"""The player card and the player comparison, driven through the real widget.

``requests.get`` is replaced by a stub that answers both iScore and the
SLUGGER Trackman API, so nothing here touches the network.
"""
import os
import re
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from stats_utils import filter_min_sample, ip_to_innings, ordinal, rank_among  # noqa: E402
from test_advanced import sample, pitch, OUT  # noqa: E402

WIDGET_PY = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "widget.py"))
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
SEASON = "9843025b-3dd7-4b1b-8776-a6b53a3bdb7a"


# ---- helpers kept from the old quadrant tests -------------------------------
def test_ip_notation_converts_outs_not_tenths():
    assert ip_to_innings(53.0) == 53.0
    assert ip_to_innings(53.1) == pytest.approx(53 + 1 / 3)
    assert ip_to_innings(0.2) == pytest.approx(2 / 3)


def test_min_sample_filter_is_inclusive():
    df = pd.DataFrame({"PA": [100, 100]})
    assert len(filter_min_sample(df, "PA", 100)) == 2
    assert len(filter_min_sample(df, "PA", 101)) == 0


def test_ordinal_handles_teens_and_endings():
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st", "111th"]


def test_rank_among_directions_ties_and_blanks():
    pool = pd.DataFrame({"OPS": [0.9, 0.8, 0.8, 0.5], "ERA": [2.0, 3.0, 4.0, None]})
    assert rank_among(pool, 0.9, "OPS", True) == (1, 4)
    assert rank_among(pool, 0.8, "OPS", True) == (2, 4)
    assert rank_among(pool, 2.0, "ERA", False) == (1, 3)
    assert rank_among(pool, float("nan"), "OPS", True) is None


# ---- stubbed feeds -----------------------------------------------------------
class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _bat(pa, so, bb, ops=0.9):
    return [{"stats": {SEASON: {"batting": {"overall": {
        "PA": pa, "AB": pa - 8, "H": 30, "2B": 5, "3B": 1, "HR": 4, "R": 15,
        "RBI": 20, "BB": bb, "SO": so, "HBP": 2,
        "RATES": {"AVG": 0.3, "OBP": 0.4, "SLG": 0.5, "OPS": ops}}}}}}]


def _pitch_line(outs, era):
    return [{"stats": {SEASON: {"pitching": {"overall": {
        "BF": 200, "H": 40, "R": 18, "ER": 15, "BB": 12, "SO": 55, "HR": 3,
        "PITCHES": 700, "OUTS_PITCHED": outs,
        "RATES": {"ERA": era, "WHIP": 1.1, "K9": 9.3, "BB9": 2.0}}}}}}]


TEAMS = [{"guid": "team-1", "name": "Lancaster Stormers"},
         {"guid": "team-2", "name": "York Revolution"}]
ROSTERS = {
    "team-1": [
        {"guid": "h1", "name": "Batter, Bob", "bats": "R", "throwsHand": "R"},
        {"guid": "h2", "name": "Batter, Al", "bats": "L", "throwsHand": "R"},
        {"guid": "h3", "name": "Tiny, Tim", "bats": "R", "throwsHand": "R"},
        {"guid": "p1", "name": "Pitcher, Pat", "bats": "L", "throwsHand": "L"},
    ],
    "team-2": [
        {"guid": "h9", "name": "Slugger, Sal", "bats": "L", "throwsHand": "R"},
        {"guid": "p9", "name": "Hurler, Hank", "bats": "R", "throwsHand": "R"},
    ],
}
STATS = {
    "h1": _bat(100, 18, 8, ops=0.95),
    "h2": _bat(90, 30, 3, ops=0.70),
    "h3": _bat(5, 1, 0),
    "h9": _bat(120, 35, 15, ops=0.88),
    "p1": _pitch_line(160, 2.7),
    "p9": _pitch_line(150, 4.1),
}

TRACKMAN_PLAYERS = [
    {"player_id": "tm-bob", "player_name": "Batter, Bob", "team_name": "Lancaster Stormers"},
    {"player_id": "tm-sal", "player_name": "Slugger, Sal", "team_name": "York Revolution"},
    {"player_id": "tm-pat", "player_name": "Pitcher, Pat", "team_name": "Lancaster Stormers"},
    {"player_id": "tm-hank", "player_name": "Hurler, Hank", "team_name": "York Revolution"},
]


def _records(df):
    return df.astype(object).where(df.notna(), None).to_dict("records")


# Bob chases 1 of 4 outside pitches (25%). Sal chases all 4 (100%).
BOB = _records(sample())
SAL = _records(pd.DataFrame([pitch("StrikeSwinging", OUT)] * 4 + [pitch("InPlay", ev=104.0, la=15.0)]))
PITCHES = {("batter_id", "tm-bob"): BOB, ("batter_id", "tm-sal"): SAL,
           ("pitcher_id", "tm-pat"): BOB, ("pitcher_id", "tm-hank"): SAL}


class Feed:
    def __init__(self):
        self.trackman_calls = []

    def __call__(self, url, headers=None, params=None, timeout=None):
        params = params or {}
        if "ALPBAPI" in url:
            assert headers and headers.get("x-api-key") == "test-key"
            self.trackman_calls.append((url.rsplit("/", 1)[-1], dict(params)))
            if url.endswith("/players"):
                return _Response({"data": TRACKMAN_PLAYERS if params.get("page") == 1 else []})
            if url.endswith("/pitches"):
                assert params["date_range_start"] == "2026-01-01"
                for role in ("batter_id", "pitcher_id"):
                    if role in params:
                        rows = PITCHES.get((role, params[role]), [])
                        return _Response({"data": rows if params.get("page") == 1 else []})
            return _Response({"data": []})
        if url.endswith("/leagues/league-1/teams"):
            return _Response(TEAMS)
        for guid, roster in ROSTERS.items():
            if url.endswith(f"/teams/{guid}/players"):
                return _Response(roster)
        if url.endswith("player-stats"):
            return _Response(STATS.get(params.get("playerId"), []))
        return _Response([])


def _run(monkeypatch, key="test-key", feed=None):
    monkeypatch.setenv("LEAGUE_GUID", "league-1")
    monkeypatch.setenv("SEASON_GUID", SEASON)
    monkeypatch.setenv("ALPB_API_KEY", key)
    monkeypatch.setenv("TRACKMAN_START_DATE", "2026-01-01")
    monkeypatch.setenv("TRACKMAN_END_DATE", "2026-12-31")
    import requests
    import streamlit as st

    monkeypatch.setattr(requests, "get", feed or Feed())
    st.cache_data.clear()
    return AppTest.from_file(WIDGET_PY, default_timeout=60).run()


def _pick_row(at, section, row=0):
    key = f"{section}_view_table_Lancaster Stormers"
    at.session_state[key] = {"selection": {"rows": [row], "columns": [], "cells": []}}
    return at.run()


def _metric(at, label):
    return [m.value for m in at.metric if m.label == label]


# ---- player card -------------------------------------------------------------
def test_page_loads_only_the_default_cards_trackman(monkeypatch):
    """Without any clicks, Trackman is asked only for the player list and the
    two default cards (top hitter, top pitcher). No comparison loads."""
    feed = Feed()
    at = _run(monkeypatch, feed=feed)
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == ["Hitters", "Pitchers", "Team"]
    asked = {(p.get("batter_id"), p.get("pitcher_id")) for name, p in feed.trackman_calls
             if name == "pitches"}
    assert asked == {("tm-bob", None), (None, "tm-pat")}
    assert not any(str(s.key).startswith("cmp_team") for s in at.selectbox)


def test_right_column_shows_top_player_without_a_click(monkeypatch):
    at = _run(monkeypatch)
    assert not at.exception, at.exception
    assert any(m.value == "### Batter, Bob" for m in at.markdown)
    assert any(m.value == "### Pitcher, Pat" for m in at.markdown)
    assert any("Select a row in the table to switch" in c.value for c in at.caption)


def test_quadrant_section_is_gone(monkeypatch):
    at = _run(monkeypatch)
    assert not at.exception, at.exception
    assert not any("Quadrant" in e.label for e in at.expander)
    assert not any("Actionable" in m.value for m in at.markdown)


def test_hitter_card_shows_ranks_and_trackman_discipline(monkeypatch):
    at = _pick_row(_run(monkeypatch), "hitter", 0)
    assert not at.exception, at.exception
    assert any(m.value == "### Batter, Bob" for m in at.markdown)
    assert [m.label for m in at.metric][:3] == ["PA", "AVG", "OBP"]
    # The pitcher tab's card also shows Chase%, so the hitter card is the first.
    assert _metric(at, "Chase%")[0] == "25.0"
    assert _metric(at, "Z-Swing%")[0] == "75.0"
    assert _metric(at, "Avg EV")[0] == "100.0"


def test_small_sample_card_warns(monkeypatch):
    at = _pick_row(_run(monkeypatch), "hitter", 2)   # Tiny, Tim has only 5 PA
    assert not at.exception, at.exception
    assert any("Small sample" in w.value for w in at.warning)
    # Tim has no Trackman record, which is explained rather than left blank.
    assert any("No Trackman match" in c.value for c in at.caption)


def test_card_without_api_key_still_renders(monkeypatch):
    at = _pick_row(_run(monkeypatch, key=""), "hitter", 0)
    assert not at.exception, at.exception
    assert any("ALPB_API_KEY" in c.value for c in at.caption)
    assert _metric(at, "OPS")


def test_pitcher_card_shows_csw(monkeypatch):
    at = _pick_row(_run(monkeypatch), "pitcher", 0)
    assert not at.exception, at.exception
    assert _metric(at, "CSW%")[0] == "37.5"   # key tile, repeated in the breakdown


# ---- compare -----------------------------------------------------------------
def _open_compare(at, kind="hitter"):
    at.toggle(key=f"cmp_on_{kind}").set_value(True)
    return at.run()


def _h2h(at):
    """The head-to-head block as ``{"names": [...], "rows": {stat: row}}``.

    Each row is ``(value_a, value_b, winner, bar_a, bar_b)`` where winner is
    0, 1 or None and the bars are width percents.
    """
    bodies = [e.proto.body for e in at.get("html") if 'class="h2h"' in e.proto.body]
    if not bodies:
        return None
    body = bodies[0]
    head = re.search(r'h2h-head">\s*<div></div><div[^>]*>(.*?)</div>\s*<div></div><div>(.*?)</div>', body)
    rows = {}
    pattern = (r'h2h-val l( win)?">(.*?)</div>.*?width:([\d.]+)%.*?'
               r'h2h-stat"[^>]*>([^<]+).*?width:([\d.]+)%.*?h2h-val( win)?">(.*?)</div>')
    for m in re.finditer(pattern, body, flags=re.S):
        win_a, a, bar_a, stat, bar_b, win_b, b = m.groups()
        winner = 0 if win_a else (1 if win_b else None)
        rows[stat.strip()] = (a, b, winner, float(bar_a), float(bar_b))
    return {"names": [head.group(1), head.group(2)], "rows": rows}


def test_compare_defaults_to_two_teams_and_uses_normal_stats(monkeypatch):
    feed = Feed()
    at = _open_compare(_run(monkeypatch, feed=feed))
    assert not at.exception, at.exception
    h2h = _h2h(at)
    assert h2h["names"] == ["Batter, Bob", "Slugger, Sal"]
    a, b, winner, bar_a, bar_b = h2h["rows"]["OPS"]
    assert (a, b, winner) == ("0.950", "0.880", 0)
    assert bar_a == 100.0 and bar_b == pytest.approx(92.6)
    assert "Chase%" not in h2h["rows"]
    # The comparison itself never asks Trackman about Sal.
    assert not any(p.get("batter_id") == "tm-sal" for _, p in feed.trackman_calls)


def test_lower_is_better_rates_pick_the_lower_value(monkeypatch):
    h2h = _h2h(_open_compare(_run(monkeypatch)))
    # Bob strikes out 18 times in 100 PA, Sal 35 in 120, so Bob wins K%
    # and gets the full bar even though his number is smaller.
    a, b, winner, bar_a, bar_b = h2h["rows"]["K%"]
    assert winner == 0
    assert bar_a == 100.0 and bar_b < bar_a


def test_totals_are_shown_but_never_scored(monkeypatch):
    h2h = _h2h(_open_compare(_run(monkeypatch)))
    for stat in ("PA", "H", "HR", "SO"):
        assert h2h["rows"][stat][2] is None


def test_compare_starts_from_the_selected_row(monkeypatch):
    at = _run(monkeypatch)
    at.toggle(key="cmp_on_hitter").set_value(True)
    at = _pick_row(at, "hitter", 1)   # Batter, Al
    assert not at.exception, at.exception
    assert _h2h(at)["names"] == ["Batter, Al", "Slugger, Sal"]


def test_compare_can_pick_another_player(monkeypatch):
    at = _open_compare(_run(monkeypatch))
    at.selectbox(key="cmp_player_0_hitter_Lancaster Stormers_Batter, Bob").set_value("Batter, Al")
    at = at.run()
    assert not at.exception, at.exception
    assert _h2h(at)["names"] == ["Batter, Al", "Slugger, Sal"]


def test_same_player_twice_asks_for_two(monkeypatch):
    at = _open_compare(_run(monkeypatch))
    at.selectbox(key="cmp_team_hitter_1").set_value("Lancaster Stormers")
    at = at.run()
    assert not at.exception, at.exception
    assert any("Pick two different players" in i.value for i in at.info)
    assert _h2h(at) is None


def test_compare_pitchers(monkeypatch):
    at = _open_compare(_run(monkeypatch), kind="pitcher")
    assert not at.exception, at.exception
    h2h = _h2h(at)
    assert h2h["names"] == ["Pitcher, Pat", "Hurler, Hank"]
    assert h2h["rows"]["ERA"][:3] == ("2.70", "4.10", 0)   # lower ERA wins
    assert h2h["rows"]["ERA"][3:] == (100.0, pytest.approx(65.9))   # 2.70 / 4.10
    # 160 outs is 53.1 IP, 150 is 50.0. Bars use true innings, 50 / 53.33.
    assert h2h["rows"]["IP"][4] == pytest.approx(93.8)


# ---- Trackman columns inside the views ---------------------------------------
class BadTrackmanFeed(Feed):
    """iScore works, but Trackman answers with something that isn't rows."""

    def __call__(self, url, headers=None, params=None, timeout=None):
        if "ALPBAPI" in url:
            return _Response(["not", "rows"])
        return super().__call__(url, headers=headers, params=params, timeout=timeout)


def test_bad_trackman_reply_leaves_columns_blank_not_a_crash(monkeypatch):
    at = _run(monkeypatch, feed=BadTrackmanFeed())
    at = _view(at, "hitter", "Power")
    assert not at.exception, at.exception
    table = _table(at, "hitter")
    assert table["Barrel%"].isna().all()
    assert table["ISO"].notna().all()          # iScore columns still fine
    assert any("blank" in i.value for i in at.info)


class SplitIdFeed(Feed):
    """Bob has a second Trackman id with no team, holding 4 more chases."""

    def __call__(self, url, headers=None, params=None, timeout=None):
        params = params or {}
        if "ALPBAPI" in url and url.endswith("/players") and params.get("page") == 1:
            extra = {"player_id": "tm-bob-2", "player_name": "Batter, Bob", "team_name": None}
            return _Response({"data": TRACKMAN_PLAYERS + [extra]})
        if "ALPBAPI" in url and params.get("batter_id") == "tm-bob-2":
            rows = _records(pd.DataFrame([pitch("StrikeSwinging", OUT)] * 4))
            return _Response({"data": rows if params.get("page") == 1 else []})
        return super().__call__(url, headers=headers, params=params, timeout=timeout)


def test_player_split_across_two_ids_is_combined(monkeypatch):
    at = _view(_run(monkeypatch, feed=SplitIdFeed()), "hitter", "Discipline")
    assert not at.exception, at.exception
    table = _table(at, "hitter").set_index("PLAYER")
    # 8 pitches on his first id with 1 of 4 chased, plus 4 chases on the second.
    assert table.loc["Batter, Bob", "Chase%"] == 62.5     # 5 of 8


def test_real_env_key_is_ignored_by_tests():
    import os
    assert os.environ.get("ALPB_API_KEY") == ""

def _view(at, kind, name):
    at.segmented_control(key=f"{kind}_view").set_value(name)
    return at.run()


def _table(at, kind):
    first = "Batter, Bob" if kind == "hitter" else "Pitcher, Pat"
    return next(d.value for d in at.dataframe if "PLAYER" in d.value.columns
                and d.value["PLAYER"].iloc[0] == first)


def test_power_view_has_barrel_and_ev90(monkeypatch):
    at = _view(_run(monkeypatch), "hitter", "Power")
    assert not at.exception, at.exception
    table = _table(at, "hitter").set_index("PLAYER")
    assert {"ISO", "Barrel%", "EV90", "Hard-Hit%"} <= set(table.columns)
    assert table.loc["Batter, Bob", "Barrel%"] == 0.0     # 100 mph at 20 degrees is just under the window
    assert table.loc["Batter, Bob", "EV90"] == 100.0
    assert pd.isna(table.loc["Tiny, Tim", "Barrel%"])      # no Trackman match, left blank


def test_discipline_view_has_chase(monkeypatch):
    at = _view(_run(monkeypatch), "hitter", "Discipline")
    assert not at.exception, at.exception
    table = _table(at, "hitter").set_index("PLAYER")
    assert table.loc["Batter, Bob", "Chase%"] == 25.0
    assert table.loc["Batter, Bob", "Z-Swing%"] == 75.0


def test_pitcher_rates_view_has_csw(monkeypatch):
    at = _view(_run(monkeypatch), "pitcher", "Rates")
    assert not at.exception, at.exception
    table = _table(at, "pitcher").set_index("PLAYER")
    assert table.loc["Pitcher, Pat", "CSW%"] == 37.5


def test_trackman_columns_blank_without_key(monkeypatch):
    at = _view(_run(monkeypatch, key=""), "hitter", "Discipline")
    assert not at.exception, at.exception
    assert any("ALPB_API_KEY" in i.value for i in at.info)
    assert _table(at, "hitter")["Chase%"].isna().all()
