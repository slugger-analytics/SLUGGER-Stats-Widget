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

HITTERS = 0   # hitters are rendered first, pitchers second
PITCHERS = 1

HITTER_COLS = ["PLAYER", "BATS", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI",
               "BB", "SO", "HBP", "SB", "AVG", "OBP", "SLG", "OPS",
               "ISO", "BB%", "K%"]
PITCHER_COLS = ["PLAYER", "THROWS", "IP", "BF", "NP", "H", "R", "ER", "HR",
                "BB", "SO", "ERA", "WHIP", "K9", "BB9", "K/BB"]


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_get(fail_first_call=False):
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
    st.cache_data.clear()
    return at.run()


def test_an_upstream_blip_is_not_cached_as_an_empty_league(monkeypatch):
    getter = _fake_get(fail_first_call=True)
    at = _run(monkeypatch, getter)

    assert any("Couldn't reach" in w.value for w in at.warning), \
        f"expected a retryable warning, got {[w.value for w in at.warning]}"
    assert len(at.selectbox) == 0

    at = at.run()
    assert len(at.selectbox) == 1, "the widget stayed dead after upstream recovered"
    assert at.selectbox[0].value == "Lancaster Stormers"


def test_every_upstream_call_carries_a_timeout(monkeypatch):
    getter = _fake_get()
    _run(monkeypatch, getter)
    assert getter.state["calls"] > 0
    assert all(t is not None for t in getter.state["timeouts"])


def test_hitters_and_pitchers_share_one_page_without_tabs(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    assert not at.exception
    assert len(at.dataframe) == 2
    assert len(at.tabs) == 0
    assert [s.value for s in at.subheader] == ["Hitters", "Pitchers"]
    assert len(at.segmented_control) == 2, "each section needs its own view selector"


def test_default_views_are_the_traditional_lines(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    hitters, pitchers = at.dataframe[HITTERS].value, at.dataframe[PITCHERS].value
    assert list(hitters.columns)[:3] == ["PLAYER", "BATS", "PA"]
    assert "RBI" in hitters.columns and "OPS" not in hitters.columns
    assert "WHIP" in pitchers.columns and "K9" not in pitchers.columns


def test_slash_line_view_shows_only_the_slash_stats(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    at = at.segmented_control[HITTERS].set_value("Slash Line").run()
    cols = list(at.dataframe[HITTERS].value.columns)
    assert cols == ["PLAYER", "BATS", "PA", "AVG", "OBP", "SLG", "OPS"]


def test_all_view_shows_every_stat_in_the_standard_order(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    at = at.segmented_control[HITTERS].set_value("All").run()
    at = at.segmented_control[PITCHERS].set_value("All").run()
    assert list(at.dataframe[HITTERS].value.columns) == HITTER_COLS
    assert list(at.dataframe[PITCHERS].value.columns) == PITCHER_COLS


def test_custom_columns_always_come_out_in_the_standard_order(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    at = at.segmented_control[HITTERS].set_value("Custom").run()
    at = at.multiselect[0].set_value(["OPS", "HR", "PLAYER"]).run()
    assert list(at.dataframe[HITTERS].value.columns) == ["PLAYER", "HR", "OPS"]


def test_clearing_the_custom_picker_does_not_take_the_page_down(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    at = at.segmented_control[PITCHERS].set_value("Custom").run()
    assert not at.exception
    at = at.multiselect[0].set_value([]).run()

    assert not at.exception, f"clearing the picker crashed the script: {at.exception}"
    assert len(at.dataframe) == 2, "the hitter table stopped rendering"
    assert len(at.segmented_control) == 2, "the hitter view selector disappeared"
    assert any("at least one column" in c.value for c in at.caption)


def test_clearing_the_hitter_custom_picker_is_equally_survivable(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    at = at.segmented_control[HITTERS].set_value("Custom").run()
    at = at.multiselect[0].set_value([]).run()
    assert not at.exception
    assert len(at.dataframe) == 2


def test_header_caption_counts_both_sides(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    assert any("1 hitters and 1 pitchers" in c.value for c in at.caption)


def test_discipline_view_derives_walk_and_strikeout_rates(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    at = at.segmented_control[HITTERS].set_value("Discipline").run()
    row = at.dataframe[HITTERS].value.iloc[0]
    assert row["BB%"] == 8.0
    assert row["K%"] == 18.0


def test_power_view_derives_iso(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    at = at.segmented_control[HITTERS].set_value("Power").run()
    row = at.dataframe[HITTERS].value.iloc[0]
    assert row["ISO"] == pytest.approx(0.167)


def test_pitcher_rates_view_derives_k_per_bb(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    at = at.segmented_control[PITCHERS].set_value("Rates").run()
    row = at.dataframe[PITCHERS].value.iloc[0]
    assert row["K/BB"] == pytest.approx(4.58)


def test_innings_pitched_is_numeric_so_it_sorts_correctly(monkeypatch):
    at = _run(monkeypatch, _fake_get())
    pitchers = at.dataframe[PITCHERS].value
    # 160 outs is 53 and one third. A number sorts correctly, a string would not.
    assert pitchers.iloc[0]["IP"] == pytest.approx(53.1)
    assert str(pitchers["IP"].dtype).startswith("float")
