"""ALPB Player Stats, a Streamlit widget in the SLUGGER project (JHU SARG).

This file is the page. Data access lives in data.py, stat math in metrics.py
and league.py, display rules in display.py, figures in charts.py, the PDF in
report_pdf.py and the research text in findings.py.
"""
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from charts import era_fip_chart, quadrant_chart, team_bars
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
from findings import render_findings
from report_pdf import generate_pdf, pdf_filename
from stats_utils import (
    HITTER_QUADRANTS,
    PITCHER_QUADRANTS,
    classify_hitters,
    classify_pitchers,
    filter_min_sample,
    hitter_actions,
    ip_to_innings,
    median_cut,
    ordinal,
    pitcher_actions,
    rank_among,
)

st.set_page_config(page_title="ALPB Player Stats", layout="wide")

STYLE = """
<style>
#MainMenu, footer, header {visibility: hidden;}
html {font-size: 14px;}
.block-container {padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1080px;}
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
# Quadrants and insights
# -------------------
def render_actions(notes):
    """List the coaching notes grouped by quadrant."""
    if not notes:
        st.caption("No players to summarize.")
        return
    seen = []
    for _, quadrant, _ in notes:
        if quadrant not in seen:
            seen.append(quadrant)
    for quadrant in seen:
        st.markdown(f"**{quadrant}**")
        for name, q, action in notes:
            if q == quadrant:
                st.markdown(f"- {name}. {action}")


def render_quadrants(df, kind, key, team, highlight=None):
    """Thresholds, a quadrant chart and rule-based insights for one table.

    The minimum sample and the cutoff lines only shape the chart and the
    insights. The table above keeps every player so nobody disappears from the
    box score. Returns the context a player card needs to judge a player the
    same way.
    """
    if kind == "hitter":
        size_label, size_max, size_default = "Minimum Plate Appearances", 250, 20
        x_col, y_col = "K%", "BB%"
        x_low_good, y_low_good = True, False
        quad_map, digits = HITTER_QUADRANTS, 1
        chart_title = "Plate Discipline"
        classify, actions, step = classify_hitters, hitter_actions, 0.5
    else:
        size_label, size_max, size_default = "Minimum Innings Pitched", 60, 5
        x_col, y_col = "K9", "BB9"
        x_low_good, y_low_good = False, True
        quad_map, digits = PITCHER_QUADRANTS, 2
        chart_title = "Strikeouts and Walks"
        classify, actions, step = classify_pitchers, pitcher_actions, 0.1

    view = df.copy()
    if kind == "pitcher":
        view["INN"] = view["IP"].map(ip_to_innings)
        size_col = "INN"
    else:
        size_col = "PA"

    with st.expander("Team Insights, Quadrants, and Thresholds", expanded=False):
        st.caption("The minimum and cutoffs apply only to the chart and notes. "
                   "The table lists every player.")
        left, right = st.columns(2)
        with left:
            minimum = st.slider(size_label, 0, size_max, size_default, key=f"{key}_min")
        with right:
            cut_mode = st.radio("Cutoff Lines", ["Team Median", "Custom"],
                                horizontal=True, key=f"{key}_cut_mode")

        sample = filter_min_sample(view, size_col, minimum)
        base = sample if not sample.empty else view
        x_cut = median_cut(base[x_col], digits)
        y_cut = median_cut(base[y_col], digits)
        if cut_mode == "Custom":
            c_left, c_right = st.columns(2)
            with c_left:
                x_cut = st.number_input(f"{x_col} Cutoff", value=float(x_cut), step=step,
                                        key=f"{key}_x_cut_{team}")
            with c_right:
                y_cut = st.number_input(f"{y_col} Cutoff", value=float(y_cut), step=step,
                                        key=f"{key}_y_cut_{team}")

        classified = None
        if sample.empty:
            st.info(f"No players meet the minimum of {minimum}. Lower the threshold.")
        else:
            hidden = len(view) - len(sample)
            if hidden:
                st.caption(f"{hidden} player(s) below the minimum are excluded from the chart and insights.")
            classified = classify(sample, x_cut, y_cut)
            fig = quadrant_chart(classified, x_col, y_col, x_cut, y_cut,
                                 x_low_good, y_low_good, x_col, y_col, quad_map,
                                 highlight=highlight, title=chart_title)
            st.pyplot(fig)
            plt.close(fig)
            st.caption("Dashed lines mark the cutoffs, and the strongest performers appear toward the upper right. "
                       "A ringed point is the player selected in the table.")
            st.markdown("**Actionable Insights**")
            render_actions(actions(classified))

    return {
        "view": view, "sample": sample, "classified": classified,
        "x_cut": x_cut, "y_cut": y_cut, "minimum": minimum, "size_col": size_col,
        "classify": classify, "actions": actions,
    }


# Stat tiles on a player card as (column, high_is_good). None means no ranking.
HITTER_TILES = [("PA", None), ("AVG", True), ("OBP", True), ("SLG", True),
                ("OPS", True), ("wOBA", True), ("K%", False), ("BB%", True)]
PITCHER_TILES = [("IP", None), ("ERA", False), ("FIP", False), ("WHIP", False),
                 ("K9", True), ("BB9", False), ("K-BB%", True)]
# League percentile tables are keyed by these names in the report.
PERCENTILE_KEY = {"BABIP_A": "BABIP_A", "K-BB%": "K-BB%"}


def render_player_card(player, ctx, kind, report):
    """One player's line, team rank, league percentile, and a note on how to use them."""
    view, sample = ctx["view"], ctx["sample"]
    all_classified = ctx["classify"](view, ctx["x_cut"], ctx["y_cut"])
    row = all_classified.loc[player.name]
    reference = ctx["classified"] if ctx["classified"] is not None else all_classified
    note = ctx["actions"](all_classified.loc[[player.name]], reference=reference)[0]

    tiles = HITTER_TILES if kind == "hitter" else PITCHER_TILES
    hand = player.get("BATS") if kind == "hitter" else player.get("THROWS")
    hand = {"R": "Right", "L": "Left", "S": "Switch", "B": "Switch"}.get(str(hand).upper(), hand)
    hand_label = "Bats" if kind == "hitter" else "Throws"

    # Rank against the qualified players plus this one, so a small sample can
    # still be placed without dragging the whole group's ranks around.
    pool = view.loc[[player.name]] if sample.empty else pd.concat(
        [sample, view.loc[[player.name]]]).loc[lambda d: ~d.index.duplicated()]

    group = "hitters" if kind == "hitter" else "pitchers"
    meta = (report or {}).get("meta", {})
    qualifier = meta.get("hit_min_pa" if kind == "hitter" else "pit_min_bf")
    opportunities = player.get("PA") if kind == "hitter" else player.get("BF")
    in_league_table = bool(report) and opportunities is not None and opportunities >= qualifier

    with st.container(border=True):
        st.markdown(f"### {player['PLAYER']}")
        st.caption(f"{hand_label} {hand}  |  {row['QUADRANT']}")
        size = row[ctx["size_col"]]
        if size < ctx["minimum"]:
            st.warning("Small sample size. Interpret these figures and rankings with caution.")

        cols = st.columns(len(tiles))
        for slot, (col, high_good) in zip(cols, tiles):
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

        st.markdown(f"**{note[1]}.** {note[2]}")
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
                       "hitter's platoon or RISP split holds up as real. See the Findings tab.")
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
                   view_key, picker_key, pdf_title, pdf_prefix, pdf_key, team, quad_kind,
                   report):
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
    available = [c for c in all_cols if c in df.columns]

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

    st.caption(f"{description} {note} Select a row to view the player card.")
    event = st.dataframe(
        df[shown], column_config=column_config_for(shown), width="stretch",
        height="content", hide_index=True, on_select="rerun",
        selection_mode="single-row", key=f"{view_key}_table_{team}")

    if shown:
        st.download_button(
            label="Download PDF",
            data=generate_pdf(df=df, title=pdf_title, subtitle=f"Team: {team}",
                              selected_cols=shown),
            file_name=pdf_filename(pdf_prefix), mime="application/pdf", key=pdf_key)
    else:
        st.caption("Pick at least one column to export a PDF.")

    rows = list(event.selection.rows) if event is not None else []
    picked = df.iloc[rows[0]] if rows and rows[0] < len(df) else None
    card_slot = st.container()
    ctx = render_quadrants(df, quad_kind, key=view_key, team=team,
                           highlight=None if picked is None else picked["PLAYER"])
    if picked is not None:
        with card_slot:
            render_player_card(picked, ctx, quad_kind, report)


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

hitters_tab, pitchers_tab, team_tab, findings_tab = st.tabs(
    ["Hitters", "Pitchers", "Team", "Findings"])

with hitters_tab:
    render_section(
        batting_df, title="Hitters", all_cols=HITTER_COLS, views=HITTER_VIEWS,
        sort_col="PA", note="Sorted by plate appearances.",
        empty_msg="No batting data available.", view_key="hitter_view",
        picker_key="hitter_cols", pdf_title="Batting Season Stats",
        pdf_prefix="batting_season", pdf_key="pdf_batting_season",
        team=selected_team, quad_kind="hitter", report=report)

with pitchers_tab:
    render_section(
        pitching_df, title="Pitchers", all_cols=PITCHER_COLS, views=PITCHER_VIEWS,
        sort_col="BF", note="Sorted by batters faced.",
        empty_msg="No pitching data available.", view_key="pitcher_view",
        picker_key="pitcher_cols", pdf_title="Pitcher Season Stats",
        pdf_prefix="pitcher_season", pdf_key="pdf_pitcher_season",
        team=selected_team, quad_kind="pitcher", report=report)

with team_tab:
    render_team_tab(selected_team, pitching_df, report)

with findings_tab:
    render_findings(report, selected_team)
