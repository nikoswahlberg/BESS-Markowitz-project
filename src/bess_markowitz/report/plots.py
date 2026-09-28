"""Static figures for reports (matplotlib, PNG).

One market per panel so every panel keeps a single colour and its own y-scale;
units are stated in each panel title (€/MW/h for reserves, €/MWh for day-ahead).
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure

from bess_markowitz.config import StudyPeriod
from bess_markowitz.raw import RawSeries
from bess_markowitz.report.labels import display_name
from bess_markowitz.report.raw_overview import in_period

# Reference palette (dataviz skill), light mode.
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES = "#2a78d6"
SERIES_BAND = "#b7d3f6"
DIVERGING = LinearSegmentedColormap.from_list(
    "blue_gray_red", ["#184f95", "#6da7ec", "#f0efec", "#ec8a89", "#b3302f"]
)


def apply_style() -> None:
    """Recessive chrome: hairline solid grid, muted axes, system sans."""
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.family": "sans-serif",
            "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
            "font.size": 9,
            "text.color": INK_PRIMARY,
            "axes.labelcolor": INK_SECONDARY,
            "axes.edgecolor": BASELINE,
            "axes.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.5,
            "grid.linestyle": "-",
            "xtick.color": INK_MUTED,
            "ytick.color": INK_MUTED,
            "xtick.labelcolor": INK_SECONDARY,
            "ytick.labelcolor": INK_SECONDARY,
            "axes.titlesize": 9.5,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
        }
    )


def daily_timeseries(series: list[RawSeries], period: StudyPeriod) -> Figure:
    """Daily mean line with a daily min–max band, one panel per market (local days)."""
    fig, axes = plt.subplots(len(series), 1, figsize=(10, 1.9 * len(series)), sharex=True)
    for ax, s in zip(np.atleast_1d(axes), series, strict=True):
        local = _local(in_period(s.prices, period), period)
        daily = local.resample("1D").agg(["mean", "min", "max"])
        ax.fill_between(daily.index, daily["min"], daily["max"], color=SERIES_BAND, lw=0)
        ax.plot(daily.index, daily["mean"], color=SERIES, lw=1.5)
        _zero_line(ax, daily["min"].min())
        ax.set_title(f"{display_name(s.key)}  ·  {s.unit}", color=INK_PRIMARY)
        ax.margins(x=0)
    fig.suptitle(
        "Daily mean price (line) and daily min–max range (band)",
        x=0.01,
        ha="left",
        color=INK_SECONDARY,
        fontsize=9,
    )
    fig.tight_layout()
    return fig


def distributions(series: list[RawSeries], period: StudyPeriod) -> Figure:
    """Histogram per market on a log count scale, with median and 99th percentile marked."""
    fig, axes = _grid(len(series))
    for ax, s in zip(axes, series, strict=False):
        prices = in_period(s.prices, period)
        ax.hist(prices, bins=60, color=SERIES, rwidth=0.85, log=True)
        ax.set_ylim(top=ax.get_ylim()[1] * 8)  # headroom so labels clear the tallest bar
        # Stagger the two labels vertically so they never collide when the values are close.
        for q, label, y in ((0.5, "median", 1.0), (0.99, "p99", 0.9)):
            value = prices.quantile(q)
            ax.axvline(value, color=INK_SECONDARY, lw=0.8)
            ax.annotate(
                f"{label} {value:.1f}",
                (value, y),
                xycoords=("data", "axes fraction"),
                xytext=(3, -2),
                textcoords="offset points",
                va="top",
                fontsize=7.5,
                color=INK_SECONDARY,
            )
        ax.set_title(f"{display_name(s.key)}  ·  {s.unit}")
        ax.set_ylabel("periods (log)")
    _hide_unused(axes, len(series))
    fig.tight_layout()
    return fig


def intraday_profile(series: list[RawSeries], period: StudyPeriod) -> Figure:
    """Median price by local hour of day with the interquartile range as a band."""
    fig, axes = _grid(len(series))
    for ax, s in zip(axes, series, strict=False):
        local = _local(in_period(s.prices, period), period)
        by_hour = local.groupby(local.index.hour).quantile([0.25, 0.5, 0.75]).unstack()
        ax.fill_between(by_hour.index, by_hour[0.25], by_hour[0.75], color=SERIES_BAND, lw=0)
        ax.plot(by_hour.index, by_hour[0.5], color=SERIES, lw=1.5)
        _zero_line(ax, by_hour[0.25].min())
        ax.set_xticks(range(0, 24, 3))
        ax.set_xlim(0, 23)
        ax.set_title(f"{display_name(s.key)}  ·  {s.unit}")
        ax.set_xlabel(f"hour of day ({period.timezone})")
    _hide_unused(axes, len(series))
    fig.suptitle(
        "Median price by hour of day (line) and interquartile range (band)",
        x=0.01,
        ha="left",
        color=INK_SECONDARY,
        fontsize=9,
    )
    fig.tight_layout()
    return fig


def correlation_heatmaps(matrices: dict[str, pd.DataFrame]) -> Figure:
    """Side-by-side correlation heatmaps on a shared −1…1 diverging scale."""
    fig, axes = plt.subplots(
        1, len(matrices), figsize=(5.2 * len(matrices), 4.6), layout="constrained"
    )
    image = None
    for i_ax, (ax, (title, corr)) in enumerate(
        zip(np.atleast_1d(axes), matrices.items(), strict=True)
    ):
        labels = [display_name(k) for k in corr.columns]
        image = ax.imshow(corr.to_numpy(), cmap=DIVERGING, vmin=-1, vmax=1)
        ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right")
        # Row labels only on the first heatmap; the matrices share their market order.
        ax.set_yticks(range(len(labels)), labels if i_ax == 0 else [])
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_visible(False)
        for i in range(len(labels)):
            for j in range(len(labels)):
                value = corr.iat[i, j]
                ink = SURFACE if abs(value) > 0.6 else INK_PRIMARY
                ax.text(j, i, f"{value:.2f}", ha="center", va="center", color=ink, fontsize=8.5)
        ax.set_title(title)
    if image is not None:
        fig.colorbar(image, ax=axes, shrink=0.75, label="correlation")
    return fig


def _local(prices: pd.Series, period: StudyPeriod) -> pd.Series:
    unique = prices[~prices.index.duplicated(keep="first")]
    return unique.tz_convert(period.timezone)


def _zero_line(ax: Axes, lowest: float) -> None:
    if lowest < 0:
        ax.axhline(0, color=BASELINE, lw=0.8)


def _grid(n: int) -> tuple[Figure, list[Axes]]:
    cols = 3
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(11, 3.1 * rows))
    return fig, list(np.atleast_1d(axes).ravel())


def _hide_unused(axes: list[Axes], used: int) -> None:
    for ax in axes[used:]:
        ax.set_visible(False)
