"""Pitch-level advanced stats from SLUGGER's Trackman feed.

Streamlit-free so every formula can be unit tested. The widget fetches one
player's pitches from the ALPB Trackman API and hands the rows to
``hitter_advanced`` or ``pitcher_advanced``.

iScore only knows outcomes (a walk, a strikeout). Plate discipline needs where
each pitch crossed the plate and whether the batter swung, which only Trackman
records, so everything in this module is built from Trackman pitch rows.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Strike zone
# ---------------------------------------------------------------------------
# Trackman gives plate location in feet. It does not give each batter's own
# zone top and bottom, so a fixed rulebook-style zone is used for everyone.
# Half the plate is 8.5 inches, plus a ball radius of about 1.45 inches, so a
# pitch that touches the edge counts. 1.5 to 3.5 feet is the usual average
# zone height used in public Trackman work.
ZONE_HALF_WIDTH = 0.83
ZONE_BOTTOM = 1.5
ZONE_TOP = 3.5

# PitchCall values. Trackman spells the dirt ball both BallInDirt and BallinDirt.
SWINGS = {"StrikeSwinging", "FoulBall", "FoulBallNotFieldable",
          "FoulBallFieldable", "InPlay"}
CONTACT = {"FoulBall", "FoulBallNotFieldable", "FoulBallFieldable", "InPlay"}
WHIFFS = {"StrikeSwinging"}
CALLED_STRIKES = {"StrikeCalled"}
# Not real pitches for rate purposes.
IGNORED_CALLS = {"Undefined", "BallIntentional", None, "", "NaN"}

HARD_HIT_MPH = 95.0
SWEET_SPOT = (8.0, 32.0)
BARREL_MPH = 98.0


def is_barrel(ev: pd.Series, la: pd.Series) -> pd.Series:
    """Statcast-style barrel. At 98 mph the launch angle window is 26 to 30
    degrees, and it widens about a degree each way per extra mph until it
    reaches 8 to 50 degrees at 116 mph. Statcast's exact table widens a little
    faster past 100 mph, so this is a close approximation, not a copy."""
    extra = (ev - BARREL_MPH).clip(lower=0, upper=18)
    low = 26.0 - extra
    high = 30.0 + extra * (20.0 / 18.0)
    return (ev >= BARREL_MPH) & (la >= low) & (la <= high)

FASTBALLS = {"Four-Seam", "Fastball", "Sinker", "Two-Seam"}
PITCH_NAMES = {
    "FourSeamFastBall": "Four-Seam", "Four-Seam": "Four-Seam",
    "Fastball": "Fastball", "TwoSeamFastBall": "Two-Seam", "Sinker": "Sinker",
    "Cutter": "Cutter", "Slider": "Slider", "Sweeper": "Sweeper",
    "Curveball": "Curveball", "ChangeUp": "Changeup", "Changeup": "Changeup",
    "Splitter": "Splitter", "Knuckleball": "Knuckleball",
}
HIT_TYPES = {"GroundBall": "GB", "LineDrive": "LD", "FlyBall": "FB", "Popup": "PU"}

# Only these columns are kept after a fetch. A raw Trackman row has around 200
# fields and a regular's season is a few thousand rows.
KEEP_COLS = ["date", "pitcher_id", "batter_id", "balls", "strikes", "pitch_call",
             "plate_loc_side", "plate_loc_height", "exit_speed", "angle",
             "tagged_hit_type", "auto_hit_type", "tagged_pitch_type",
             "auto_pitch_type", "rel_speed", "spin_rate", "induced_vert_break",
             "horz_break", "batter_side", "pitcher_throws"]


def trim(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only the columns this module reads."""
    return df[[c for c in KEEP_COLS if c in df.columns]].copy()


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").astype(float)


def _str(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype=object)
    return df[col].fillna("").astype(str)


def _pick(tagged: pd.Series, auto: pd.Series) -> pd.Series:
    """Use the operator's tag when there is one, the auto tag otherwise."""
    bad = tagged.isin(["", "Undefined", "Other", "None", "nan", "NaN"])
    return tagged.where(~bad, auto)


def prepare(pitches: pd.DataFrame) -> pd.DataFrame:
    """Add the boolean flags every rate is built from.

    Rows with an undefined or intentional-ball call are dropped. Location
    flags are left blank (NaN) when Trackman did not track the location, so
    those pitches count toward swing and whiff rates but not toward zone rates.
    """
    if pitches is None or pitches.empty or "pitch_call" not in pitches.columns:
        return pd.DataFrame()
    df = pitches.reset_index(drop=True)
    call = df["pitch_call"].replace({"BallinDirt": "BallInDirt"})
    df = df[~call.isin(IGNORED_CALLS) & call.notna()].copy()
    call = call.loc[df.index]
    df["call"] = call

    side = _num(df, "plate_loc_side")
    height = _num(df, "plate_loc_height")
    located = side.notna() & height.notna()
    in_zone = (side.abs() <= ZONE_HALF_WIDTH) & height.between(ZONE_BOTTOM, ZONE_TOP)
    df["located"] = located
    df["in_zone"] = in_zone.where(located)

    df["swing"] = call.isin(SWINGS)
    df["contact"] = call.isin(CONTACT)
    df["whiff"] = call.isin(WHIFFS)
    df["called_strike"] = call.isin(CALLED_STRIKES)
    df["in_play"] = call == "InPlay"
    df["first_pitch"] = (_num(df, "balls") == 0) & (_num(df, "strikes") == 0)

    df["ev"] = _num(df, "exit_speed").where(df["in_play"])
    df["la"] = _num(df, "angle").where(df["in_play"])
    hit = _pick(_str(df, "tagged_hit_type"), _str(df, "auto_hit_type"))
    df["hit_type"] = hit.map(HIT_TYPES).where(df["in_play"])

    ptype = _pick(_str(df, "tagged_pitch_type"), _str(df, "auto_pitch_type"))
    df["pitch_type"] = ptype.map(PITCH_NAMES).fillna("Untagged")
    df["velo"] = _num(df, "rel_speed")
    return df


def _pct(num, den) -> float:
    num, den = float(num), float(den)
    return round(100.0 * num / den, 1) if den else np.nan


def _mean(series: pd.Series, digits: int = 1) -> float:
    vals = series.dropna()
    return round(float(vals.mean()), digits) if len(vals) else np.nan


def _max(series: pd.Series, digits: int = 1) -> float:
    vals = series.dropna()
    return round(float(vals.max()), digits) if len(vals) else np.nan


def _discipline(df: pd.DataFrame) -> dict:
    """Zone, swing and contact rates shared by hitters and pitchers."""
    loc = df[df["located"]]
    zone = loc[loc["in_zone"] == True]   # noqa: E712  (NaN-safe on object dtype)
    chase = loc[loc["in_zone"] == False]  # noqa: E712
    swings = df[df["swing"]]
    return {
        "Pitches": int(len(df)),
        "Zone%": _pct(len(zone), len(loc)),
        "Swing%": _pct(len(swings), len(df)),
        "Z-Swing%": _pct(zone["swing"].sum(), len(zone)),
        "Chase%": _pct(chase["swing"].sum(), len(chase)),
        "Z-Contact%": _pct((zone["swing"] & zone["contact"]).sum(), zone["swing"].sum()),
        "O-Contact%": _pct((chase["swing"] & chase["contact"]).sum(), chase["swing"].sum()),
        "Contact%": _pct(swings["contact"].sum(), len(swings)),
        "Whiff%": _pct(swings["whiff"].sum(), len(swings)),
        "SwStr%": _pct(df["whiff"].sum(), len(df)),
    }


def _batted_ball(df: pd.DataFrame) -> dict:
    bbe = df[df["ev"].notna()]
    typed = df[df["hit_type"].notna()]
    la = bbe["la"]
    both = bbe[bbe["la"].notna()]
    return {
        "BBE": int(len(bbe)),
        "Barrel%": _pct(is_barrel(both["ev"], both["la"]).sum(), len(both)),
        "EV90": round(float(bbe["ev"].quantile(0.9)), 1) if len(bbe) else np.nan,
        "Avg EV": _mean(bbe["ev"]),
        "Max EV": _max(bbe["ev"]),
        "Hard-Hit%": _pct((bbe["ev"] >= HARD_HIT_MPH).sum(), len(bbe)),
        "Avg LA": _mean(la),
        "Sweet-Spot%": _pct(la.between(*SWEET_SPOT).sum(), la.notna().sum()),
        "GB%": _pct((typed["hit_type"] == "GB").sum(), len(typed)),
        "LD%": _pct((typed["hit_type"] == "LD").sum(), len(typed)),
        "FB%": _pct((typed["hit_type"].isin(["FB", "PU"])).sum(), len(typed)),
    }


def hitter_advanced(pitches: pd.DataFrame) -> dict:
    """Every pitch a batter saw, summarised. Empty dict when there is no data."""
    df = prepare(pitches)
    if df.empty:
        return {}
    out = _discipline(df)
    first = df[df["first_pitch"]]
    out["1st-Pitch Swing%"] = _pct(first["swing"].sum(), len(first))
    out.update(_batted_ball(df))
    return out


def pitcher_advanced(pitches: pd.DataFrame) -> dict:
    """Every pitch a pitcher threw, summarised. Empty dict when there is no data."""
    df = prepare(pitches)
    if df.empty:
        return {}
    out = _discipline(df)
    out["CSW%"] = _pct((df["called_strike"] | df["whiff"]).sum(), len(df))
    first = df[df["first_pitch"]]
    out["F-Strike%"] = _pct((first["swing"] | first["called_strike"]).sum(), len(first))
    fb = df[df["pitch_type"].isin(FASTBALLS)]
    out["FB Velo"] = _mean(fb["velo"])
    out["Max Velo"] = _max(df["velo"])
    out.update(_batted_ball(df))
    return out


def arsenal(pitches: pd.DataFrame) -> pd.DataFrame:
    """One row per pitch type, most used first, like a Savant pitch mix table."""
    df = prepare(pitches)
    if df.empty:
        return pd.DataFrame()
    rows = []
    for name, g in df.groupby("pitch_type"):
        swings = g[g["swing"]]
        loc = g[g["located"]]
        rows.append({
            "Pitch": name,
            "#": int(len(g)),
            "Usage%": _pct(len(g), len(df)),
            "Velo": _mean(g["velo"]),
            "Max": _max(g["velo"]),
            "Spin": _mean(_num(g, "spin_rate"), 0),
            "IVB": _mean(_num(g, "induced_vert_break")),
            "HB": _mean(_num(g, "horz_break")),
            "Zone%": _pct((loc["in_zone"] == True).sum(), len(loc)),  # noqa: E712
            "Whiff%": _pct(swings["whiff"].sum(), len(swings)),
        })
    return pd.DataFrame(rows).sort_values("#", ascending=False, ignore_index=True)


# ---------------------------------------------------------------------------
# Stat metadata for display
# ---------------------------------------------------------------------------
# (stat, good direction for a HITTER, good direction for a PITCHER, help)
# True means higher is better, False lower is better, None means neither.
STAT_INFO = {
    "Pitches": (None, None, "Pitches seen or thrown with a recorded result"),
    "Zone%": (None, True, "Share of tracked pitches inside the strike zone"),
    "Swing%": (None, None, "Swings per pitch"),
    "Z-Swing%": (True, False, "Swings at pitches in the zone, per zone pitch"),
    "Chase%": (False, True, "Swings at pitches outside the zone, per outside pitch (O-Swing%)"),
    "Z-Contact%": (True, False, "Contact per swing on pitches in the zone"),
    "O-Contact%": (None, False, "Contact per swing on pitches outside the zone"),
    "Contact%": (True, False, "Foul or fair contact per swing"),
    "Whiff%": (False, True, "Swings and misses per swing"),
    "SwStr%": (False, True, "Swings and misses per pitch"),
    "1st-Pitch Swing%": (None, None, "Swings on 0-0 pitches"),
    "CSW%": (None, True, "Called strikes plus whiffs, per pitch"),
    "F-Strike%": (None, True, "0-0 pitches that became a strike or were put in play"),
    "FB Velo": (None, True, "Average release speed of fastballs and sinkers, mph"),
    "Max Velo": (None, True, "Fastest pitch thrown, mph"),
    "BBE": (None, None, "Batted ball events with a tracked exit velocity"),
    "Barrel%": (True, False, "Balls in play hit hard enough at the right launch angle to usually become extra-base hits, per batted ball. The headline power stat"),
    "EV90": (True, False, "90th percentile exit velocity, mph. How hard a player hits his best balls, steadier than Max EV"),
    "Avg EV": (True, False, "Average exit velocity on balls in play, mph"),
    "Max EV": (True, False, "Hardest ball in play, mph"),
    "Hard-Hit%": (True, False, f"Balls in play at {HARD_HIT_MPH:.0f}+ mph"),
    "Avg LA": (None, None, "Average launch angle on balls in play, degrees"),
    "Sweet-Spot%": (True, False, f"Balls in play launched between {SWEET_SPOT[0]:.0f} and {SWEET_SPOT[1]:.0f} degrees"),
    "GB%": (None, True, "Ground balls per typed ball in play"),
    "LD%": (True, False, "Line drives per typed ball in play"),
    "FB%": (None, None, "Fly balls and pop ups per typed ball in play"),
}

HITTER_GROUPS = {
    "Plate Discipline": ["Pitches", "Zone%", "Swing%", "Z-Swing%", "Chase%",
                         "1st-Pitch Swing%"],
    "Contact": ["Z-Contact%", "O-Contact%", "Contact%", "Whiff%", "SwStr%"],
    "Batted Ball": ["BBE", "Barrel%", "EV90", "Hard-Hit%", "Avg EV", "Max EV",
                    "Avg LA", "Sweet-Spot%", "GB%", "LD%", "FB%"],
}
PITCHER_GROUPS = {
    "Stuff and Command": ["Pitches", "FB Velo", "Max Velo", "Zone%",
                          "F-Strike%", "CSW%"],
    "Swing and Miss": ["Swing%", "Chase%", "Z-Swing%", "Z-Contact%",
                       "Whiff%", "SwStr%"],
    "Contact Allowed": ["BBE", "Barrel%", "Avg EV", "Hard-Hit%", "Avg LA", "GB%", "LD%", "FB%"],
}


def better(stat: str, kind: str, a, b):
    """Return 0 or 1 for the better of two values, or None for a tie or neutral stat."""
    info = STAT_INFO.get(stat)
    direction = None
    if info is not None:
        direction = info[0] if kind == "hitter" else info[1]
    if direction is None or pd.isna(a) or pd.isna(b) or a == b:
        return None
    a_wins = (a > b) if direction else (a < b)
    return 0 if a_wins else 1


# ---------------------------------------------------------------------------
# Matching iScore players to Trackman player ids
# ---------------------------------------------------------------------------
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _split(name) -> tuple[str, str]:
    """Return ``(first, last)`` for both 'Last, First' and 'First Last'."""
    raw = str(name or "")
    if "," in raw:
        last, first = raw.split(",", 1)
    else:
        parts = raw.split()
        first, last = (parts[0], " ".join(parts[1:])) if len(parts) > 1 else ("", raw)
    last_tokens = [t for t in normalize_name(last).split() if t not in _SUFFIXES]
    return normalize_name(first), " ".join(last_tokens)


def _same_team(a, b) -> bool:
    ta = {t for t in normalize_name(a).split() if len(t) >= 4}
    tb = {t for t in normalize_name(b).split() if len(t) >= 4}
    return bool(ta & tb)


def match_player_ids(name, candidates: pd.DataFrame) -> list[str]:
    """Every Trackman ``player_id`` that belongs to an iScore player.

    Trackman gives the same player a new id for each team he plays for, plus
    ids with no team at all, so one season can be spread across several ids.
    Every id whose first and last name match exactly is returned, and the
    caller combines their pitches. If there is no exact match, a last name plus
    first initial match is used, but only when it points at one person, so a
    "J. Smith" never pulls in both Jaylen and Julian.
    """
    if candidates is None or candidates.empty:
        return []
    first, last = _split(name)
    if not last:
        return []
    split = candidates["player_name"].map(_split)
    c_first = split.map(lambda p: p[0])
    c_last = split.map(lambda p: p[1])

    exact = candidates[(c_last == last) & (c_first == first)]
    if not exact.empty:
        return sorted({str(i) for i in exact["player_id"]})
    if not first:
        return []
    initial = candidates[(c_last == last) & (c_first.str[:1] == first[:1])]
    if split.loc[initial.index].nunique() == 1:
        return sorted({str(i) for i in initial["player_id"]})
    return []
