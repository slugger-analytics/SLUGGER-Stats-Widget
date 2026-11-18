"""Unit tests for the stat math (metrics.py) and the league report (league.py).

Neither module imports Streamlit, so these run with no app and no network.
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from league import build_league_report, frames_from_snapshot  # noqa: E402
from metrics import (  # noqa: E402
    STABILIZE,
    batting_row,
    bh_reject,
    line_from_counts,
    norm_sf,
    pitching_row,
    shrink,
    two_prop_z,
)


# ---- line_from_counts ----------------------------------------------------------
def test_slash_line_and_babip_from_counts():
    # 100 AB, 30 H (20 1B, 5 2B, 1 3B, 4 HR), 10 BB, 2 HBP, 1 SF, 20 SO
    c = {"AB": 100, "H": 30, "1B": 20, "2B": 5, "3B": 1, "HR": 4, "BB": 10,
         "HBP": 2, "SF": 1, "SO": 20, "PA": 113}
    line = line_from_counts(c)
    assert line["AVG"] == pytest.approx(0.300)
    assert line["OBP"] == pytest.approx(42 / 113)
    assert line["SLG"] == pytest.approx((20 + 10 + 3 + 16) / 100)
    assert line["BABIP"] == pytest.approx(26 / (100 - 20 - 4 + 1))


def test_woba_uses_unintentional_walks_only():
    base = {"AB": 100, "H": 20, "1B": 20, "BB": 10, "IBB": 0, "PA": 110}
    with_ibb = {**base, "IBB": 10}
    assert line_from_counts(with_ibb)["wOBA"] < line_from_counts(base)["wOBA"]


def test_empty_block_gives_nan_not_a_crash():
    line = line_from_counts({})
    assert math.isnan(line["AVG"]) and math.isnan(line["wOBA"])


# ---- rows ----------------------------------------------------------------------
def _season(pa=300, so=60, bb=30):
    o = {"PA": pa, "AB": pa - bb - 3, "H": 80, "1B": 50, "2B": 18, "3B": 2, "HR": 10,
         "BB": bb, "SO": so, "HBP": 3, "SF": 0, "R": 40, "RBI": 45, "GP": 70,
         "RATES": {"AVG": 0.3, "OBP": 0.4, "SLG": 0.5, "OPS": 0.9}}
    return {"batting": {"overall": o,
                        "byHand": {"vsL": {**o, "PA": 100, "AB": 90, "BB": 8, "HBP": 1},
                                   "vsR": {**o, "PA": 200, "AB": 190}}},
            "running": {"overall": {"SB": 7}}}


def test_batting_row_prefers_the_published_slash_line():
    row = batting_row("A", "R", _season())
    assert row["AVG"] == 0.3 and row["OPS"] == 0.9
    assert row["ISO"] == pytest.approx(0.2)
    assert row["BB%"] == pytest.approx(10.0) and row["K%"] == pytest.approx(20.0)
    assert row["SB"] == 7


def test_batting_row_skips_players_with_no_plate_appearances():
    assert batting_row("A", "R", {"batting": {"overall": {"PA": 0}}}) is None
    assert batting_row("A", "R", {}) is None


def test_split_columns_exist_and_unused_ones_are_dropped():
    row = batting_row("A", "R", _season())
    assert row["vsL_PA"] == 100 and "vsL_OPS" in row
    assert "RISP_OPS" not in row      # no situation block, so no made-up split


def test_pitching_row_ip_is_baseball_notation_and_role_is_derived():
    season = {"pitching": {"overall": {
        "BF": 200, "OUTS_PITCHED": 160, "SO": 55, "BB": 12, "HR": 3, "HBP": 2,
        "H": 40, "ER": 15, "R": 18, "GP": 10, "GS": 8, "PITCHES": 700, "STRIKES": 460,
        "RATES": {"ERA": 2.7, "WHIP": 1.1, "K9": 9.3, "BB9": 2.0}}}}
    row = pitching_row("P", "R", season)
    assert row["IP"] == pytest.approx(53.1) and row["INN"] == pytest.approx(160 / 3)
    assert row["ROLE"] == "SP"
    assert row["K-BB%"] == pytest.approx(100 * 43 / 200)
    assert row["STR%"] == pytest.approx(100 * 460 / 700)
    assert row["_FIPNUM"] == 13 * 3 + 3 * 14 - 2 * 55


def test_pitcher_with_no_walks_has_blank_k_per_bb():
    season = {"pitching": {"overall": {"BF": 30, "OUTS_PITCHED": 18, "SO": 9, "BB": 0}}}
    assert math.isnan(pitching_row("P", "L", season)["K/BB"])


# ---- shrinkage and tests -------------------------------------------------------
def test_shrinkage_is_halfway_at_the_stabilization_sample():
    k = STABILIZE["hit_K%"]
    # Observed 40% over exactly k trials, league 20%, so the estimate is 30%.
    assert shrink(0.4 * k, k, 0.2, k) == pytest.approx(0.30)
    # More data trusts the player more, no data returns the league rate.
    assert shrink(0.4 * 10 * k, 10 * k, 0.2, k) > 0.37
    assert shrink(0, 0, 0.2, k) == pytest.approx(0.2)


def test_two_proportion_z():
    diff, z, p = two_prop_z(50, 100, 50, 100)
    assert diff == 0 and z == 0 and p == pytest.approx(1.0)
    _, z, p = two_prop_z(60, 100, 40, 100)
    assert z > 2.5 and p < 0.02
    assert all(math.isnan(v) for v in two_prop_z(1, 0, 1, 10))


def test_normal_tail():
    assert norm_sf(0) == pytest.approx(0.5)
    assert norm_sf(1.96) == pytest.approx(0.025, abs=1e-3)


def test_benjamini_hochberg_controls_false_discoveries():
    # Ten tests, three of which look significant at .05 by chance. Only the
    # tiny one should survive a 10% false discovery rate.
    p = [0.0001, 0.03, 0.04, 0.045, 0.2, 0.3, 0.5, 0.6, 0.8, 0.9]
    keep = bh_reject(p, 0.10)
    assert keep[0] and sum(keep) == 1
    assert bh_reject([], 0.1) == []


# ---- the league report ---------------------------------------------------------
def _snapshot():
    rng = np.random.default_rng(7)
    teams = []
    for t in range(2):
        players = []
        for i in range(14):
            pa = int(rng.integers(120, 400))
            hit = _season(pa=pa, so=int(rng.integers(30, 90)), bb=int(rng.integers(10, 50)))
            loc = {"home": {**hit["batting"]["overall"], "PA": pa // 2},
                   "away": {**hit["batting"]["overall"], "PA": pa - pa // 2}}
            hit["batting"]["byLocation"] = loc
            hit["batting"]["bySituation"] = {
                "risp": {**hit["batting"]["overall"], "PA": 60},
                "basesEmpty": {**hit["batting"]["overall"], "PA": 200}}
            players.append({"guid": f"h{t}{i}", "name": f"H{t}{i}", "bats": "R",
                            "throws": "R", "stats": hit})
        for i in range(10):
            bf = int(rng.integers(100, 300))
            pit = {"pitching": {"overall": {
                "BF": bf, "AB": int(bf * 0.9), "OUTS_PITCHED": bf * 2 // 1, "SO": int(bf * 0.2), "BB": int(bf * 0.1),
                "HR": 4, "HBP": 2, "H": int(bf * 0.22), "ER": 20, "R": 24, "GP": 12, "GS": 0,
                "PITCHES": bf * 4, "STRIKES": bf * 2,
                "RATES": {"ERA": 4.0, "WHIP": 1.3, "K9": 8.0, "BB9": 4.0}}}}
            pit["pitching"]["byLocation"] = {
                "home": {**pit["pitching"]["overall"], "BF": bf // 2},
                "away": {**pit["pitching"]["overall"], "BF": bf - bf // 2}}
            players.append({"guid": f"p{t}{i}", "name": f"P{t}{i}", "bats": "L",
                            "throws": "R", "stats": pit})
        teams.append({"guid": f"t{t}", "name": f"Team {t}", "players": players})
    return {"taken_at": "2026-01-01T00:00:00", "season_guid": "s", "teams": teams}


def test_report_is_complete_json_safe_and_internally_consistent():
    report = build_league_report(_snapshot())
    json.dumps(report)                      # NaN would raise under allow_nan=False
    json.dumps(report, allow_nan=False)
    assert report["meta"]["hitters"] == 28 and report["meta"]["pitchers"] == 20
    assert {t["TEAM"] for t in report["teams"]} == {"Team 0", "Team 1"}
    for key in ("base", "percentiles", "reliability", "noise", "platoon", "risp",
                "counts", "predictive", "teams"):
        assert key in report
    base = report["base"]
    assert 0 < base["hit_K%"] < 1 and 0 < base["pit_BABIP"] < 1


def test_frames_drop_players_without_a_season_line():
    snap = _snapshot()
    snap["teams"][0]["players"].append(
        {"guid": "x", "name": "No Stats", "bats": "R", "throws": "R", "stats": None})
    hit, pit = frames_from_snapshot(snap)
    assert "No Stats" not in set(hit["PLAYER"]) | set(pit["PLAYER"])


def test_percentiles_run_from_zero_to_one_hundred_and_are_sorted():
    report = build_league_report(_snapshot())
    table = report["percentiles"]["hitters"]["wOBA"]
    assert len(table) == 101 and table == sorted(table)


def test_shipped_report_matches_the_widget_contract():
    """The committed report must carry every key the app and findings read."""
    path = os.path.join(os.path.dirname(__file__), "..", "data", "league_baselines.json")
    report = json.load(open(path))
    assert len(report["teams"]) == 10
    for key in ("hit_K%", "hit_BABIP", "pit_BABIP", "FIP_C", "ERA"):
        assert key in report["base"]
    for stat in ("wOBA", "K%", "BB%", "OPS"):
        assert stat in report["percentiles"]["hitters"]
    for stat in ("ERA", "FIP", "K-BB%"):
        assert stat in report["percentiles"]["pitchers"]
    # The tab's text reads these fields directly.
    assert {"hitters_R", "pitchers_R", "individual"} <= set(report["platoon"])
    assert {"K-BB%", "FIP", "ERA"} <= set(report["predictive"]["r"])
