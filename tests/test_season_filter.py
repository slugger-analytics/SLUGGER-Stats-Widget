"""Unit tests for the pure season-selection helper.

These import ``stats_utils`` (Streamlit-free) rather than ``widget``, whose
module body executes network + Streamlit calls on import.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from stats_utils import select_season_rows  # noqa: E402

# Current season shipped in the Fargate task definition (env SEASON_GUID).
CURRENT = "9843025b-3dd7-4b1b-8776-a6b53a3bdb7a"  # "ALPB- 2026"
# The junk season the ALPBAPI Lambda filters out — but this widget hits iScore
# directly, so it reaches us here.
JUNK = "46808fcc-0000-0000-0000-000000000000"  # "DO-NOT-USE-2026"
PRIOR = "11111111-2222-3333-4444-555555555555"  # a prior season


def _stats(pa_current=10, pa_junk=5, pa_prior=7):
    """A stats-by-season dict shaped like iScore's ``stats`` payload."""
    return {
        CURRENT: {"batting": {"overall": {"PA": pa_current}}},
        JUNK: {"batting": {"overall": {"PA": pa_junk}}},
        PRIOR: {"batting": {"overall": {"PA": pa_prior}}},
    }


def test_selects_only_the_configured_current_season():
    """(a) current + junk + prior seasons -> only the current one is kept."""
    rows = select_season_rows(_stats(), CURRENT)
    assert [guid for guid, _ in rows] == [CURRENT]
    # The junk/prior duplicate rows are gone.
    assert JUNK not in {guid for guid, _ in rows}
    assert PRIOR not in {guid for guid, _ in rows}


def test_none_season_guid_keeps_all_seasons_legacy():
    """(b) SEASON_GUID None -> legacy behavior: every season is returned."""
    rows = select_season_rows(_stats(), None)
    assert {guid for guid, _ in rows} == {CURRENT, JUNK, PRIOR}


def test_empty_season_guid_keeps_all_seasons_legacy():
    """(b) SEASON_GUID "" -> legacy behavior: every season is returned."""
    rows = select_season_rows(_stats(), "")
    assert {guid for guid, _ in rows} == {CURRENT, JUNK, PRIOR}


def test_current_season_absent_returns_empty():
    """(c) configured season not present -> no rows (player has no current line)."""
    stats = {
        JUNK: {"batting": {"overall": {"PA": 5}}},
        PRIOR: {"batting": {"overall": {"PA": 7}}},
    }
    assert select_season_rows(stats, CURRENT) == []


def test_empty_stats_returns_empty():
    """A player with no stats at all yields nothing, either mode."""
    assert select_season_rows({}, CURRENT) == []
    assert select_season_rows({}, None) == []


def test_selector_does_not_gate_on_pa_gating_unchanged():
    """(d) PA>0 gating is NOT the selector's job and stays unchanged downstream.

    The selector returns the current season even when PA==0 and passes the
    season payload through untouched, so the caller's existing ``PA > 0`` gate
    still sees the real value and behaves exactly as before.
    """
    stats = {CURRENT: {"batting": {"overall": {"PA": 0}}}}
    rows = select_season_rows(stats, CURRENT)
    assert [guid for guid, _ in rows] == [CURRENT]
    # Data passed through unchanged -> downstream PA>0 gate is unaffected.
    assert rows[0][1]["batting"]["overall"]["PA"] == 0
