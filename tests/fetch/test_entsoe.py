"""Tests for the ENTSO-E client. No network: HTTP is replaced by a fake session."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
import requests

from bess_markowitz.fetch import entsoe

FIXTURES = Path(__file__).parents[1] / "fixtures"
FI = "10YFI-1--------U"
SECRET = "secret-token-value"


class FakeResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url: str, params: dict, timeout: float) -> FakeResponse:
        self.calls.append(params)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def sample_xml() -> bytes:
    """Real A44 document for FI, delivery 2026-09-01..02 (PT15M, curve A03), saved 2026-09-28."""
    return (FIXTURES / "entsoe_a44_fi_sample.xml").read_bytes()


@pytest.fixture
def ack_xml() -> bytes:
    """Real 'no matching data' acknowledgement, saved 2026-09-28."""
    return (FIXTURES / "entsoe_ack_no_data.xml").read_bytes()


def test_parse_expands_every_quarter_hour(sample_xml):
    df = entsoe.parse_day_ahead_xml(sample_xml)

    assert list(df.columns) == entsoe.COLUMNS
    assert len(df) == 2 * 96  # two delivery days of 15-minute slots
    assert set(df["resolution"]) == {"PT15M"}
    assert df["start_time"].iloc[0] == pd.Timestamp("2026-08-31T22:00:00Z")
    assert df["start_time"].diff().dropna().eq(pd.Timedelta(minutes=15)).all()


def test_parse_a03_omitted_point_repeats_previous_price(sample_xml):
    df = entsoe.parse_day_ahead_xml(sample_xml)

    repeated = df.index[df["repeated"]].tolist()
    assert repeated == [12]
    assert df.loc[12, "price_eur_mwh"] == df.loc[11, "price_eur_mwh"]
    assert (~df["repeated"]).sum() == 191  # exactly the points present in the XML


def test_parse_acknowledgement_raises_with_reason(ack_xml):
    with pytest.raises(entsoe.EntsoeError, match="No matching data found"):
        entsoe.parse_day_ahead_xml(ack_xml)


def test_fetch_splits_ranges_longer_than_a_year(sample_xml):
    session = FakeSession([FakeResponse(200, sample_xml), FakeResponse(200, sample_xml)])
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2025, 6, 1, tzinfo=UTC)

    entsoe.fetch_day_ahead_prices(FI, start, end, token="t", session=session)

    assert [(c["periodStart"], c["periodEnd"]) for c in session.calls] == [
        ("202401010000", "202412310000"),
        ("202412310000", "202506010000"),
    ]


def test_http_error_reports_reason(ack_xml):
    session = FakeSession([FakeResponse(400, ack_xml)])
    start = datetime(2030, 1, 1, tzinfo=UTC)
    end = datetime(2030, 1, 2, tzinfo=UTC)

    with pytest.raises(entsoe.EntsoeError, match="HTTP 400.*No matching data"):
        entsoe.fetch_day_ahead_prices(FI, start, end, token=SECRET, session=session)


def test_connection_error_does_not_leak_token():
    leaky = requests.ConnectionError(f"Max retries exceeded with url: /api?securityToken={SECRET}")
    session = FakeSession([leaky])
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 2, tzinfo=UTC)

    with pytest.raises(entsoe.EntsoeError) as info:
        entsoe.fetch_day_ahead_prices(FI, start, end, token=SECRET, session=session)

    assert SECRET not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


def test_token_from_env_missing(monkeypatch):
    monkeypatch.delenv("ENTSOE_TOKEN", raising=False)

    with pytest.raises(entsoe.EntsoeError, match="ENTSOE_TOKEN"):
        entsoe.token_from_env()
