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
# Quadrants, thresholds and insights
# ---------------------------------------------------------------------------
# Keys are (x_is_good, y_is_good). Charts orient both axes so good is always
# right and up, so the key also says which corner a label belongs in.
HITTER_QUADRANTS = {
    (True, True): "Disciplined",
    (False, True): "Patient, High Strikeout",
    (True, False): "Aggressive Contact",
    (False, False): "Approach Concern",
}
PITCHER_QUADRANTS = {
    (True, True): "Dominant",
    (True, False): "Strikeout Arm, Shaky Command",
    (False, True): "Soft Contact Manager",
    (False, False): "Command Concern",
}


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


def median_cut(series: pd.Series, digits: int = 1) -> float:
    """Default quadrant cutoff, the median of the visible group."""
    vals = _num(series).dropna()
    if vals.empty:
        return 0.0
    return round(float(vals.median()), digits)


def classify_hitters(df: pd.DataFrame, k_cut: float, bb_cut: float) -> pd.DataFrame:
    """Label each hitter by K% (lower is better) and BB% (higher is better)."""
    out = df.copy()
    k_good = _num(out["K%"]) <= k_cut
    bb_good = _num(out["BB%"]) >= bb_cut
    out["QUADRANT"] = [
        HITTER_QUADRANTS[(bool(k), bool(b))] for k, b in zip(k_good, bb_good)
    ]
    return out


def classify_pitchers(df: pd.DataFrame, k9_cut: float, bb9_cut: float) -> pd.DataFrame:
    """Label each pitcher by K9 (higher is better) and BB9 (lower is better)."""
    out = df.copy()
    k_good = _num(out["K9"]) >= k9_cut
    bb_good = _num(out["BB9"]) <= bb9_cut
    out["QUADRANT"] = [
        PITCHER_QUADRANTS[(bool(k), bool(b))] for k, b in zip(k_good, bb_good)
    ]
    return out


def hitter_actions(df: pd.DataFrame, reference: pd.DataFrame | None = None) -> list[tuple[str, str, str]]:
    """Rule-based coaching notes as ``(player, quadrant, action)`` tuples.

    Expects the output of ``classify_hitters``. Production is judged against
    the median OPS and SLG of the same group, so the advice is relative to the
    team being viewed, not to an outside standard. Pass ``reference`` to
    judge a few players against a larger group, such as one player's card
    against the team's qualified hitters.
    """
    if df.empty:
        return []
    ref = df if reference is None else reference
    med_ops = _num(ref["OPS"]).median()
    med_slg = _num(ref["SLG"]).median()
    notes = []
    for _, r in df.iterrows():
        strong = r["OPS"] >= med_ops
        power = r["SLG"] >= med_slg
        q = r["QUADRANT"]
        if q == HITTER_QUADRANTS[(True, True)]:
            action = (
                "Table setter. Keep near the top of the order."
                if strong
                else "Sound approach with lagging results, likely bad luck. Hold course."
            )
        elif q == HITTER_QUADRANTS[(False, True)]:
            action = (
                "Power bat with strikeouts. Protect with contact hitters nearby."
                if power
                else "Draws walks but whiffs without damage. Work on pitches to drive."
            )
        elif q == HITTER_QUADRANTS[(True, False)]:
            action = (
                "Producing without walks. Expect some regression and monitor BABIP."
                if strong
                else "Few walks and weak production. Coach pitch selection."
            )
        else:
            action = "Strikes out often and rarely walks. Consider a reduced role or approach work."
        notes.append((r["PLAYER"], q, action))
    return notes


def pitcher_actions(df: pd.DataFrame, reference: pd.DataFrame | None = None) -> list[tuple[str, str, str]]:
    """Rule-based usage notes as ``(player, quadrant, action)`` tuples.

    Expects the output of ``classify_pitchers``. ERA is compared with the
    group median so results can be read against the peripheral quadrant. Pass
    ``reference`` to judge a few pitchers against a larger group.
    """
    if df.empty:
        return []
    ref = df if reference is None else reference
    med_era = _num(ref["ERA"]).median()
    notes = []
    for _, r in df.iterrows():
        good_results = r["ERA"] <= med_era
        q = r["QUADRANT"]
        if q == PITCHER_QUADRANTS[(True, True)]:
            action = (
                "Trusted arm. Suited to high-leverage innings."
                if good_results
                else "Elite peripherals with a poor ERA, likely unlucky. Keep the current role."
            )
        elif q == PITCHER_QUADRANTS[(True, False)]:
            action = "Strikeout stuff but too many walks. Best in short stints."
        elif q == PITCHER_QUADRANTS[(False, True)]:
            action = (
                "Pitches to contact effectively and relies on defense. Regression risk."
                if good_results
                else "Few strikeouts and poor results. Adjust the pitch mix."
            )
        else:
            action = "Walks batters without strikeouts. Reduce leverage until command improves."
        notes.append((r["PLAYER"], q, action))
    return notes


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
