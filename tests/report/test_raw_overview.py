"""Tests for the raw-data summary. All price series here are synthetic, built to
have known statistics; they are not market data."""

from datetime import date

import pandas as pd
import pytest

from bess_markowitz.config import StudyPeriod
from bess_markowitz.raw import ENTSOE_UNIT, FINGRID_UNIT, RawSeries
from bess_markowitz.report.raw_overview import METRICS, correlations, summarize, to_markdown

# Two Helsinki days in winter (UTC+2): 2026-01-01 00:00 local = 2025-12-31 22:00 UTC.
PERIOD = StudyPeriod(date(2026, 1, 1), date(2026, 1, 2), "Europe/Helsinki")
HOURS = pd.date_range("2025-12-31 22:00", periods=48, freq="1h", tz="UTC")


def capacity(key: str, values: list[float], index: pd.DatetimeIndex = HOURS) -> RawSeries:
    return RawSeries(
        key, "fingrid", FINGRID_UNIT, pd.Timedelta(hours=1), pd.Series(values, index=index), 0
    )


def test_complete_series_has_no_missing_and_exact_revenue():
    s = capacity("fcr_n", [10.0] * 48)

    row = summarize([s], PERIOD).loc["fcr_n"]

    assert row["rows"] == row["expected_rows"] == 48
    assert row["missing"] == 0
    assert row["revenue_1mw"] == pytest.approx(480.0)  # 48 h x 10 €/MW/h x 1 MW


def test_missing_and_duplicate_hours_are_counted():
    index = HOURS.delete([5, 6]).append(HOURS[[0]])  # two gaps, one duplicate
    s = capacity("fcr_n", [1.0] * len(index), index)

    row = summarize([s], PERIOD).loc["fcr_n"]

    assert row["missing"] == 2
    assert row["duplicates"] == 1


def test_rows_outside_period_are_excluded():
    extended = HOURS.append(pd.DatetimeIndex(["2026-01-02 22:00"], tz="UTC"))  # next local day
    s = capacity("fcr_n", [1.0] * 48 + [999.0], extended)

    row = summarize([s], PERIOD).loc["fcr_n"]

    assert row["rows"] == 48
    assert row["max"] == 1.0


def test_top_share_measures_spike_dependence():
    values = [1.0] * 45 + [100.0] * 3  # top 5 % of 48 hours = the 3 spikes
    s = capacity("fcr_n", values)

    row = summarize([s], PERIOD).loc["fcr_n"]

    assert row["top5_revenue_share"] == pytest.approx(300 / 345)


def test_revenue_metrics_undefined_for_day_ahead():
    quarter_hours = pd.date_range("2025-12-31 22:00", periods=192, freq="15min", tz="UTC")
    s = RawSeries(
        "day_ahead_fi",
        "entsoe",
        ENTSOE_UNIT,
        pd.Timedelta(minutes=15),
        pd.Series([50.0] * 192, index=quarter_hours),
        7,
    )

    row = summarize([s], PERIOD).loc["day_ahead_fi"]

    assert row["expected_rows"] == 192
    assert row["repeated"] == 7
    assert pd.isna(row["revenue_1mw"])


def test_correlations_cover_reserves_only():
    a = capacity("fcr_n", [float(i) for i in range(48)])
    b = capacity("afrr_up", [float(2 * i) for i in range(48)])
    da = RawSeries(
        "day_ahead_fi",
        "entsoe",
        ENTSOE_UNIT,
        pd.Timedelta(hours=1),
        pd.Series([1.0] * 48, index=HOURS),
        0,
    )

    corr = correlations([a, b, da], PERIOD, "pearson")

    assert list(corr.columns) == ["fcr_n", "afrr_up"]
    assert corr.loc["fcr_n", "afrr_up"] == pytest.approx(1.0)


def test_markdown_has_one_row_per_metric():
    table = to_markdown(summarize([capacity("fcr_n", [1.0] * 48)], PERIOD))

    assert "| Metric | FCR-N |" in table
    assert len(table.splitlines()) == 2 + len(METRICS)
