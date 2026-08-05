"""Behavioural tests for the widget's failure handling, driven through Streamlit.

These run the real ``widget.py`` under ``streamlit.testing.v1.AppTest`` with a
stubbed ``requests.get``, so they assert what a visitor actually sees rather
than what the source text says. Nothing here touches iScore.

Two live defects motivated them:

* a one-second upstream blip was cached exactly like a success, pinning the
  widget on "Could not load teams." for the full 3600s TTL and replaying an
  error banner for an outage that had ended, and
* clearing every chip out of a "Select stats to display" multiselect replaced
  the page with a reportlab traceback, taking the other tab down with it.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

WIDGET_PY = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "widget.py")
)

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

SEASON = "9843025b-3dd7-4b1b-8776-a6b53a3bdb7a"

TEAMS = [{"guid": "team-1", "name": "Lancaster Stormers"}]
PLAYERS = [
    {"guid": "p-1", "name": "Batter, Bob", "bats": "R", "throwsHand": "R"},
    {"guid": "p-2", "name": "Pitcher, Pat", "bats": "L", "throwsHand": "L"},
]
STATS = {
    "p-1": [{"stats": {SEASON: {"batting": {"overall": {
        "PA": 100, "AB": 90, "H": 30, "2B": 5, "3B": 1, "HR": 4, "R": 15,
        "RBI": 20, "BB": 8, "SO": 18, "HBP": 2,
        "RATES": {"AVG": 0.333, "OBP": 0.4, "SLG": 0.5, "OPS": 0.9}}}}}}],
    "p-2": [{"stats": {SEASON: {"pitching": {"overall": {
        "BF": 200, "H": 40, "R": 18, "ER": 15, "BB": 12, "SO": 55, "HR": 3,
        "PITCHES": 700, "OUTS_PITCHED": 160,
        "RATES": {"ERA": 2.7, "WHIP": 1.1, "K9": 9.3, "BB9": 2.0}}}}}}],
}


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_get(fail_first_call=False):
    """Stand in for ``requests.get``; optionally fail its very first call."""
    state = {"calls": 0, "timeouts": []}

    def _get(url, headers=None, params=None, timeout=None):
        state["calls"] += 1
        state["timeouts"].append(timeout)
        if fail_first_call and state["calls"] == 1:
            raise RuntimeError("simulated iScore blip")
        if url.endswith("/teams"):
            return _Response(TEAMS)
        if url.endswith("/players"):
            return _Response(PLAYERS)
        if url.endswith("player-stats"):
            return _Response(STATS.get((params or {}).get("playerId"), []))
        return _Response([])

    _get.state = state
    return _get


def _run(monkeypatch, getter):
    monkeypatch.setenv("LEAGUE_GUID", "league-1")
    monkeypatch.setenv("SEASON_GUID", SEASON)
    at = AppTest.from_file(WIDGET_PY, default_timeout=60)
    import requests
    import streamlit as st

    monkeypatch.setattr(requests, "get", getter)
    # Each test gets its own cache: these assert what a COLD container does, and
    # @st.cache_data otherwise persists across AppTest instances in one process.
    st.cache_data.clear()
    return at.run()


def test_an_upstream_blip_is_not_cached_as_an_empty_league(monkeypatch):
    """The blip must not outlive itself.

    Streamlit's cache stores return values, not exceptions, so raising on an
    upstream failure is what makes the retry a real retry.
    """
    getter = _fake_get(fail_first_call=True)
    at = _run(monkeypatch, getter)

    assert any("Couldn't reach" in w.value for w in at.warning), \
        f"expected a retryable warning, got {[w.value for w in at.warning]}"
    assert len(at.selectbox) == 0

    # Same process, same cache, upstream healthy again.
    at = at.run()
    assert len(at.selectbox) == 1, "the widget stayed dead after upstream recovered"
    assert at.selectbox[0].value == "Lancaster Stormers"


def test_every_upstream_call_carries_a_timeout(monkeypatch):
    getter = _fake_get()
    _run(monkeypatch, getter)
    assert getter.state["calls"] > 0
    assert all(t is not None for t in getter.state["timeouts"]), \
        "a hung connection would hold the script run open forever"


def test_clearing_the_column_picker_does_not_take_the_page_down(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    assert not at.exception
    tabs_before = len(at.dataframe)
    assert tabs_before == 2, "expected a pitcher table and a hitter table"

    # One click per chip, no confirmation — this is reachable by accident.
    at = at.multiselect[0].set_value([]).run()

    assert not at.exception, f"clearing the picker crashed the script: {at.exception}"
    # The OTHER tab must survive: the script used to abort here, before tab2 was
    # ever built, so a user hiding a pitching column lost the hitting view too.
    assert len(at.dataframe) == 2, "the hitter table stopped rendering"
    assert len(at.multiselect) == 2, "the hitter tab's own picker disappeared"
    assert any("at least one column" in c.value for c in at.caption), \
        "the export needs to say why it is unavailable"


def test_clearing_the_hitter_picker_is_equally_survivable(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    at = at.multiselect[1].set_value([]).run()
    assert not at.exception
    assert len(at.multiselect) == 2
