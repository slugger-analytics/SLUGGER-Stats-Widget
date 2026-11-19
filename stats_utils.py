"""Pure, Streamlit-free helpers for the ALPB Player Stats widget.

Kept in a separate module (no ``import streamlit``) so the season-selection
logic can be unit-tested without booting the Streamlit app, whose module body
executes network + UI calls on import.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

_warned_no_season_guid = False


def select_season_rows(
    stats_by_season: dict, season_guid: str | None
) -> list[tuple[str, dict]]:
    """Choose which ``(season_guid, season_data)`` entries to aggregate.

    iScore returns a player's stats keyed by season GUID. This widget calls
    iScore directly, so nothing upstream drops the junk "DO-NOT-USE" season or
    prior seasons — without constraining here a player shows up once per season.

    - ``season_guid`` set and present   -> just that one season.
    - ``season_guid`` set but absent    -> no rows (player has no current-season line).
    - ``season_guid`` unset/empty       -> all seasons (legacy behavior), warned once.

    PA/BF gating is intentionally NOT done here — it stays the caller's job so
    existing gating behavior is unchanged.
    """
    if not stats_by_season:
        return []

    if season_guid:
        season_data = stats_by_season.get(season_guid)
        if season_data is None:
            return []
        return [(season_guid, season_data)]

    _warn_missing_season_guid_once()
    return list(stats_by_season.items())


def _warn_missing_season_guid_once() -> None:
    """Log a single warning when running without a configured SEASON_GUID."""
    global _warned_no_season_guid
    if not _warned_no_season_guid:
        logger.warning(
            "SEASON_GUID is not set; aggregating ALL seasons (may include the "
            "junk DO-NOT-USE season and prior seasons). Set SEASON_GUID to the "
            "current-season GUID in production."
        )
        _warned_no_season_guid = True


# ---------------------------------------------------------------------------
# Sample sizes and rankings
# ---------------------------------------------------------------------------
def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype(float)


def ip_to_innings(ip) -> float:
    """Turn baseball innings notation into true innings.

    The widget stores IP as 53.1 for 53 and one third, so the decimal part is
    outs (0, 1 or 2), not tenths. 53.1 becomes 53.33, which is what a minimum
    innings threshold should compare against.
    """
    value = float(ip)
    whole = int(value)
    outs = round((value - whole) * 10)
    return whole + outs / 3


def filter_min_sample(df: pd.DataFrame, col: str, minimum: float) -> pd.DataFrame:
    """Keep rows whose ``col`` meets the minimum sample size."""
    if df.empty or col not in df.columns:
        return df
    return df[_num(df[col]).fillna(0) >= minimum]







def ordinal(n: int) -> str:
    """1 becomes 1st, 2 becomes 2nd, 11 becomes 11th."""
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def rank_among(pool: pd.DataFrame, value, col: str, high_is_good: bool):
    """Rank ``value`` against ``pool[col]``, returning ``(rank, size)`` or None.

    Ties share a rank, since the rank is one plus the number of players
    strictly better. Blank values on either side give None, so a pitcher with
    no walks never gets a made-up K/BB rank.
    """
    if col not in pool.columns or pd.isna(value):
        return None
    vals = _num(pool[col]).dropna()
    if vals.empty:
        return None
    better = (vals > float(value)).sum() if high_is_good else (vals < float(value)).sum()
    return int(better) + 1, int(len(vals))
