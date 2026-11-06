"""Tests for the quadrant, threshold and insight features.

The unit tests use the Streamlit-free helpers in ``stats_utils``. The last two
run the real widget under AppTest with a stubbed ``requests.get``.
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from stats_utils import (  # noqa: E402
    HITTER_QUADRANTS,
    PITCHER_QUADRANTS,
    classify_hitters,
    classify_pitchers,
    filter_min_sample,
    hitter_actions,
    ip_to_innings,
    median_cut,
    pitcher_actions,
)

WIDGET_PY = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "widget.py"))
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
SEASON = "9843025b-3dd7-4b1b-8776-a6b53a3bdb7a"


def _hitters():
    return pd.DataFrame([
        {"PLAYER": "A", "PA": 100, "K%": 10.0, "BB%": 15.0, "SLG": 0.500, "OPS": 0.900},
        {"PLAYER": "B", "PA": 100, "K%": 30.0, "BB%": 15.0, "SLG": 0.300, "OPS": 0.600},
        {"PLAYER": "C", "PA": 100, "K%": 10.0, "BB%": 3.0, "SLG": 0.450, "OPS": 0.800},
        {"PLAYER": "D", "PA": 100, "K%": 30.0, "BB%": 3.0, "SLG": 0.250, "OPS": 0.500},
    ])


def test_ip_notation_converts_outs_not_tenths():
    assert ip_to_innings(53.0) == 53.0
    assert ip_to_innings(53.1) == pytest.approx(53 + 1 / 3)
    assert ip_to_innings(0.2) == pytest.approx(2 / 3)


def test_min_sample_filter_is_inclusive():
    df = _hitters()
    assert len(filter_min_sample(df, "PA", 100)) == 4
    assert len(filter_min_sample(df, "PA", 101)) == 0


def test_hitter_quadrants_cover_all_four_corners():
    df = classify_hitters(_hitters(), 20, 9)
    assert list(df["QUADRANT"]) == [
        HITTER_QUADRANTS[(True, True)],
        HITTER_QUADRANTS[(False, True)],
        HITTER_QUADRANTS[(True, False)],
        HITTER_QUADRANTS[(False, False)],
    ]
    notes = hitter_actions(df)
    assert [n for n, _, _ in notes] == ["A", "B", "C", "D"]
    assert all(a for _, _, a in notes)


def test_pitcher_quadrants_and_actions():
    df = pd.DataFrame([
        {"PLAYER": "P1", "K9": 11, "BB9": 2, "ERA": 5.0},
        {"PLAYER": "P2", "K9": 11, "BB9": 6, "ERA": 3.0},
        {"PLAYER": "P3", "K9": 5, "BB9": 2, "ERA": 3.0},
        {"PLAYER": "P4", "K9": 5, "BB9": 6, "ERA": 6.0},
    ])
    out = classify_pitchers(df, 8, 4)
    assert list(out["QUADRANT"]) == [
        PITCHER_QUADRANTS[(True, True)],
        PITCHER_QUADRANTS[(True, False)],
        PITCHER_QUADRANTS[(False, True)],
        PITCHER_QUADRANTS[(False, False)],
    ]
    notes = {n: a for n, _, a in pitcher_actions(out)}
    assert "unlucky" in notes["P1"]
    assert set(notes) == {"P1", "P2", "P3", "P4"}


def test_median_cut_handles_empty():
    assert median_cut(pd.Series([], dtype=float)) == 0.0
    assert median_cut(pd.Series([1.0, 3.0])) == 2.0


# ---- widget level -----------------------------------------------------------
class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _bat(pa, so, bb):
    return [{"stats": {SEASON: {"batting": {"overall": {
        "PA": pa, "AB": pa - 8, "H": 30, "2B": 5, "3B": 1, "HR": 4, "R": 15,
        "RBI": 20, "BB": bb, "SO": so, "HBP": 2,
        "RATES": {"AVG": 0.3, "OBP": 0.4, "SLG": 0.5, "OPS": 0.9}}}}}}]


PLAYERS = [
    {"guid": "h1", "name": "Batter, Bob", "bats": "R", "throwsHand": "R"},
    {"guid": "h2", "name": "Batter, Al", "bats": "L", "throwsHand": "R"},
    {"guid": "h3", "name": "Tiny, Tim", "bats": "R", "throwsHand": "R"},
    {"guid": "p1", "name": "Pitcher, Pat", "bats": "L", "throwsHand": "L"},
]
STATS = {
    "h1": _bat(100, 18, 8),
    "h2": _bat(90, 30, 3),
    "h3": _bat(5, 1, 0),
    "p1": [{"stats": {SEASON: {"pitching": {"overall": {
        "BF": 200, "H": 40, "R": 18, "ER": 15, "BB": 12, "SO": 55, "HR": 3,
        "PITCHES": 700, "OUTS_PITCHED": 160,
        "RATES": {"ERA": 2.7, "WHIP": 1.1, "K9": 9.3, "BB9": 2.0}}}}}}],
}


def _get(url, headers=None, params=None, timeout=None):
    if url.endswith("/teams"):
        return _Response([{"guid": "team-1", "name": "Lancaster Stormers"}])
    if url.endswith("/players"):
        return _Response(PLAYERS)
    if url.endswith("player-stats"):
        return _Response(STATS.get((params or {}).get("playerId"), []))
    return _Response([])


def _run(monkeypatch):
    monkeypatch.setenv("LEAGUE_GUID", "league-1")
    monkeypatch.setenv("SEASON_GUID", SEASON)
    import requests
    import streamlit as st

    monkeypatch.setattr(requests, "get", _get)
    st.cache_data.clear()
    return AppTest.from_file(WIDGET_PY, default_timeout=60).run()


def test_insights_render_and_the_threshold_only_shapes_the_chart(monkeypatch):
    at = _run(monkeypatch)
    assert not at.exception, at.exception
    bullets = [m.value for m in at.markdown if m.value.startswith("- ")]
    assert any(b.startswith("- Batter, Bob.") for b in bullets)
    assert any(b.startswith("- Pitcher, Pat.") for b in bullets)
    # Tiny, Tim has 5 PA, under the default minimum of 20, so no insight line
    # for him. The table still lists him.
    assert not any(b.startswith("- Tiny, Tim.") for b in bullets)
    assert "Tiny, Tim" in at.dataframe[0].value["PLAYER"].tolist()


def test_threshold_controls_do_not_crash_the_page(monkeypatch):
    at = _run(monkeypatch)
    at = at.radio[0].set_value("Custom").run()
    assert not at.exception, at.exception
    at = at.slider[0].set_value(250).run()
    assert not at.exception, at.exception
    assert any("No players meet the minimum" in i.value for i in at.info)
    assert len(at.dataframe) == 2


# ---- rank helpers and the player card ----------------------------------------
from stats_utils import ordinal, rank_among  # noqa: E402


def test_ordinal_handles_teens_and_endings():
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st", "111th"]


def test_rank_among_directions_ties_and_blanks():
    pool = pd.DataFrame({"OPS": [0.9, 0.8, 0.8, 0.5], "ERA": [2.0, 3.0, 4.0, None]})
    assert rank_among(pool, 0.9, "OPS", True) == (1, 4)
    assert rank_among(pool, 0.8, "OPS", True) == (2, 4)      # tie shares a rank
    assert rank_among(pool, 2.0, "ERA", False) == (1, 3)     # blank ERA is ignored
    assert rank_among(pool, float("nan"), "OPS", True) is None
    assert rank_among(pool, 1.0, "missing", True) is None


def test_actions_can_be_judged_against_a_reference_group():
    group = classify_hitters(_hitters(), 20, 9)
    one = group.iloc[[0]]
    assert hitter_actions(one, reference=group)[0][0] == "A"
    # Alone, A is its own median and counts as strong. Against the team it is
    # the best bat, so the note must not change for a strong player either way.
    assert hitter_actions(one)[0][2] == hitter_actions(one, reference=group)[0][2]


def _pick_row(at, section, row=0):
    key = f"{section}_view_table_Lancaster Stormers"
    at.session_state[key] = {"selection": {"rows": [row], "columns": [], "cells": []}}
    return at.run()


def test_clicking_a_hitter_row_opens_that_players_card(monkeypatch):
    at = _run(monkeypatch)
    at = _pick_row(at, "hitter", 0)
    assert not at.exception, at.exception
    # Rows open sorted by plate appearances, so row 0 is Batter, Bob with 100 PA.
    assert any(m.value == "### Batter, Bob" for m in at.markdown)
    labels = [m.label for m in at.metric]
    assert labels[:3] == ["PA", "AVG", "OBP"]
    assert any("of 3" in c.value or "of 2" in c.value for c in at.caption)


def test_a_card_for_a_small_sample_warns(monkeypatch):
    at = _run(monkeypatch)
    at = _pick_row(at, "hitter", 2)   # Tiny, Tim has only 5 PA
    assert not at.exception, at.exception
    assert any(m.value == "### Tiny, Tim" for m in at.markdown)
    assert any("Small sample" in w.value for w in at.warning)


def test_clicking_a_pitcher_row_opens_a_pitcher_card(monkeypatch):
    at = _run(monkeypatch)
    at = _pick_row(at, "pitcher", 0)
    assert not at.exception, at.exception
    assert any(m.value == "### Pitcher, Pat" for m in at.markdown)
    assert "ERA" in [m.label for m in at.metric]
