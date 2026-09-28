"""Client for the Fingrid open data API (https://data.fingrid.fi).

Fetches a dataset's time series for a UTC time range. The reserve capacity price
datasets used in this project are hourly and in €/MW/h. Any HTTP or payload error
raises FingridError; nothing is retried silently or filled in.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import pandas as pd
import requests

BASE_URL = "https://data.fingrid.fi/api"
PAGE_SIZE = 20_000  # API maximum rows per page
MIN_REQUEST_INTERVAL_S = 6.5  # the API allows 10 requests per minute per key
TIMEOUT_S = 60

COLUMNS = ["dataset_id", "start_time", "end_time", "value"]

_last_request_at = 0.0


class FingridError(RuntimeError):
    """The Fingrid API returned an error or a payload we don't understand."""


def api_key_from_env() -> str:
    """Return FINGRID_API_KEY from the environment, or raise if it is missing."""
    key = os.environ.get("FINGRID_API_KEY")
    if not key:
        raise FingridError("FINGRID_API_KEY is not set in the environment")
    return key


def fetch_dataset(
    dataset_id: int,
    start: datetime,
    end: datetime,
    api_key: str,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch every row of a dataset whose start time lies in [start, end).

    Args:
        dataset_id: Fingrid dataset ID, e.g. 317 for FCR-N hourly prices.
        start: Inclusive range start, timezone-aware.
        end: Exclusive range end, timezone-aware.
        api_key: Fingrid open data API key.
        session: Optional requests session (for connection reuse or tests).

    Returns:
        DataFrame with columns dataset_id, start_time, end_time (UTC timestamps)
        and value (in the dataset's unit; €/MW/h for capacity prices), sorted
        by start_time. Empty if the API has no data for the range.
    """
    _require_tz_aware(start, end)
    session = session or requests.Session()
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = _get_page(session, dataset_id, start, end, page, api_key)
        rows.extend(payload["data"])
        next_page = payload["pagination"].get("nextPage")
        if next_page is None:
            break
        page = int(next_page)
    return parse_rows(rows)


def parse_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Turn the API's list of row dicts into a typed DataFrame (see fetch_dataset)."""
    if not rows:
        return pd.DataFrame(
            {
                "dataset_id": pd.Series(dtype="int64"),
                "start_time": pd.Series(dtype="datetime64[ns, UTC]"),
                "end_time": pd.Series(dtype="datetime64[ns, UTC]"),
                "value": pd.Series(dtype="float64"),
            }
        )
    df = pd.DataFrame(rows).rename(
        columns={"datasetId": "dataset_id", "startTime": "start_time", "endTime": "end_time"}
    )
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise FingridError(f"Fingrid rows are missing fields: {sorted(missing)}")
    df = df[COLUMNS]
    df["dataset_id"] = df["dataset_id"].astype("int64")
    df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
    df["end_time"] = pd.to_datetime(df["end_time"], utc=True)
    df["value"] = df["value"].astype("float64")
    return df.sort_values("start_time", ignore_index=True)


def _get_page(
    session: requests.Session,
    dataset_id: int,
    start: datetime,
    end: datetime,
    page: int,
    api_key: str,
) -> dict[str, Any]:
    params = {
        "startTime": _iso_utc(start),
        "endTime": _iso_utc(end),
        "format": "json",
        "pageSize": PAGE_SIZE,
        "page": page,
    }
    _throttle()
    try:
        response = session.get(
            f"{BASE_URL}/datasets/{dataset_id}/data",
            params=params,
            headers={"x-api-key": api_key},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as exc:
        raise FingridError(f"Request for dataset {dataset_id} failed: {exc}") from exc
    if response.status_code != 200:
        raise FingridError(
            f"Dataset {dataset_id}, page {page}: HTTP {response.status_code}: {response.text[:300]}"
        )
    payload = response.json()
    if "data" not in payload or "pagination" not in payload:
        raise FingridError(f"Dataset {dataset_id}: unexpected payload keys {list(payload)}")
    return payload


def _throttle() -> None:
    """Sleep so consecutive requests stay under the API's per-minute limit."""
    global _last_request_at
    wait = MIN_REQUEST_INTERVAL_S - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _iso_utc(ts: datetime) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_tz_aware(*timestamps: datetime) -> None:
    for ts in timestamps:
        if ts.tzinfo is None:
            raise ValueError(f"Timestamp {ts} must be timezone-aware")
