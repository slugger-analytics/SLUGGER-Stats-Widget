"""Unit tests for the Trackman advanced stats in ``advanced.py``."""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import advanced as adv  # noqa: E402

IN = (0.0, 2.5)     # middle of the zone
OUT = (1.5, 2.5)    # well off the plate


def pitch(call, loc=IN, balls=1, strikes=1, ev=None, la=None, hit="Undefined",
          ptype="Fastball", velo=90.0):
    side, height = loc if loc else (None, None)
    return {"pitch_call": call, "plate_loc_side": side, "plate_loc_height": height,
            "balls": balls, "strikes": strikes, "exit_speed": ev, "angle": la,
            "tagged_hit_type": hit, "auto_hit_type": None,
            "tagged_pitch_type": ptype, "auto_pitch_type": None, "rel_speed": velo}


def sample():
    """4 in the zone (3 swings), 4 outside (1 swing). Numbers are easy to check."""
    return pd.DataFrame([
        pitch("InPlay", IN, ev=100.0, la=20.0, hit="LineDrive"),
        pitch("FoulBallNotFieldable", IN),
        pitch("StrikeSwinging", IN),
        pitch("StrikeCalled", IN, balls=0, strikes=0),
        pitch("StrikeSwinging", OUT, ptype="Slider", velo=82.0),
        pitch("BallCalled", OUT, ptype="Slider", velo=82.0),
        pitch("BallinDirt", OUT, ptype="Slider", velo=82.0),
        pitch("BallCalled", OUT, balls=0, strikes=0),
    ])


def test_zone_swing_and_contact_rates():
    s = adv.hitter_advanced(sample())
    assert s["Pitches"] == 8
    assert s["Zone%"] == 50.0
    assert s["Z-Swing%"] == 75.0
    assert s["Chase%"] == 25.0
    assert s["Swing%"] == 50.0
    assert s["Whiff%"] == 50.0
    assert s["Contact%"] == 50.0
    assert s["Z-Contact%"] == pytest.approx(66.7)
    assert s["O-Contact%"] == 0.0
    assert s["SwStr%"] == 25.0
    assert s["F-Swing%"] == 0.0


def test_batted_ball_uses_only_balls_in_play():
    s = adv.hitter_advanced(sample())
    assert s["BBE"] == 1
    assert s["Avg EV"] == 100.0
    assert s["Hard-Hit%"] == 100.0
    assert s["Sweet-Spot%"] == 100.0
    assert s["LD%"] == 100.0


def test_barrel_window_widens_with_exit_velocity():
    ev = pd.Series([97.9, 98.0, 98.0, 105.0, 105.0, 116.0, 120.0, 120.0])
    la = pd.Series([28.0, 28.0, 31.0, 20.0, 18.0, 9.0, 50.0, 51.0])
    assert adv.is_barrel(ev, la).tolist() == [False, True, False, True, False, True, True, False]


def test_barrel_rate_and_ev90():
    rows = [pitch("InPlay", ev=104.0, la=25.0, hit="LineDrive"),
            pitch("InPlay", ev=80.0, la=-5.0, hit="GroundBall")]
    s = adv.hitter_advanced(pd.DataFrame(rows))
    assert s["Barrel%"] == 50.0
    assert s["EV90"] == pytest.approx(101.6)


def test_untracked_location_counts_for_swings_but_not_zone():
    df = pd.concat([sample(), pd.DataFrame([pitch("StrikeSwinging", loc=None)])])
    s = adv.hitter_advanced(df)
    assert s["Pitches"] == 9
    assert s["Zone%"] == 50.0          # unchanged, still 8 located pitches
    assert s["Whiff%"] == 60.0         # 3 whiffs of 5 swings


def test_undefined_and_intentional_calls_are_dropped():
    df = pd.concat([sample(), pd.DataFrame([pitch("Undefined"), pitch("BallIntentional", OUT)])])
    assert adv.hitter_advanced(df)["Pitches"] == 8


def test_zone_edge_counts_as_a_strike():
    edge = pd.DataFrame([pitch("StrikeCalled", (adv.ZONE_HALF_WIDTH, adv.ZONE_TOP))])
    assert adv.hitter_advanced(edge)["Zone%"] == 100.0


def test_empty_or_missing_data_gives_empty_summary():
    assert adv.hitter_advanced(pd.DataFrame()) == {}
    assert adv.pitcher_advanced(None) == {}
    assert adv.arsenal(pd.DataFrame()).empty


def test_pitcher_csw_first_strike_and_velocity():
    s = adv.pitcher_advanced(sample())
    assert s["CSW%"] == 37.5           # 1 called + 2 whiffs of 8
    assert s["F-Strike%"] == 50.0      # two 0-0 pitches, one a called strike
    assert s["FB Velo"] == 90.0        # sliders are not fastballs
    assert s["Max Velo"] == 90.0


def test_arsenal_is_sorted_by_usage():
    mix = adv.arsenal(sample())
    assert mix["Pitch"].tolist() == ["Fastball", "Slider"]
    assert mix["#"].tolist() == [5, 3]
    assert mix.loc[1, "Whiff%"] == 100.0


def test_better_respects_direction_per_role():
    assert adv.better("Chase%", "hitter", 20.0, 30.0) == 0
    assert adv.better("Chase%", "pitcher", 20.0, 30.0) == 1
    assert adv.better("Swing%", "hitter", 20.0, 30.0) is None
    assert adv.better("Whiff%", "hitter", 25.0, 25.0) is None
    assert adv.better("Whiff%", "hitter", float("nan"), 25.0) is None


PLAYERS = pd.DataFrame([
    {"player_id": "t1", "player_name": "Batter, Bob", "team_name": "Lancaster Stormers"},
    {"player_id": "t4", "player_name": "Muñoz Jr., José", "team_name": "York Revolution"},
    # One player, one id per team plus one with no team, like the real feed.
    {"player_id": "d1", "player_name": "Dunston, Shawon", "team_name": "High Point Rockers"},
    {"player_id": "d2", "player_name": "Dunston, Shawon", "team_name": "York Revolution"},
    {"player_id": "d3", "player_name": "Dunston, Shawon", "team_name": None},
    {"player_id": "s1", "player_name": "Smith, Jaylen", "team_name": None},
    {"player_id": "s2", "player_name": "Smith, Julian", "team_name": "Gastonia Ghost Peppers"},
    {"player_id": "n1", "player_name": "Nelson, James", "team_name": "York Revolution"},
    {"player_id": "n2", "player_name": "Nelson, Jasper", "team_name": None},
])


def test_match_handles_both_name_orders_accents_and_suffixes():
    assert adv.match_player_ids("Batter, Bob", PLAYERS) == ["t1"]
    assert adv.match_player_ids("Bob Batter", PLAYERS) == ["t1"]
    assert adv.match_player_ids("Jose Munoz", PLAYERS) == ["t4"]
    assert adv.match_player_ids("Shawon Dunston Jr.", PLAYERS) == ["d1", "d2", "d3"]


def test_every_id_for_the_same_player_is_returned():
    assert adv.match_player_ids("Dunston, Shawon", PLAYERS) == ["d1", "d2", "d3"]


def test_exact_name_beats_a_shared_initial():
    # Jaylen and Julian Smith share an initial, but Jaylen is an exact match.
    assert adv.match_player_ids("Jaylen Smith", PLAYERS) == ["s1"]
    assert adv.match_player_ids("James Nelson", PLAYERS) == ["n1"]


def test_initial_only_match_must_point_at_one_person():
    assert adv.match_player_ids("J. Smith", PLAYERS) == []        # Jaylen or Julian
    assert adv.match_player_ids("Bobby Batter", PLAYERS) == ["t1"]
    assert adv.match_player_ids("Nobody, Here", PLAYERS) == []
