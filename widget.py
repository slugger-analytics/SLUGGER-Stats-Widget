"""ALPB Player Stats, a Streamlit widget in the SLUGGER project (JHU SARG).

This file is the page. Data access lives in data.py, stat math in metrics.py
and league.py, display rules in display.py, figures in charts.py, the PDF in
and report_pdf.py.
"""
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import advanced as adv
import trackman
from charts import era_fip_chart, team_bars
from compare import render_compare
from data import (
    UpstreamError,
    enrich,
    get_league_teams,
    get_team_players,
    get_team_stats_aggregated,
    load_league_report,
    percentile,
)
from display import (
    DECIMALS,
    HELP,
    HITTER_COLS,
    HITTER_VIEWS,
    PITCHER_COLS,
    PITCHER_VIEWS,
    format_cell,
    label,
)
from report_pdf import generate_pdf, pdf_filename
from stats_utils import filter_min_sample, ip_to_innings, ordinal, rank_among

st.set_page_config(page_title="ALPB Player Stats", layout="wide")

STYLE = """
<style>
#MainMenu, footer, header {visibility: hidden;}
html {font-size: 14px;}
.block-container {padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1440px;}
h1 {font-size: 1.55rem !important; font-weight: 700; padding: 0 0 .35rem 0 !important;
    border-bottom: 2px solid #c62127; margin-bottom: .4rem;}
h2, h3 {font-size: 1.05rem !important; font-weight: 650; margin: .4rem 0 .15rem 0 !important;
    padding: 0 !important;}
div[data-testid="stCaptionContainer"] {color: #6b7280;}
span[data-tag] {background-color: #e5e7eb !important; color: #1b1f2a !important;
    border-radius: 999px !important; font-size: 0.8rem;}
span[data-tag] svg {fill: #6b7280 !important;}
div[data-testid="stMetricValue"] {font-size: 1.2rem;}
div[data-testid="stMetricLabel"] p {color: #6b7280; font-size: .75rem;}
div[data-testid="stTabs"] button p {font-size: .95rem; font-weight: 600;}
div[data-testid="stExpander"] summary p {font-size: .9rem;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 6px;}
</style>
"""


def stop_on_upstream_error(error):
    """Report an outage as a live, retryable condition rather than a dead page."""
    st.warning("Couldn't reach the league stats feed just now.")
    st.caption(str(error))
    st.button("Try again")
    st.stop()


# -------------------
# Player card
# -------------------
# A player is ranked against teammates with at least this much playing time.
MIN_PA = 20
MIN_INNINGS = 5


def qualified(df, kind):
    if kind == "hitter":
        return filter_min_sample(df, "PA", MIN_PA)
    return df[df["IP"].map(ip_to_innings) >= MIN_INNINGS]


def tile_rows(items, per_row=4):
    """Yield ``(slot, item)`` pairs, ``per_row`` tiles to a row, so the card's
    stat tiles stay readable in the narrow right-hand column."""
    items = list(items)
    for start in range(0, len(items), per_row):
        chunk = items[start:start + per_row]
        yield from zip(st.columns(per_row), chunk)


def render_trackman_tiles(name, kind):
    """Four key Trackman numbers up front, the full breakdown collapsed below,
    so the card stays about as tall as the table beside it."""
    st.markdown("**Trackman**")
    summary, message = trackman.player_summary(name, kind)
    if message:
        st.caption(message)
        return
    for slot, stat in tile_rows(adv.KEY_STATS[kind]):
        with slot:
            st.metric(stat, format_cell(stat, summary.get(stat)), help=HELP.get(stat))
    with st.expander("Full Trackman breakdown"):
        groups = adv.HITTER_GROUPS if kind == "hitter" else adv.PITCHER_GROUPS
        for group, stats in groups.items():
            st.caption(group)
            for slot, stat in tile_rows(stats):
                with slot:
                    st.metric(stat, format_cell(stat, summary.get(stat)), help=HELP.get(stat))
        st.caption(f"Zone stats use a fixed strike zone ({adv.ZONE_BOTTOM} to {adv.ZONE_TOP} ft "
                   f"high, {adv.ZONE_HALF_WIDTH} ft either side of center) because Trackman "
                   "does not record each batter's own zone.")


# Stat tiles on a player card as (column, high_is_good). None means no ranking.
HITTER_TILES = [("PA", None), ("AVG", True), ("OBP", True), ("SLG", True),
                ("OPS", True), ("wOBA", True), ("K%", False), ("BB%", True)]
PITCHER_TILES = [("IP", None), ("ERA", False), ("FIP", False), ("WHIP", False),
                 ("K9", True), ("BB9", False), ("K-BB%", True)]
# League percentile tables are keyed by these names in the report.
PERCENTILE_KEY = {"BABIP_A": "BABIP_A", "K-BB%": "K-BB%"}


def render_player_card(player, team_df, kind, report):
    """One player's line, team rank, league percentile, Trackman breakdown and splits."""

    tiles = HITTER_TILES if kind == "hitter" else PITCHER_TILES
    hand = player.get("BATS") if kind == "hitter" else player.get("THROWS")
    hand = {"R": "Right", "L": "Left", "S": "Switch", "B": "Switch"}.get(str(hand).upper(), hand)
    hand_label = "Bats" if kind == "hitter" else "Throws"

    # Rank against the qualified players plus this one, so a small sample can
    # still be placed without dragging the whole group's ranks around.
    sample = qualified(team_df, kind)
    small = player.name not in sample.index
    pool = pd.concat([sample, team_df.loc[[player.name]]])
    pool = pool[~pool.index.duplicated()]

    group = "hitters" if kind == "hitter" else "pitchers"
    meta = (report or {}).get("meta", {})
    qualifier = meta.get("hit_min_pa" if kind == "hitter" else "pit_min_bf")
    opportunities = player.get("PA") if kind == "hitter" else player.get("BF")
    in_league_table = bool(report) and opportunities is not None and opportunities >= qualifier

    with st.container(border=True):
        st.markdown(f"### {player['PLAYER']}")
        st.caption(f"{hand_label} {hand}  |  Team ranks are among teammates with at least "
                   + (f"{MIN_PA} PA." if kind == "hitter" else f"{MIN_INNINGS} IP."))
        if small:
            st.warning("Small sample size. Interpret these figures and rankings with caution.")

        for slot, (col, high_good) in tile_rows(tiles):
            with slot:
                st.metric(col, format_cell(col, player.get(col)), help=HELP.get(col))
                if high_good is not None:
                    bits = []
                    ranked = rank_among(pool, player.get(col), col, high_good)
                    if ranked:
                        bits.append(f"{ordinal(ranked[0])} of {ranked[1]} team")
                    if in_league_table:
                        pct = percentile(report, group, PERCENTILE_KEY.get(col, col),
                                         player.get(col), high_good)
                        if pct is not None:
                            bits.append(f"{ordinal(pct)} pct league")
                    if bits:
                        st.caption("  \n".join(bits))
        if report and not in_league_table:
            st.caption(f"League percentiles need at least {qualifier} "
                       f"{'plate appearances' if kind == 'hitter' else 'batters faced'}.")

        render_trackman_tiles(player["PLAYER"], kind)
        _card_detail(player, kind, report)


def _card_detail(player, kind, report):
    """The regressed and split numbers, collapsed so the card stays short."""
    with st.expander("Skill estimate and splits"):
        if kind == "hitter":
            lines = []
            for col, name in (("xK%", "K%"), ("xBB%", "BB%")):
                if pd.notna(player.get(col)):
                    lines.append(f"- **{name}** {format_cell(name, player.get(name))} observed, "
                                 f"{format_cell(col, player.get(col))} regressed to league average "
                                 f"by sample size.")
            if pd.notna(player.get("xBABIP")):
                lines.append(f"- **BABIP** {format_cell('BABIP', player.get('BABIP'))} observed, "
                             f"{format_cell('xBABIP', player.get('xBABIP'))} regressed. "
                             "BABIP is mostly luck over one season, so lean on the regressed figure.")
            st.markdown("\n".join(lines) or "Not enough data.")
            st.markdown(
                f"**OPS** vs L {format_cell('vsL_OPS', player.get('vsL_OPS'))} "
                f"({format_cell('vsL_PA', player.get('vsL_PA'))} PA), "
                f"vs R {format_cell('vsR_OPS', player.get('vsR_OPS'))} "
                f"({format_cell('vsR_PA', player.get('vsR_PA'))} PA), "
                f"RISP {format_cell('RISP_OPS', player.get('RISP_OPS'))}.")
            st.caption("Individual splits rest on small samples. League-wide, almost no "
                       "hitter's platoon or RISP split holds up as real.")
        else:
            if pd.notna(player.get("ERA-FIP")):
                gap = float(player["ERA-FIP"])
                lean = ("ERA is worse than his strikeouts, walks and homers suggest."
                        if gap > 0.5 else
                        "ERA is better than his strikeouts, walks and homers suggest."
                        if gap < -0.5 else "ERA and FIP agree.")
                st.markdown(f"**ERA** {format_cell('ERA', player.get('ERA'))} vs "
                            f"**FIP** {format_cell('FIP', player.get('FIP'))}. {lean}")
            st.markdown(
                f"**OPS allowed** vs L {format_cell('vsL_OPS', player.get('vsL_OPS'))}, "
                f"vs R {format_cell('vsR_OPS', player.get('vsR_OPS'))}, "
                f"RISP {format_cell('RISP_OPS', player.get('RISP_OPS'))}. "
                f"**BABIP allowed** {format_cell('BABIP_A', player.get('BABIP_A'))}.")
            st.caption("Pitcher BABIP and home run rate do not repeat from half-season to "
                       "half-season in ALPB data, so treat them as luck-prone.")


# -------------------
# Tables
# -------------------
def column_config_for(columns):
    """The same formatting rules for every table, so a stat looks the same everywhere."""
    config = {}
    for col in columns:
        if col == "PLAYER":
            config[col] = st.column_config.TextColumn("PLAYER", pinned=True, width="medium")
        elif col in ("BATS", "THROWS", "ROLE"):
            config[col] = st.column_config.TextColumn(label(col), width="small")
        elif col in DECIMALS:
            config[col] = st.column_config.NumberColumn(
                label(col), format=f"%.{DECIMALS[col]}f", help=HELP.get(col))
        else:
            config[col] = st.column_config.NumberColumn(label(col), help=HELP.get(col))
    return config


def render_section(df, *, title, all_cols, views, sort_col, note, empty_msg,
                   view_key, picker_key, pdf_title, pdf_prefix, pdf_key, team, kind,
                   report, teams_df):
    """A heading, a row of views, one table, and a PDF of exactly that table.

    Views are never empty. Only Custom can be, and an empty selection must never
    reach generate_pdf, because download_button builds its payload eagerly on every
    rerun and reportlab raises on a 0-column table.
    """
    st.subheader(title)
    if df.empty:
        st.info(empty_msg)
        return

    df = df.sort_values(sort_col, ascending=False, kind="stable")
    available = [c for c in all_cols if c in df.columns or c in adv.STAT_INFO]

    # Table on the left, the selected player on the right, so the page reads
    # across instead of one long scroll. The comparison goes underneath.
    left, right = st.columns([3, 2], gap="large")
    with left:
        event, df = _render_table(df, available, views, note, view_key, picker_key,
                                  pdf_title, pdf_prefix, pdf_key, team, kind)

    rows = list(event.selection.rows) if event is not None else []
    chosen = rows and rows[0] < len(df)
    # With nothing selected, show the top player so the right side is never empty.
    picked = df.iloc[rows[0]] if chosen else df.iloc[0]
    with right:
        if not chosen:
            st.caption("Showing the top player. Select a row in the table to switch.")
        render_player_card(picked, df, kind, report)

    # The comparison spans the full width under both columns. Off by default,
    # so nobody pays for another team's load unless they ask.
    st.divider()
    if st.toggle(f"Compare two {title.lower()}", key=f"cmp_on_{kind}",
                 help="Pick a player from any team on each side, like Baseball Savant's comparison."):
        render_compare(teams_df, team, kind, report, default_player=picked["PLAYER"])


def _render_table(df, available, views, note, view_key, picker_key,
                  pdf_title, pdf_prefix, pdf_key, team, kind):
    """The view buttons, the table and its PDF. Returns the selection event and
    the table as shown, with Trackman columns added when the view needs them."""
    names = list(views) + ["All", "Custom"]
    view = st.segmented_control("View", names, default=names[0], key=view_key) or names[0]

    if view == "Custom":
        description = "Pick any stats. They always appear in the standard order."
        picked = st.multiselect(
            "Select stats to display", options=available,
            default=[c for c in views[names[0]][1] if c in available], key=picker_key)
        shown = [c for c in available if c in picked]
    elif view == "All":
        description = "Every available stat."
        shown = available
    else:
        description, cols = views[view]
        shown = [c for c in cols if c in available]

    st.caption(f"{description} {note} Select a row to see that player on the right.")
    # Trackman is only queried when a view that shows its columns is open.
    if any(c in adv.STAT_INFO for c in shown):
        df, message = trackman.add_columns(df, kind)
        if message:
            st.info(message)
    event = st.dataframe(
        df[shown], column_config=column_config_for(shown), width="stretch",
        height="content", hide_index=True, on_select="rerun",
        placeholder="-",  # blank cells, e.g. no Trackman match, show "-" not "None"
        selection_mode="single-row", key=f"{view_key}_table_{team}")

    if shown:
        st.download_button(
            label="Download PDF",
            data=generate_pdf(df=df, title=pdf_title, subtitle=f"Team: {team}",
                              selected_cols=shown),
            file_name=pdf_filename(pdf_prefix), mime="application/pdf", key=pdf_key)
    else:
        st.caption("Pick at least one column to export a PDF.")
    return event, df


# -------------------
# Team tab
# -------------------
def _rank_line(rows, col, team, high_good, fmt):
    ordered = sorted((r for r in rows if r.get(col) is not None),
                     key=lambda r: r[col], reverse=high_good)
    names = [r["TEAM"] for r in ordered]
    if team not in names:
        return None, None
    mine = next(r for r in ordered if r["TEAM"] == team)
    return format(mine[col], fmt), f"{ordinal(names.index(team) + 1)} of {len(names)}"


def render_team_tab(team, pit, report):
    """Where this team sits in the league. One summary strip and one chart at a time."""
    if not report:
        st.info("League context is not built yet. Run scripts/build_league_report.py.")
        return
    rows = report["teams"]
    frame = pd.DataFrame(rows)
    base = report["base"]

    st.subheader(f"{team} in the league")
    st.caption("Rank among the 10 ALPB teams for the 2026 season.")
    tiles = [
        ("Offense wOBA", "hit_wOBA", True, ".3f"), ("Offense K%", "hit_K%", False, ".1f"),
        ("Offense BB%", "hit_BB%", True, ".1f"), ("Pitching ERA", "ERA", False, ".2f"),
        ("Pitching FIP", "FIP", False, ".2f"), ("Pitching K-BB%", "pit_K-BB%", True, ".1f"),
    ]
    with st.container(border=True):
        for slot, (name, col, high_good, fmt) in zip(st.columns(len(tiles)), tiles):
            value, rank = _rank_line(rows, col, team, high_good, fmt)
            with slot:
                st.metric(name, value or "-")
                if rank:
                    st.caption(rank)

    mine = frame[frame["TEAM"] == team]
    if not mine.empty:
        m = mine.iloc[0]
        gap = m["ERA"] - m["FIP"]
        lag_note = (", so run prevention lags what the peripherals predict" if gap > 0.4
                    else ", so run prevention beats what the peripherals predict" if gap < -0.4
                    else "")
        hits = round(abs(m["def_hits_vs_avg"]))
        st.markdown(
            f"**Defense and park.** Opponents hit .{int(round(m['def_BABIP'] * 1000)):03d} on balls in play "
            f"against this staff (league .{int(round(base['pit_BABIP'] * 1000)):03d}), "
            f"about {hits} {'fewer' if m['def_hits_vs_avg'] > 0 else 'more'} "
            f"{'hit' if hits == 1 else 'hits'} than an average team would allow (z = {m['def_z']:+.1f}). "
            f"Team ERA is {m['ERA']:.2f} against a FIP of {m['FIP']:.2f}{lag_note}. "
            f"Home games run {abs(m['park_wOBA'] - 100):.0f}% "
            f"{'above' if m['park_wOBA'] > 100 else 'below'} road games in offense "
            f"and {abs(m['park_HR'] - 100):.0f}% {'above' if m['park_HR'] > 100 else 'below'} in home runs "
            f"(home run margin of error about {m['park_HR_se']:.0f} points).")

    views = {
        "BABIP allowed": "Share of balls in play that fall for hits against each staff. The line is the "
                         "league rate and lower is better. It blends defense, park and luck.",
        "ERA vs FIP": "Each dot is a pitcher with 20 or more innings. Above the dashed line, ERA is worse "
                      "than strikeouts, walks and homers predict. Below it, better.",
        "Park effect": "Home wOBA as a percent of road wOBA. Above 100 favors hitters at home. "
                       "A rough park factor, since it also reflects each roster.",
        "Team ERA": "Earned runs per nine innings for each staff. The line is the league rate.",
    }
    view = st.radio("Chart", list(views), horizontal=True, key="team_chart")
    chart_col, note_col = st.columns([3, 2])
    fig = None
    with chart_col:
        if view == "BABIP allowed":
            fig = team_bars(frame, "def_BABIP", "BABIP allowed, by team", ".3f", base["pit_BABIP"],
                            highlight=team, sort_ascending=True,
                            xlabel="Lower is better. Line is the league rate.")
        elif view == "ERA vs FIP":
            qualified = pit[pit["INN"] >= 20] if pit is not None and not pit.empty else None
            if qualified is not None and len(qualified) >= 3:
                fig = era_fip_chart(qualified, title=f"{team}, ERA against FIP")
            else:
                st.info("Not enough pitchers with 20 or more innings.")
        elif view == "Park effect":
            fig = team_bars(frame, "park_wOBA", "Home offense vs road offense (100 is neutral)", ".0f",
                            100, highlight=team, sort_ascending=False,
                            xlabel="Home wOBA as a percent of road wOBA")
        else:
            fig = team_bars(frame, "ERA", "Team ERA", ".2f", base["ERA"], highlight=team,
                            sort_ascending=True, xlabel="Lower is better. Line is the league rate.")
        if fig is not None:
            st.pyplot(fig)
            plt.close(fig)
    with note_col:
        st.caption(views[view])


# -------------------
# Page
# -------------------
st.title("ALPB Player Stats")
st.markdown(STYLE, unsafe_allow_html=True)

try:
    teams_df = get_league_teams()
except UpstreamError as e:
    stop_on_upstream_error(e)

if teams_df.empty:
    st.warning("The league returned no teams.")
    st.stop()

# ?warm=1 loads every team into the server's cache so the first real visitor
# never waits on a cold team. The cache lives in the server process, so a
# separate script cannot do this. Entries expire with the aggregate TTL.
if st.query_params.get("warm") == "1":
    try:
        with st.spinner("Warming the cache for every team..."):
            for _guid in teams_df["team_guid"]:
                get_team_stats_aggregated(_guid, get_team_players(_guid))
        st.success(f"Warmed {len(teams_df)} teams.")
    except UpstreamError as e:
        stop_on_upstream_error(e)

pick_col, _spacer = st.columns([2, 3])
with pick_col:
    selected_team = st.selectbox("Team", sorted(teams_df["TEAM"].dropna().unique()))
team_guid = teams_df[teams_df["TEAM"] == selected_team].iloc[0]["team_guid"]

try:
    with st.spinner(f"Loading {selected_team} stats. A team's first load can take a few seconds."):
        players_df = get_team_players(team_guid)
        batting_df, pitching_df = get_team_stats_aggregated(team_guid, players_df)
except UpstreamError as e:
    stop_on_upstream_error(e)

report = load_league_report()
batting_df, pitching_df, _base = enrich(batting_df, pitching_df, report)

st.caption(f"{len(batting_df)} hitters and {len(pitching_df)} pitchers with season stats. "
           "Click any column header to sort. Hover a header for what the stat means.")

hitters_tab, pitchers_tab, team_tab = st.tabs(["Hitters", "Pitchers", "Team"])

with hitters_tab:
    render_section(
        batting_df, title="Hitters", all_cols=HITTER_COLS, views=HITTER_VIEWS,
        sort_col="PA", note="Sorted by plate appearances.",
        empty_msg="No batting data available.", view_key="hitter_view",
        picker_key="hitter_cols", pdf_title="Batting Season Stats",
        pdf_prefix="batting_season", pdf_key="pdf_batting_season",
        team=selected_team, kind="hitter", report=report, teams_df=teams_df)

with pitchers_tab:
    render_section(
        pitching_df, title="Pitchers", all_cols=PITCHER_COLS, views=PITCHER_VIEWS,
        sort_col="BF", note="Sorted by batters faced.",
        empty_msg="No pitching data available.", view_key="pitcher_view",
        picker_key="pitcher_cols", pdf_title="Pitcher Season Stats",
        pdf_prefix="pitcher_season", pdf_key="pdf_pitcher_season",
        team=selected_team, kind="pitcher", report=report, teams_df=teams_df)

with team_tab:
    render_team_tab(selected_team, pitching_df, report)
