"""How every stat is labeled, ordered, grouped and formatted.

One place for this so a stat looks the same in the table, the player card and
the PDF. Streamlit-free.
"""
from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Palette. Ink and red brand, with a quadrant set that passes the colorblind
# validator (teal, amber, violet, red; all-pairs CVD delta E >= 13).
# ---------------------------------------------------------------------------
INK = "#1b1f2a"
MUTED = "#6b7280"
ACCENT = "#c62127"
PANEL = "#f5f4ef"
GRID = "#e5e7eb"
QUAD_GOOD = "#1f9d8a"
QUAD_MIXED_A = "#eda100"
QUAD_MIXED_B = "#6250d6"
QUAD_BAD = "#c62127"

# ---------------------------------------------------------------------------
# Column order. Who, then volume, then counting stats, then rates, then
# advanced, then splits.
# ---------------------------------------------------------------------------
HITTER_COLS = [
    "PLAYER", "BATS", "G", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI",
    "BB", "SO", "HBP", "SB", "AVG", "OBP", "SLG", "OPS",
    "ISO", "BB%", "K%", "BB/K", "wOBA", "BABIP", "xBABIP", "xK%", "xBB%",
    "vsL_PA", "vsL_OPS", "vsR_PA", "vsR_OPS", "RISP_PA", "RISP_OPS",
    "Home_OPS", "Away_OPS",
]
PITCHER_COLS = [
    "PLAYER", "THROWS", "ROLE", "G", "GS", "IP", "BF", "NP", "H", "R", "ER",
    "HR", "BB", "SO", "ERA", "FIP", "ERA-FIP", "WHIP", "K9", "BB9", "HR9",
    "K/BB", "K%", "BB%", "K-BB%", "BABIP_A", "STR%", "P/PA",
    "vsL_PA", "vsL_OPS", "vsR_PA", "vsR_OPS", "RISP_OPS",
]

# Views follow scouting-report groupings, each answering one question.
HITTER_VIEWS = {
    "Traditional": ("The classic box score line.",
                    ["PLAYER", "BATS", "PA", "AB", "R", "H", "2B", "3B", "HR",
                     "RBI", "BB", "SO", "SB"]),
    "Slash Line": ("AVG / OBP / SLG / OPS, the one-glance summary of a hitter.",
                   ["PLAYER", "BATS", "PA", "AVG", "OBP", "SLG", "OPS"]),
    "Power": ("Extra-base production. ISO is SLG minus AVG.",
              ["PLAYER", "PA", "H", "2B", "3B", "HR", "RBI", "SLG", "ISO"]),
    "Discipline": ("Plate approach. BB% and K% are per plate appearance.",
                   ["PLAYER", "PA", "BB", "SO", "HBP", "BB%", "K%", "BB/K", "OBP"]),
    "Advanced": ("wOBA weights each way of reaching base by its run value. "
                 "x columns are the regressed estimates to trust over a small sample.",
                 ["PLAYER", "PA", "wOBA", "OPS", "BABIP", "xBABIP", "K%", "xK%", "BB%", "xBB%"]),
    "Splits": ("OPS against left- and right-handed pitching, with runners in scoring "
               "position, and home versus road.",
               ["PLAYER", "BATS", "PA", "vsL_PA", "vsL_OPS", "vsR_PA", "vsR_OPS",
                "RISP_PA", "RISP_OPS", "Home_OPS", "Away_OPS"]),
}
PITCHER_VIEWS = {
    "Traditional": ("The classic pitching line.",
                    ["PLAYER", "THROWS", "IP", "H", "R", "ER", "HR", "BB", "SO",
                     "ERA", "WHIP"]),
    "Rates": ("Per-inning effectiveness. K/BB is strikeouts per walk.",
              ["PLAYER", "THROWS", "IP", "ERA", "WHIP", "K9", "BB9", "K/BB"]),
    "Advanced": ("FIP is ERA built only from strikeouts, walks, HBP and homers. "
                 "K-BB% is the best single predictor of future runs allowed in ALPB data.",
                 ["PLAYER", "ROLE", "IP", "ERA", "FIP", "ERA-FIP", "K%", "BB%",
                  "K-BB%", "BABIP_A"]),
    "Command": ("Strike throwing. Each point of strike rate is worth about a point of walk rate.",
                ["PLAYER", "THROWS", "IP", "NP", "STR%", "P/PA", "BB%", "K%"]),
    "Splits": ("OPS allowed to left- and right-handed batters and with runners in scoring position.",
               ["PLAYER", "THROWS", "BF", "vsL_PA", "vsL_OPS", "vsR_PA", "vsR_OPS", "RISP_OPS"]),
    "Workload": ("How much each arm has been used.",
                 ["PLAYER", "THROWS", "ROLE", "G", "GS", "IP", "BF", "NP"]),
}

# Short header labels for internal column names.
LABELS = {
    "vsL_PA": "PA vs L", "vsL_OPS": "OPS vs L", "vsR_PA": "PA vs R",
    "vsR_OPS": "OPS vs R", "RISP_PA": "PA RISP", "RISP_OPS": "OPS RISP",
    "Home_OPS": "OPS Home", "Away_OPS": "OPS Road", "BABIP_A": "BABIP",
}


def label(col: str) -> str:
    return LABELS.get(col, col)


# Decimal places per stat. ERA 5.90, never 5.9.
DECIMALS = {
    "AVG": 3, "OBP": 3, "SLG": 3, "OPS": 3, "ISO": 3, "wOBA": 3, "BABIP": 3,
    "xBABIP": 3, "BABIP_A": 3, "vsL_OPS": 3, "vsR_OPS": 3, "RISP_OPS": 3,
    "Home_OPS": 3, "Away_OPS": 3,
    "ERA": 2, "FIP": 2, "ERA-FIP": 2, "WHIP": 2, "K9": 2, "BB9": 2, "HR9": 2,
    "K/BB": 2, "BB/K": 2, "P/PA": 2,
    "BB%": 1, "K%": 1, "xK%": 1, "xBB%": 1, "K-BB%": 1, "STR%": 1, "IP": 1,
}

HELP = {
    "G": "Games", "PA": "Plate appearances", "AB": "At bats", "R": "Runs", "H": "Hits",
    "2B": "Doubles", "3B": "Triples", "HR": "Home runs", "RBI": "Runs batted in",
    "BB": "Walks", "SO": "Strikeouts", "HBP": "Hit by pitch", "SB": "Stolen bases",
    "AVG": "Batting average", "OBP": "On-base percentage",
    "SLG": "Slugging percentage", "OPS": "On-base plus slugging",
    "ISO": "Isolated power, SLG minus AVG",
    "BB%": "Walks per plate appearance (batters faced for pitchers), as a percent",
    "K%": "Strikeouts per plate appearance (batters faced for pitchers), as a percent",
    "BB/K": "Walks per strikeout",
    "wOBA": "Weighted on-base average. Each way of reaching base weighted by its run value "
            "(MLB weights). A better single number than OPS.",
    "BABIP": "Batting average on balls in play. About 80% of the spread between players is luck.",
    "xBABIP": "BABIP regressed toward the league rate by sample size. The better guess at true talent.",
    "xK%": "K% regressed toward the league rate by sample size",
    "xBB%": "BB% regressed toward the league rate by sample size",
    "IP": "Innings pitched. 53.1 means 53 and one third.", "BF": "Batters faced",
    "NP": "Pitches thrown", "ER": "Earned runs", "ERA": "Earned run average",
    "FIP": "Fielding independent pitching. ERA scale, built from K, BB, HBP and HR only.",
    "ERA-FIP": "Positive means ERA is worse than the peripherals suggest, often defense or luck.",
    "WHIP": "Walks plus hits per inning pitched",
    "K9": "Strikeouts per nine innings", "BB9": "Walks per nine innings",
    "HR9": "Home runs per nine innings", "K/BB": "Strikeouts per walk, blank with no walks",
    "K-BB%": "Strikeout rate minus walk rate. Most predictive pitching stat in ALPB data.",
    "STR%": "Share of pitches that were strikes", "P/PA": "Pitches per batter faced",
    "ROLE": "SP if at least half of appearances were starts, else RP",
    "GS": "Games started", "BABIP_A": "BABIP allowed",
    "vsL_PA": "Plate appearances against left-handed pitchers (left-handed batters for pitchers)",
    "vsL_OPS": "OPS against lefties", "vsR_PA": "Plate appearances against righties",
    "vsR_OPS": "OPS against righties", "RISP_PA": "Plate appearances with runners in scoring position",
    "RISP_OPS": "OPS with runners in scoring position",
    "Home_OPS": "OPS at home", "Away_OPS": "OPS on the road",
}


def format_cell(col, value):
    """One display rule for every cell outside a Streamlit table."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return "-"
    if col in DECIMALS:
        try:
            return f"{float(value):.{DECIMALS[col]}f}"
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
