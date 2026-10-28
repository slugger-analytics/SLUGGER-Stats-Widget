"""Behavioural tests for how the widget loads a team, driven through Streamlit.

Same approach as ``test_upstream_resilience``: run the real ``widget.py`` under
``AppTest`` with a stubbed ``requests.get``. Nothing here touches iScore.

They pin the things a live audience would notice.

* A cold team loads its players concurrently instead of one at a time.
* A failed fetch inside a worker thread still fails the whole build, so a
  partial team table is never cached.
* ``?warm=1`` loads every team once and later renders come from the cache.
* A team with no roster renders an empty state instead of crashing.
* Tables open sorted by workload, so a one-out sample never leads the table.

Hitters render first and pitchers second on one page, and the name column is
called PLAYER in both.
"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

WIDGET_PY = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "widget.py")
)

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

SEASON = "9843025b-3dd7-4b1b-8776-a6b53a3bdb7a"

TEAMS = [
    {"guid": "team-1", "name": "Lancaster Stormers"},
    {"guid": "team-2", "name": "York Revolution"},
]


def _bat(pa, ops):
    return {"stats": {SEASON: {"batting": {"overall": {
        "PA": pa, "AB": pa, "H": 1, "2B": 0, "3B": 0, "HR": 0, "R": 0,
        "RBI": 0, "BB": 0, "SO": 0, "HBP": 0,
        "RATES": {"AVG": 0.3, "OBP": 0.3, "SLG": 0.3, "OPS": ops}}}}}}


def _pitch(outs, era):
    return {"stats": {SEASON: {"pitching": {"overall": {
        "BF": max(outs, 1), "H": 1, "R": 0, "ER": 0, "BB": 0, "SO": 0,
        "HR": 0, "PITCHES": 10, "OUTS_PITCHED": outs,
        "RATES": {"ERA": era, "WHIP": 1.0, "K9": 9.0, "BB9": 2.0}}}}}}


# Team 1 only. Each player is a hitter or a pitcher, never both, so the
# expected order of each table is unambiguous.
PLAYERS = [
    {"guid": "h-small", "name": "Small, Sam", "bats": "R", "throwsHand": "R"},
    {"guid": "h-mid", "name": "Mid, Max", "bats": "L", "throwsHand": "R"},
    {"guid": "h-star", "name": "Star, Stu", "bats": "R", "throwsHand": "R"},
    {"guid": "p-tiny", "name": "Tiny, Tim", "bats": "R", "throwsHand": "R"},
    {"guid": "p-ace", "name": "Ace, Al", "bats": "R", "throwsHand": "R"},
    {"guid": "p-ok", "name": "Okay, Oz", "bats": "R", "throwsHand": "L"},
]
STATS = {
    "h-small": [_bat(pa=5, ops=1.5)],
    "h-mid": [_bat(pa=60, ops=0.8)],
    "h-star": [_bat(pa=100, ops=1.1)],
    # 1 out (0.1 IP) and a 0.00 ERA would top an ERA-sorted table.
    "p-tiny": [_pitch(outs=1, era=0.0)],
    "p-ace": [_pitch(outs=200, era=2.1)],
    "p-ok": [_pitch(outs=160, era=3.5)],
}


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Feed:
    """A ``requests.get`` stand-in that records concurrency and can fail a call."""

    def __init__(self, latency=0.0, fail_player=None):
        self.latency = latency
        self.fail_player = fail_player
        self.fail_remaining = 1 if fail_player else 0
        self.stats_calls = []
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    def __call__(self, url, headers=None, params=None, timeout=None):
        if url.endswith("/leagues/league-1/teams"):
            return _Response(TEAMS)
        if url.endswith("/teams/team-1/players"):
            return _Response(PLAYERS)
        if url.endswith("/teams/team-2/players"):
            return _Response([])
        if url.endswith("player-stats"):
            guid = (params or {}).get("playerId")
            with self._lock:
                self.stats_calls.append(guid)
                self._in_flight += 1
                self.max_in_flight = max(self.max_in_flight, self._in_flight)
                should_fail = guid == self.fail_player and self.fail_remaining > 0
                if should_fail:
                    self.fail_remaining -= 1
            try:
                time.sleep(self.latency)
                if should_fail:
                    raise RuntimeError("simulated iScore blip")
                return _Response(STATS.get(guid, []))
            finally:
                with self._lock:
                    self._in_flight -= 1
        return _Response([])


def _app(monkeypatch, feed):
    monkeypatch.setenv("LEAGUE_GUID", "league-1")
    monkeypatch.setenv("SEASON_GUID", SEASON)
    import requests
    import streamlit as st

    monkeypatch.setattr(requests, "get", feed)
    st.cache_data.clear()
    return AppTest.from_file(WIDGET_PY, default_timeout=60)


def test_tables_open_sorted_by_workload(monkeypatch):
    at = _app(monkeypatch, _Feed()).run()
    assert not at.exception
    hitters = at.dataframe[0].value["PLAYER"].tolist()
    pitchers = at.dataframe[1].value["PLAYER"].tolist()
    assert hitters == ["Star, Stu", "Mid, Max", "Small, Sam"]
    assert pitchers == ["Ace, Al", "Okay, Oz", "Tiny, Tim"]


def test_player_stats_are_fetched_concurrently(monkeypatch):
    feed = _Feed(latency=0.3)
    start = time.monotonic()
    at = _app(monkeypatch, feed).run()
    elapsed = time.monotonic() - start

    assert not at.exception
    assert len(feed.stats_calls) == len(PLAYERS), "every player is fetched exactly once"
    assert feed.max_in_flight > 1, "fetches ran one at a time"
    sequential = 0.3 * len(PLAYERS)
    assert elapsed < sequential, \
        f"cold load took {elapsed:.2f}s, no better than sequential {sequential:.2f}s"


def test_a_failed_fetch_in_a_worker_thread_is_not_cached_as_a_short_roster(monkeypatch):
    feed = _Feed(fail_player="h-mid")
    at = _app(monkeypatch, feed).run()

    assert any("Couldn't reach" in w.value for w in at.warning), \
        f"expected a retryable warning, got {[w.value for w in at.warning]}"
    assert len(at.dataframe) == 0, "a partial team table must not be shown"

    # Same process, same cache, upstream healthy again.
    at = at.run()
    assert not at.exception
    hitters = at.dataframe[0].value["PLAYER"].tolist()
    assert "Mid, Max" in hitters, "the player who failed once never came back"


def test_a_team_with_no_roster_shows_an_empty_state(monkeypatch):
    at = _app(monkeypatch, _Feed()).run()
    at = at.selectbox[0].select("York Revolution").run()

    assert not at.exception, f"an empty roster crashed the page: {at.exception}"
    assert any("No pitching data" in i.value for i in at.info)
    assert any("No batting data" in i.value for i in at.info)


def test_warm_param_loads_every_team_once(monkeypatch):
    feed = _Feed()
    at = _app(monkeypatch, feed)
    at.query_params["warm"] = "1"
    at = at.run()

    assert not at.exception, f"warming crashed the script: {at.exception}"
    assert any("Warmed 2 teams" in s.value for s in at.success)
    # Team 1 was fetched while warming, and the normal render that follows must
    # have been served from the cache rather than fetching its players again.
    assert sorted(feed.stats_calls) == sorted(p["guid"] for p in PLAYERS)
