# BESS reserve market allocation

Mean-variance and mean-CVaR allocation of a battery's capacity across
Finnish reserve markets (FCR-N, FCR-D up/down, aFRR) and the day-ahead spread.

See BLUEPRINT.md for the repo layout, open modelling decisions and decision log.
Keep it up to date when the structure or a decision changes.

## Stack
- Python 3.12, uv for dependency management
- pandas, numpy, cvxpy, matplotlib
- pytest for tests

## Conventions
- All prices in €/MW/h, all energy in MWh. State units in every docstring.
- Data fetch scripts write raw parquet to data/raw/, never committed.
- API keys from environment variables (FINGRID_API_KEY, ENTSOE_TOKEN), never hardcoded.
- No notebook may contain the optimization logic — notebooks call src/, nothing more.
- Type hints everywhere. Run `ruff check` and `pytest` before declaring anything done.

## Domain constraints that must hold
- Capacity sold in one hour cannot exceed rated power (30 MW).
- The same MW cannot be sold into two markets in the same hour.
- FCR-N requires symmetric up/down capability.

## What I want from you
- Explain the modelling choice before writing optimization code.
- Prefer explicit loops over vectorized cleverness in the optimization layer; I need to read it.
- Never invent data. If an API call fails, stop and tell me.