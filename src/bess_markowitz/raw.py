"""Load the raw parquet files written by scripts/fetch_data.py.

Read-only access to data/raw/: no cleaning, trimming or resampling happens here.
Reserve capacity prices are in €/MW/h, day-ahead prices in €/MWh.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from bess_markowitz.config import RAW_DATA_DIR, MarketsConfig, StudyPeriod

FINGRID_UNIT = "€/MW/h"
ENTSOE_UNIT = "€/MWh"


@dataclass(frozen=True)
class RawSeries:
    """One market's raw price series as fetched.

    Attributes:
        key: Market key from config/markets.toml, e.g. "fcr_n".
        source: "fingrid" or "entsoe".
        unit: "€/MW/h" for reserve capacity, "€/MWh" for day-ahead energy.
        resolution: Length of one delivery period (1 h or 15 min).
        prices: Prices indexed by UTC period start, in `unit`. Duplicates kept.
        n_repeated: Points ENTSO-E omitted in an A03 curve (0 for Fingrid).
    """

    key: str
    source: str
    unit: str
    resolution: pd.Timedelta
    prices: pd.Series
    n_repeated: int


def raw_path(source: str, key: str, period: StudyPeriod, raw_dir: Path = RAW_DATA_DIR) -> Path:
    """Path of the raw parquet file for one market and study period."""
    span = f"{period.start_date:%Y%m%d}_{period.end_date:%Y%m%d}"
    return raw_dir / f"{source}_{key}_{span}.parquet"


def load_raw(
    markets: MarketsConfig, period: StudyPeriod, raw_dir: Path = RAW_DATA_DIR
) -> list[RawSeries]:
    """Load every configured market's raw file for the period, Fingrid first."""
    series: list[RawSeries] = []
    for market in markets.fingrid:
        df = _read(raw_path("fingrid", market.key, period, raw_dir))
        resolution = _single_resolution((df["end_time"] - df["start_time"]).unique(), market.key)
        prices = pd.Series(
            df["value"].to_numpy(), index=pd.DatetimeIndex(df["start_time"]), name=market.key
        )
        series.append(RawSeries(market.key, "fingrid", FINGRID_UNIT, resolution, prices, 0))
    for market in markets.entsoe:
        df = _read(raw_path("entsoe", market.key, period, raw_dir))
        # ENTSO-E resolutions are ISO 8601 minute durations such as "PT15M" or "PT60M".
        steps = [pd.Timedelta(minutes=int(r[2:-1])) for r in df["resolution"].unique()]
        resolution = _single_resolution(steps, market.key)
        prices = pd.Series(
            df["price_eur_mwh"].to_numpy(),
            index=pd.DatetimeIndex(df["start_time"]),
            name=market.key,
        )
        n_repeated = int(df["repeated"].sum())
        series.append(RawSeries(market.key, "entsoe", ENTSOE_UNIT, resolution, prices, n_repeated))
    return series


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} not found in {path.parent}. Run scripts/fetch_data.py first."
        )
    return pd.read_parquet(path)


def _single_resolution(steps: Iterable[object], key: str) -> pd.Timedelta:
    unique = sorted({pd.Timedelta(s) for s in steps})
    if len(unique) != 1:
        raise ValueError(f"{key}: expected one resolution, found {unique}")
    return unique[0]
