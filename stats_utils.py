"""Pure, Streamlit-free helpers for the ALPB Player Stats widget.

Kept in a separate module (no ``import streamlit``) so the season-selection
logic can be unit-tested without booting the Streamlit app, whose module body
executes network + UI calls on import.
"""
from __future__ import annotations

import logging

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
