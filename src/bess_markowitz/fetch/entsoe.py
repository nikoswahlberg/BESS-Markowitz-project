"""Client for day-ahead prices from the ENTSO-E transparency platform.

Fetches document type A44 (day-ahead prices) for one bidding zone and returns
prices in €/MWh at the resolution ENTSO-E publishes (PT60M historically, PT15M
since the move to 15-minute day-ahead products). Any HTTP or payload error
raises EntsoeError.

The API only accepts the token as a URL query parameter, so error messages here
never include the request URL or the underlying requests exception text.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pandas as pd
import requests

BASE_URL = "https://web-api.tp.entsoe.eu/api"
DAY_AHEAD_DOCUMENT_TYPE = "A44"
MAX_SPAN = timedelta(days=365)  # API limit per request
TIMEOUT_S = 120

COLUMNS = ["start_time", "resolution", "price_eur_mwh", "repeated"]


class EntsoeError(RuntimeError):
    """The ENTSO-E API returned an error or a document we don't understand."""


def token_from_env() -> str:
    """Return ENTSOE_TOKEN from the environment, or raise if it is missing."""
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        raise EntsoeError("ENTSOE_TOKEN is not set in the environment")
    return token


def fetch_day_ahead_prices(
    bidding_zone: str,
    start: datetime,
    end: datetime,
    token: str,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch day-ahead prices for a bidding zone over [start, end).

    Requests longer than one year are split into yearly chunks. ENTSO-E returns
    whole delivery days, so rows slightly outside [start, end) and duplicates at
    chunk borders can appear; they are kept as delivered and handled in prep/.

    Args:
        bidding_zone: EIC code, e.g. "10YFI-1--------U" for Finland.
        start: Inclusive range start, timezone-aware.
        end: Exclusive range end, timezone-aware.
        token: ENTSO-E security token.
        session: Optional requests session (for connection reuse or tests).

    Returns:
        DataFrame with columns start_time (UTC), resolution (e.g. "PT15M"),
        price_eur_mwh (€/MWh) and repeated (True where the point was omitted in
        an A03 curve and takes the previous point's price, as the format defines).
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    session = session or requests.Session()
    frames: list[pd.DataFrame] = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + MAX_SPAN, end)
        xml = _get_document(session, bidding_zone, chunk_start, chunk_end, token)
        frames.append(parse_day_ahead_xml(xml))
        chunk_start = chunk_end
    return pd.concat(frames, ignore_index=True).sort_values("start_time", ignore_index=True)


def parse_day_ahead_xml(xml: bytes) -> pd.DataFrame:
    """Parse an A44 Publication_MarketDocument into rows (see fetch_day_ahead_prices)."""
    root = ET.fromstring(xml)
    ns = _namespace(root)
    if root.tag.endswith("Acknowledgement_MarketDocument"):
        reason = root.findtext(f".//{ns}Reason/{ns}text", default="no reason given")
        raise EntsoeError(f"ENTSO-E returned an acknowledgement instead of data: {reason}")

    starts: list[pd.Timestamp] = []
    resolutions: list[str] = []
    prices: list[float] = []
    repeated: list[bool] = []

    for series in root.iter(f"{ns}TimeSeries"):
        curve_type = series.findtext(f"{ns}curveType", default="A01")
        for period in series.iter(f"{ns}Period"):
            period_start = pd.Timestamp(period.findtext(f"{ns}timeInterval/{ns}start"))
            period_end = pd.Timestamp(period.findtext(f"{ns}timeInterval/{ns}end"))
            resolution = period.findtext(f"{ns}resolution", default="")
            step = _resolution_to_timedelta(resolution)
            n_slots = int((period_end - period_start) / step)

            points: dict[int, float] = {}
            for point in period.iter(f"{ns}Point"):
                position = int(point.findtext(f"{ns}position", default="0"))
                points[position] = float(point.findtext(f"{ns}price.amount", default="nan"))

            if 1 not in points:
                raise EntsoeError(f"Period starting {period_start} has no point at position 1")
            last_price = points[1]
            for position in range(1, n_slots + 1):
                is_repeat = position not in points
                if is_repeat and curve_type != "A03":
                    raise EntsoeError(
                        f"Curve type {curve_type} period starting {period_start} "
                        f"is missing position {position}"
                    )
                price = last_price if is_repeat else points[position]
                starts.append(period_start + (position - 1) * step)
                resolutions.append(resolution)
                prices.append(price)
                repeated.append(is_repeat)
                last_price = price

    return pd.DataFrame(
        {
            "start_time": pd.to_datetime(starts, utc=True),
            "resolution": pd.Series(resolutions, dtype="string"),
            "price_eur_mwh": pd.Series(prices, dtype="float64"),
            "repeated": pd.Series(repeated, dtype="bool"),
        }
    )


def _get_document(
    session: requests.Session,
    bidding_zone: str,
    start: datetime,
    end: datetime,
    token: str,
) -> bytes:
    params = {
        "securityToken": token,
        "documentType": DAY_AHEAD_DOCUMENT_TYPE,
        "in_Domain": bidding_zone,
        "out_Domain": bidding_zone,
        "periodStart": _entsoe_time(start),
        "periodEnd": _entsoe_time(end),
    }
    try:
        response = session.get(BASE_URL, params=params, timeout=TIMEOUT_S)
    except requests.RequestException as exc:
        # Deliberately drop exc's message and chain: it contains the URL with the token.
        raise EntsoeError(
            f"Request for {bidding_zone} {start:%Y-%m-%d}..{end:%Y-%m-%d} failed "
            f"({type(exc).__name__})"
        ) from None
    if response.status_code != 200:
        detail = _acknowledgement_reason(response.content)
        raise EntsoeError(f"HTTP {response.status_code} for {bidding_zone}: {detail}")
    return response.content


def _acknowledgement_reason(xml: bytes) -> str:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return "response body is not XML"
    ns = _namespace(root)
    return root.findtext(f".//{ns}Reason/{ns}text", default="no reason given")


def _namespace(root: ET.Element) -> str:
    """Return the '{uri}' prefix of the root tag, or '' if it has none."""
    match = re.match(r"\{[^}]*\}", root.tag)
    return match.group(0) if match else ""


def _resolution_to_timedelta(resolution: str) -> pd.Timedelta:
    match = re.fullmatch(r"PT(\d+)M", resolution)
    if not match:
        raise EntsoeError(f"Unsupported resolution {resolution!r}")
    return pd.Timedelta(minutes=int(match.group(1)))


def _entsoe_time(ts: datetime) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y%m%d%H%M")
