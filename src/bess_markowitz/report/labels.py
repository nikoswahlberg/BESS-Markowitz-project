"""Short human-readable market names for tables and figures."""

DISPLAY_NAMES = {
    "fcr_n": "FCR-N",
    "fcr_d_up": "FCR-D up",
    "fcr_d_down": "FCR-D down",
    "afrr_up": "aFRR up",
    "afrr_down": "aFRR down",
    "day_ahead_fi": "Day-ahead FI",
}


def display_name(key: str) -> str:
    """Short name for a market key from config/markets.toml; the key itself if unknown."""
    return DISPLAY_NAMES.get(key, key)
