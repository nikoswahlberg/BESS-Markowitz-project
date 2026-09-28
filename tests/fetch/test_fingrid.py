"""Tests for the Fingrid client. No network: HTTP is replaced by a fake session."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from bess_markowitz.fetch import fingrid

FIXTURES = Path(__file__).parents[1] / "fixtures"
START = datetime(2025, 9, 1, tzinfo=UTC)
END = datetime(2025, 9, 1, 3, tzinfo=UTC)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict:
        return self._payload


class FakeSession:
    """Returns queued responses in order and records the params of each call."""

    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url: str, params: dict, headers: dict, timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    monkeypatch.setattr(fingrid, "MIN_REQUEST_INTERVAL_S", 0.0)


@pytest.fixture
def sample_payload() -> dict:
    """Real response for dataset 317 (FCR-N prices), saved 2026-09-28."""
    return json.loads((FIXTURES / "fingrid_317_sample.json").read_text())


def test_parse_rows_types_and_order(sample_payload):
    df = fingrid.parse_rows(sample_payload["data"])

    assert list(df.columns) == fingrid.COLUMNS
    assert str(df["start_time"].dtype).endswith("UTC]")
    assert df["start_time"].is_monotonic_increasing  # API returns newest first
    assert df["start_time"].iloc[0] == pd.Timestamp("2025-09-01T00:00:00Z")
    assert df["value"].tolist() == [10.45, 11.54, 12.06]


def test_parse_rows_empty_returns_typed_frame():
    df = fingrid.parse_rows([])

    assert df.empty
    assert list(df.columns) == fingrid.COLUMNS


def test_fetch_dataset_sends_key_in_header_and_utc_range(sample_payload):
    session = FakeSession([FakeResponse(200, sample_payload)])

    fingrid.fetch_dataset(317, START, END, api_key="k", session=session)

    call = session.calls[0]
    assert call["url"].endswith("/datasets/317/data")
    assert call["headers"] == {"x-api-key": "k"}
    assert call["params"]["startTime"] == "2025-09-01T00:00:00Z"
    assert call["params"]["endTime"] == "2025-09-01T03:00:00Z"


def test_fetch_dataset_follows_pagination(sample_payload):
    rows = sample_payload["data"]
    page1 = {"data": rows[:2], "pagination": {"nextPage": 2}}
    page2 = {"data": rows[2:], "pagination": {"nextPage": None}}
    session = FakeSession([FakeResponse(200, page1), FakeResponse(200, page2)])

    df = fingrid.fetch_dataset(317, START, END, api_key="k", session=session)

    assert [c["params"]["page"] for c in session.calls] == [1, 2]
    assert len(df) == 3


def test_fetch_dataset_raises_on_http_error():
    session = FakeSession([FakeResponse(429, text="Rate limit exceeded")])

    with pytest.raises(fingrid.FingridError, match="HTTP 429"):
        fingrid.fetch_dataset(317, START, END, api_key="k", session=session)


def test_fetch_dataset_rejects_naive_datetimes():
    with pytest.raises(ValueError, match="timezone-aware"):
        fingrid.fetch_dataset(317, datetime(2025, 9, 1), END, api_key="k", session=FakeSession([]))


def test_api_key_from_env_missing(monkeypatch):
    monkeypatch.delenv("FINGRID_API_KEY", raising=False)

    with pytest.raises(fingrid.FingridError, match="FINGRID_API_KEY"):
        fingrid.api_key_from_env()
