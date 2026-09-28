"""Fetch raw market prices and write them to data/raw/ as parquet.

Usage:
    uv run python scripts/fetch_data.py                    # study period from config/study.toml
    uv run python scripts/fetch_data.py --start 2026-03-01 --end 2026-03-31

Dates are inclusive whole days in the study period's timezone (Europe/Helsinki).
Reads FINGRID_API_KEY and ENTSOE_TOKEN from the environment (a local .env file is
loaded if present).
Stops on the first failed request or empty result rather than writing partial data.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from dotenv import load_dotenv

from bess_markowitz.config import RAW_DATA_DIR, StudyPeriod, load_markets, load_study_period
from bess_markowitz.fetch import entsoe, fingrid
from bess_markowitz.raw import raw_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--start", type=date.fromisoformat, help="YYYY-MM-DD, inclusive (default: study period)"
    )
    parser.add_argument(
        "--end", type=date.fromisoformat, help="YYYY-MM-DD, inclusive (default: study period)"
    )
    parser.add_argument(
        "--source",
        choices=["all", "fingrid", "entsoe"],
        default="all",
        help="which API to fetch from",
    )
    args = parser.parse_args()
    study = load_study_period()
    try:
        period = StudyPeriod(
            start_date=args.start or study.start_date,
            end_date=args.end or study.end_date,
            timezone=study.timezone,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Period {period.start_date}..{period.end_date} ({period.timezone})", flush=True)

    load_dotenv()
    # Read every key needed before fetching anything, so a missing one fails immediately.
    fetch_fingrid = args.source in ("all", "fingrid")
    fetch_entsoe = args.source in ("all", "entsoe")
    api_key = fingrid.api_key_from_env() if fetch_fingrid else ""
    token = entsoe.token_from_env() if fetch_entsoe else ""

    markets = load_markets()
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    if fetch_fingrid:
        for market in markets.fingrid:
            print(f"Fingrid {market.key} (dataset {market.dataset_id}) ...", flush=True)
            df = fingrid.fetch_dataset(market.dataset_id, period.start, period.end, api_key)
            if df.empty:
                print(f"  No data returned for {market.key}; stopping.", file=sys.stderr)
                return 1
            path = raw_path("fingrid", market.key, period)
            df.to_parquet(path, index=False)
            print(f"  {len(df)} rows -> {path.relative_to(RAW_DATA_DIR.parents[1])}")

    if fetch_entsoe:
        for market in markets.entsoe:
            print(f"ENTSO-E {market.key} ({market.bidding_zone}) ...", flush=True)
            df = entsoe.fetch_day_ahead_prices(market.bidding_zone, period.start, period.end, token)
            if df.empty:
                print(f"  No data returned for {market.key}; stopping.", file=sys.stderr)
                return 1
            path = raw_path("entsoe", market.key, period)
            df.to_parquet(path, index=False)
            print(f"  {len(df)} rows -> {path.relative_to(RAW_DATA_DIR.parents[1])}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
