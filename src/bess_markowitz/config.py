"""Load project configuration from the TOML files in config/."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"


@dataclass(frozen=True)
class FingridMarket:
    """A reserve capacity market published as a Fingrid dataset (prices in €/MW/h)."""

    key: str
    dataset_id: int
    name: str


@dataclass(frozen=True)
class EntsoeMarket:
    """A day-ahead market on the ENTSO-E transparency platform (prices in €/MWh)."""

    key: str
    bidding_zone: str


@dataclass(frozen=True)
class MarketsConfig:
    fingrid: list[FingridMarket]
    entsoe: list[EntsoeMarket]


def load_markets(path: Path = CONFIG_DIR / "markets.toml") -> MarketsConfig:
    """Read config/markets.toml into typed market definitions."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    fingrid = [
        FingridMarket(key=key, dataset_id=int(entry["dataset_id"]), name=str(entry["name"]))
        for key, entry in raw.get("fingrid", {}).items()
    ]
    entsoe = [
        EntsoeMarket(key=key, bidding_zone=str(entry["bidding_zone"]))
        for key, entry in raw.get("entsoe", {}).items()
    ]
    return MarketsConfig(fingrid=fingrid, entsoe=entsoe)


@dataclass(frozen=True)
class StudyPeriod:
    """Research period as inclusive local dates, e.g. 2026-01-01..2026-06-30 in Europe/Helsinki."""

    start_date: date
    end_date: date
    timezone: str

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError(f"Study period ends ({self.end_date}) before it starts")

    @property
    def start(self) -> datetime:
        """Inclusive start: local midnight at the beginning of start_date (tz-aware)."""
        return datetime.combine(self.start_date, time(0), tzinfo=ZoneInfo(self.timezone))

    @property
    def end(self) -> datetime:
        """Exclusive end: local midnight after end_date (tz-aware)."""
        next_day = self.end_date + timedelta(days=1)
        return datetime.combine(next_day, time(0), tzinfo=ZoneInfo(self.timezone))


def load_study_period(path: Path = CONFIG_DIR / "study.toml") -> StudyPeriod:
    """Read the research period from config/study.toml."""
    with path.open("rb") as f:
        period = tomllib.load(f)["period"]
    return StudyPeriod(
        start_date=period["start"], end_date=period["end"], timezone=str(period["timezone"])
    )
