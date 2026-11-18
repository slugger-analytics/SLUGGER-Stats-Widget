"""Two players side by side, Baseball Savant style.

The stat sits in the middle and each player's bar grows outward from it. A
longer bar is always better, so on stats where lower wins (ERA, K% for a
hitter) the lower number gets the full bar. Only rates are scored. Totals are
shown in grey for context, because more playing time always means bigger
totals and a pitcher with fewer innings would "win" hits and runs allowed.
"""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from data import UpstreamError, enrich, get_team_players, get_team_stats_aggregated
from display import GOOD, HELP, INK, MUTED, format_cell
from stats_utils import ip_to_innings

# (stat, high_is_good). None means shown but never scored.
COMPARE_ROWS = {
    "hitter": [
        ("Rates", [("AVG", True), ("OBP", True), ("SLG", True), ("OPS", True),
                   ("wOBA", True), ("ISO", True), ("BB%", True), ("K%", False)]),
        ("Totals", [("PA", None), ("AB", None), ("R", None), ("H", None),
                    ("2B", None), ("3B", None), ("HR", None), ("RBI", None),
                    ("BB", None), ("SO", None), ("SB", None)]),
    ],
    "pitcher": [
        ("Rates", [("ERA", False), ("FIP", False), ("WHIP", False), ("K9", True),
                   ("BB9", False), ("K/BB", True), ("K-BB%", True)]),
        ("Totals", [("IP", None), ("BF", None), ("H", None), ("R", None),
                    ("ER", None), ("HR", None), ("BB", None), ("SO", None)]),
    ],
}
BAR_LOSE = "#cbd5e1"
BAR_NEUTRAL = "#94a3b8"


def _num(stat, value):
    if value is None or pd.isna(value):
        return None
    # Bars use true innings, so 133.1 IP is 133 1/3, not 133.1.
    return float(ip_to_innings(value)) if stat == "IP" else float(value)


def compare_rows(row_a, row_b, kind):
    """Everything the head to head draws, as plain data so it can be tested.

    Returns ``[(group, [row, ...]), ...]``. Each row has the stat, both display
    values, both bar widths as a percent, and which side won (0, 1 or None).
    """
    out = []
    for group, stats in COMPARE_ROWS[kind]:
        rows = []
        for stat, high_good in stats:
            a, b = row_a.get(stat), row_b.get(stat)
            va, vb = _num(stat, a), _num(stat, b)
            present = [v for v in (va, vb) if v is not None]
            top, low = max(present, default=0), min(present, default=0)

            def width(v):
                if v is None:
                    return 0.0
                if high_good is False:   # smaller is better, so it gets the full bar
                    return 100.0 if v <= 0 else round(100 * low / v, 1)
                return 0.0 if top <= 0 else round(100 * v / top, 1)

            winner = None
            if high_good is not None and va is not None and vb is not None and va != vb:
                winner = 0 if (va > vb) == high_good else 1
            rows.append({"stat": stat, "a": format_cell(stat, a), "b": format_cell(stat, b),
                         "bar_a": width(va), "bar_b": width(vb), "winner": winner})
        out.append((group, rows))
    return out


def compare_html(names, groups):
    def color(row, side):
        if row["winner"] is None:
            return BAR_NEUTRAL
        return GOOD if row["winner"] == side else BAR_LOSE

    parts = [f"""
<style>
.h2h {{ font-family: inherit; width: 100%; color: {INK}; }}
.h2h-row {{ display: grid; grid-template-columns: 72px 1fr 96px 1fr 72px;
            align-items: center; gap: 10px; padding: 4px 0; }}
.h2h-head {{ font-weight: 700; font-size: 0.95rem; padding-bottom: 8px;
             border-bottom: 1px solid #e5e7eb; }}
.h2h-group {{ font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase;
              color: {MUTED}; margin: 14px 0 2px 0; text-align: center; }}
.h2h-val {{ font-variant-numeric: tabular-nums; font-size: 0.95rem; }}
.h2h-val.l {{ text-align: right; }}
.h2h-val.win {{ font-weight: 700; }}
.h2h-stat {{ text-align: center; font-weight: 600; font-size: 0.9rem; }}
.h2h-track {{ height: 12px; background: #f1f5f9; border-radius: 6px; display: flex; }}
.h2h-track.l {{ justify-content: flex-end; }}
.h2h-bar {{ height: 100%; border-radius: 6px; }}
</style>
<div class="h2h">
  <div class="h2h-row h2h-head">
    <div></div><div style="text-align:right">{escape(names[0])}</div>
    <div></div><div>{escape(names[1])}</div><div></div>
  </div>"""]
    for group, rows in groups:
        parts.append(f'<div class="h2h-group">{escape(group)}</div>')
        for r in rows:
            parts.append(f"""
  <div class="h2h-row">
    <div class="h2h-val l{' win' if r['winner'] == 0 else ''}">{escape(r['a'])}</div>
    <div class="h2h-track l"><div class="h2h-bar" style="width:{r['bar_a']}%;background:{color(r, 0)}"></div></div>
    <div class="h2h-stat" title="{escape(HELP.get(r['stat'], ''))}">{escape(r['stat'])}</div>
    <div class="h2h-track"><div class="h2h-bar" style="width:{r['bar_b']}%;background:{color(r, 1)}"></div></div>
    <div class="h2h-val{' win' if r['winner'] == 1 else ''}">{escape(r['b'])}</div>
  </div>""")
    parts.append("</div>")
    return "".join(parts)


def _team_tables(team_name, teams_df, report):
    team_guid = teams_df[teams_df["TEAM"] == team_name].iloc[0]["team_guid"]
    batting, pitching = get_team_stats_aggregated(team_guid, get_team_players(team_guid))
    batting, pitching, _ = enrich(batting, pitching, report)
    return batting, pitching


def render_compare(teams_df, default_team, kind, report, default_player=None):
    """Pick a team and player on each side. Player 1 starts on the row picked
    in the table above, when there is one."""
    mode = "hitters" if kind == "hitter" else "pitchers"
    teams = sorted(teams_df["TEAM"].dropna().unique())
    start = teams.index(default_team) if default_team in teams else 0
    defaults = [start, (start + 1) % len(teams)]

    picks = []
    for i, slot in enumerate(st.columns(2)):
        with slot:
            team = st.selectbox(f"Team {i + 1}", teams, index=defaults[i],
                                key=f"cmp_team_{kind}_{i}")
            try:
                batting, pitching = _team_tables(team, teams_df, report)
            except UpstreamError as e:
                st.warning(f"Couldn't load {team}. {e}")
                picks.append(None)
                continue
            table = batting if kind == "hitter" else pitching
            if table.empty:
                st.info(f"No {mode} with stats for {team}.")
                picks.append(None)
                continue
            table = table.sort_values("PA" if kind == "hitter" else "BF", ascending=False)
            names = table["PLAYER"].tolist()
            at = names.index(default_player) if (
                i == 0 and team == default_team and default_player in names) else 0
            name = st.selectbox(f"Player {i + 1}", names, index=at,
                                key=f"cmp_player_{i}_{kind}_{team}_{default_player}")
            row = table[table["PLAYER"] == name].iloc[0]
            hand = row.get("BATS") if kind == "hitter" else row.get("THROWS")
            st.caption(f"{team}  |  {'Bats' if kind == 'hitter' else 'Throws'} {hand}")
            picks.append((team, row))

    if None in picks:
        return
    (team_a, row_a), (team_b, row_b) = picks
    names = [row_a["PLAYER"], row_b["PLAYER"]]
    if names[0] == names[1] and team_a == team_b:
        st.info("Pick two different players.")
        return
    if names[0] == names[1]:
        names = [f"{names[0]} ({team_a})", f"{names[1]} ({team_b})"]
    st.html(compare_html(names, compare_rows(row_a, row_b, kind)))
