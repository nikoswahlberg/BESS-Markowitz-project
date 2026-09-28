"""Summary statistics of the raw price series over the study period.

Descriptive only: series are restricted to the study period (ENTSO-E delivers
whole CET days, so its edges are trimmed here) but not resampled or filled.
Reserve prices are in €/MW/h, day-ahead prices in €/MWh.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from bess_markowitz.config import StudyPeriod
from bess_markowitz.raw import FINGRID_UNIT, RawSeries
from bess_markowitz.report.labels import display_name

TOP_SHARE_QUANTILE = 0.95  # "top 5 % of hours" for revenue concentration


@dataclass(frozen=True)
class Metric:
    """A row of the summary table: column name, human label and number format."""

    name: str
    label: str
    fmt: str


METRICS: list[Metric] = [
    Metric("unit", "Unit", "{}"),
    Metric("resolution", "Resolution", "{}"),
    Metric("rows", "Rows in period", "{:,.0f}"),
    Metric("expected_rows", "Expected rows", "{:,.0f}"),
    Metric("missing", "Missing periods", "{:,.0f}"),
    Metric("duplicates", "Duplicate timestamps", "{:,.0f}"),
    Metric("repeated", "A03 repeated points", "{:,.0f}"),
    Metric("mean", "Mean", "{:.2f}"),
    Metric("std", "Std. deviation", "{:.2f}"),
    Metric("min", "Min", "{:.2f}"),
    Metric("p05", "5th percentile", "{:.2f}"),
    Metric("median", "Median", "{:.2f}"),
    Metric("p95", "95th percentile", "{:.2f}"),
    Metric("p99", "99th percentile", "{:.2f}"),
    Metric("max", "Max", "{:.2f}"),
    Metric("skew", "Skewness", "{:.1f}"),
    Metric("excess_kurtosis", "Excess kurtosis", "{:.1f}"),
    Metric("negative_share", "Negative prices (% of periods)", "{:.1%}"),
    Metric("acf_1h", "Autocorrelation, 1 h lag", "{:.2f}"),
    Metric("acf_24h", "Autocorrelation, 24 h lag", "{:.2f}"),
    Metric("revenue_1mw", "Revenue, 1 MW every hour (€/MW)", "{:,.0f}"),
    Metric("top5_revenue_share", "Revenue from top 5 % of hours", "{:.1%}"),
]


def in_period(prices: pd.Series, period: StudyPeriod) -> pd.Series:
    """Rows whose UTC start time lies in [period.start, period.end)."""
    start = pd.Timestamp(period.start).tz_convert("UTC")
    end = pd.Timestamp(period.end).tz_convert("UTC")
    return prices[(prices.index >= start) & (prices.index < end)]


def summarize(series: list[RawSeries], period: StudyPeriod) -> pd.DataFrame:
    """One row per market with the METRICS columns, restricted to the study period.

    Revenue metrics are only defined for reserve capacity prices (€/MW/h) and are
    NaN for day-ahead energy prices.
    """
    start = pd.Timestamp(period.start).tz_convert("UTC")
    end = pd.Timestamp(period.end).tz_convert("UTC")
    rows: dict[str, dict[str, object]] = {}
    for s in series:
        prices = in_period(s.prices, period)
        unique = prices[~prices.index.duplicated(keep="first")]
        expected = pd.date_range(start, end, freq=s.resolution, inclusive="left")
        is_capacity = s.unit == FINGRID_UNIT

        row: dict[str, object] = {
            "unit": s.unit,
            "resolution": _format_resolution(s.resolution),
            "rows": len(prices),
            "expected_rows": len(expected),
            "missing": len(expected.difference(unique.index)),
            "duplicates": int(prices.index.duplicated().sum()),
            "repeated": s.n_repeated if not is_capacity else 0,
            "mean": unique.mean(),
            "std": unique.std(),
            "min": unique.min(),
            "p05": unique.quantile(0.05),
            "median": unique.median(),
            "p95": unique.quantile(0.95),
            "p99": unique.quantile(0.99),
            "max": unique.max(),
            "skew": unique.skew(),
            "excess_kurtosis": unique.kurt(),
            "negative_share": float((unique < 0).mean()),
            "acf_1h": _autocorr(unique, pd.Timedelta(hours=1)),
            "acf_24h": _autocorr(unique, pd.Timedelta(hours=24)),
            "revenue_1mw": unique.sum() if is_capacity else float("nan"),
            "top5_revenue_share": _top_share(unique) if is_capacity else float("nan"),
        }
        rows[s.key] = row
    return pd.DataFrame.from_dict(rows, orient="index")[[m.name for m in METRICS]]


def to_markdown(summary: pd.DataFrame) -> str:
    """Render the summary with metrics as rows and markets as columns."""
    header = "| Metric | " + " | ".join(display_name(k) for k in summary.index) + " |"
    align = "|---|" + "---:|" * len(summary.index)
    lines = [header, align]
    for metric in METRICS:
        cells = []
        for value in summary[metric.name]:
            cells.append("–" if pd.isna(value) else metric.fmt.format(value))
        lines.append(f"| {metric.label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def correlations(series: list[RawSeries], period: StudyPeriod, method: str) -> pd.DataFrame:
    """Correlation matrix of the reserve capacity series on their common hourly index.

    Day-ahead is left out: it is 15-minute data and how to align it to hours is
    still an open decision (BLUEPRINT.md).
    """
    columns = {}
    for s in series:
        if s.unit != FINGRID_UNIT:
            continue
        prices = in_period(s.prices, period)
        columns[s.key] = prices[~prices.index.duplicated(keep="first")]
    panel = pd.DataFrame(columns).dropna()
    return panel.corr(method=method)


def _autocorr(prices: pd.Series, lag: pd.Timedelta) -> float:
    lagged = prices.shift(freq=lag)
    aligned = pd.concat([prices, lagged], axis=1, join="inner").dropna()
    if aligned.iloc[:, 0].std() == 0 or aligned.iloc[:, 1].std() == 0:
        return float("nan")  # undefined for a constant series
    return float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))


def _top_share(prices: pd.Series) -> float:
    total = prices.sum()
    top = prices[prices >= prices.quantile(TOP_SHARE_QUANTILE)].sum()
    return float(top / total)


def _format_resolution(step: pd.Timedelta) -> str:
    minutes = int(step.total_seconds() // 60)
    return f"{minutes // 60} h" if minutes % 60 == 0 else f"{minutes} min"
