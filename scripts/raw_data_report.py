"""Build the raw-data overview report in reports/raw_data/.

Usage:
    uv run python scripts/raw_data_report.py

Reads the raw parquet files for the study period in config/study.toml (run
scripts/fetch_data.py first) and writes README.md, summary.csv and figures/*.png.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

import matplotlib.pyplot as plt
import pandas as pd

from bess_markowitz.config import PROJECT_ROOT, StudyPeriod, load_markets, load_study_period
from bess_markowitz.raw import load_raw
from bess_markowitz.report import plots
from bess_markowitz.report.raw_overview import correlations, summarize, to_markdown

REPORT_DIR = PROJECT_ROOT / "reports" / "raw_data"
FIGURE_DIR = REPORT_DIR / "figures"


def main() -> int:
    period = load_study_period()
    series = load_raw(load_markets(), period)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)

    summary = summarize(series, period)
    summary.to_csv(REPORT_DIR / "summary.csv", index_label="market")

    plots.apply_style()
    figures = {
        "daily_timeseries.png": plots.daily_timeseries(series, period),
        "distributions.png": plots.distributions(series, period),
        "intraday_profile.png": plots.intraday_profile(series, period),
        "correlations.png": plots.correlation_heatmaps(
            {
                "Pearson (linear, what covariance sees)": correlations(series, period, "pearson"),
                "Spearman (rank, robust to spikes)": correlations(series, period, "spearman"),
            }
        ),
    }
    for name, fig in figures.items():
        fig.savefig(FIGURE_DIR / name, dpi=150, bbox_inches="tight")
        plt.close(fig)

    (REPORT_DIR / "README.md").write_text(_readme(summary, period), encoding="utf-8")
    print(f"Report written to {REPORT_DIR.relative_to(PROJECT_ROOT)}/")
    return 0


def _readme(summary: pd.DataFrame, period: StudyPeriod) -> str:
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"""# Raw data overview

Study period **{period.start_date} to {period.end_date}** (inclusive, {period.timezone}).
Generated {generated} by `scripts/raw_data_report.py` from the files in `data/raw/`.
Regenerate after refetching or changing `config/study.toml`.

Sources: reserve capacity prices from Fingrid open data (datasets listed in
`config/markets.toml`); day-ahead prices from the ENTSO-E Transparency Platform.
Reserve prices are in €/MW/h, day-ahead prices in €/MWh, so the two are not on a
common scale.

## Summary

Statistics use each market's native resolution (1 h for reserves, 15 min for
day-ahead), restricted to the study period. Nothing is resampled or filled.
Machine-readable copy: [summary.csv](summary.csv).

{to_markdown(summary)}

- **Missing periods** compares the rows present with every period expected in
  the study period at that resolution.
- **A03 repeated points**: prices ENTSO-E omitted because they equal the
  previous point; they take that price, as the format defines.
- **Revenue, 1 MW every hour**: sum of hourly capacity prices, i.e. income from
  selling 1 MW in every hour of the period, ignoring energy activation. Only
  defined for reserve markets.
- **Revenue from top 5 % of hours**: share of that income earned in the 5 %
  highest-priced hours; high values mean income depends on price spikes.

## Figures

### Price over time

![Daily mean and range](figures/daily_timeseries.png)

### Price distributions

Count axis is logarithmic so rare spikes remain visible.

![Distributions](figures/distributions.png)

### Hour-of-day profile

![Intraday profile](figures/intraday_profile.png)

### Correlation between reserve markets

Hourly reserve prices only; day-ahead is left out until the 15-minute to
hourly alignment is decided (BLUEPRINT.md, open decision 5).

![Correlations](figures/correlations.png)
"""


if __name__ == "__main__":
    sys.exit(main())
