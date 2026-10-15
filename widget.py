import streamlit as st
import pandas as pd
import requests
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import os
from io import BytesIO
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from stats_utils import select_season_rows

st.set_page_config(page_title="ALPB Player Stats", layout="wide")


# -------------------
# Column layout
# -------------------
# One fixed order for every table, following the usual box score convention.
# Who the player is first, then volume, then counting stats, then rates.
HITTER_COLS = ["PLAYER", "BATS", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI",
               "BB", "SO", "HBP", "SB", "AVG", "OBP", "SLG", "OPS",
               "ISO", "BB%", "K%"]
PITCHER_COLS = ["PLAYER", "THROWS", "IP", "BF", "NP", "H", "R", "ER", "HR",
                "BB", "SO", "ERA", "WHIP", "K9", "BB9", "K/BB"]

# Views group stats the way scouting reports do, so each one answers a single
# question. Each entry is (what it answers, columns). The first view is the default.
HITTER_VIEWS = {
    "Traditional": (
        "The classic box score line.",
        ["PLAYER", "BATS", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI",
         "BB", "SO", "SB"],
    ),
    "Slash Line": (
        "AVG / OBP / SLG / OPS, the one-glance summary of a hitter.",
        ["PLAYER", "BATS", "PA", "AVG", "OBP", "SLG", "OPS"],
    ),
    "Power": (
        "Extra-base production. ISO is SLG minus AVG.",
        ["PLAYER", "PA", "H", "2B", "3B", "HR", "RBI", "SLG", "ISO"],
    ),
    "Discipline": (
        "Plate approach. BB% and K% are per plate appearance.",
        ["PLAYER", "PA", "BB", "SO", "HBP", "BB%", "K%", "OBP"],
    ),
}
PITCHER_VIEWS = {
    "Traditional": (
        "The classic pitching line.",
        ["PLAYER", "THROWS", "IP", "H", "R", "ER", "HR", "BB", "SO",
         "ERA", "WHIP"],
    ),
    "Rates": (
        "Per-inning effectiveness. K/BB is strikeouts per walk.",
        ["PLAYER", "THROWS", "IP", "ERA", "WHIP", "K9", "BB9", "K/BB"],
    ),
    "Workload": (
        "How much each arm has been used.",
        ["PLAYER", "THROWS", "IP", "BF", "NP"],
    ),
}

# Decimal places per stat, shared by the on-screen tables and the PDF so a
# stat always looks the same everywhere (ERA 5.90, never 5.9).
DECIMALS = {"AVG": 3, "OBP": 3, "SLG": 3, "OPS": 3, "ISO": 3,
            "ERA": 2, "WHIP": 2, "K9": 2, "BB9": 2, "K/BB": 2,
            "BB%": 1, "K%": 1, "IP": 1}

HELP = {
    "PA": "Plate appearances", "AB": "At bats", "R": "Runs", "H": "Hits",
    "2B": "Doubles", "3B": "Triples", "HR": "Home runs", "RBI": "Runs batted in",
    "BB": "Walks", "SO": "Strikeouts", "HBP": "Hit by pitch", "SB": "Stolen bases",
    "AVG": "Batting average", "OBP": "On-base percentage",
    "SLG": "Slugging percentage", "OPS": "On-base plus slugging",
    "ISO": "Isolated power, SLG minus AVG",
    "BB%": "Walks per plate appearance, as a percent",
    "K%": "Strikeouts per plate appearance, as a percent",
    "IP": "Innings pitched", "BF": "Batters faced", "NP": "Pitches thrown",
    "ER": "Earned runs", "ERA": "Earned run average",
    "WHIP": "Walks plus hits per inning pitched",
    "K9": "Strikeouts per nine innings", "BB9": "Walks per nine innings",
    "K/BB": "Strikeouts per walk, blank when there are no walks",
}


def format_cell(col, value):
    """One display rule for every cell, used by the PDF."""
    if pd.isna(value):
        return "-"
    if col in DECIMALS:
        return f"{float(value):.{DECIMALS[col]}f}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# -------------------
# PDF Generation
# -------------------
def generate_pdf(df, title, subtitle, selected_cols):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(LETTER),
        leftMargin=24,
        rightMargin=24,
        topMargin=24,
        bottomMargin=24
    )

    elements = []
    styles = getSampleStyleSheet()

    custom_title_style = ParagraphStyle(
        name="CustomTitle",
        parent=styles["Title"],
        textColor=colors.HexColor("#000c66"),
        fontSize=14,
        alignment=1
    )

    subtitle_style = ParagraphStyle(
        name="SubtitleStyle",
        parent=styles["Normal"],
        textColor=colors.HexColor("#c62127"),
        fontSize=9,
        alignment=1
    )

    date_style = ParagraphStyle(
        name="DateStyle",
        parent=styles["Normal"],
        textColor=colors.HexColor("#000c66"),
        fontSize=7,
        alignment=1
    )

    now = datetime.now(ZoneInfo("America/New_York"))
    elements.append(Paragraph(now.strftime("Report Date: %B %d, %Y at %I:%M %p"), date_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(title, custom_title_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(subtitle, subtitle_style))
    elements.append(Spacer(1, 14))

    display_df = df[selected_cols].copy()
    cleaned_data = [
        [format_cell(col, cell) for col, cell in zip(selected_cols, row)]
        for row in display_df.values.tolist()
    ]
    data = [display_df.columns.tolist()] + cleaned_data

    # Name and hand columns get fixed room, the stat columns share the rest.
    col_count = len(selected_cols)
    fixed = {"PLAYER": 120, "BATS": 40, "THROWS": 40}
    fixed_total = sum(fixed[c] for c in selected_cols if c in fixed)
    stat_count = col_count - sum(1 for c in selected_cols if c in fixed)
    stat_width = (720 - fixed_total) / stat_count if stat_count else 0
    col_widths = [fixed.get(c, stat_width) for c in selected_cols]

    body_size = 7 if col_count > 14 else 8

    table = Table(data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0072eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), body_size),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef3fb")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def pdf_filename(prefix):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}.pdf"


BASE_URL = "https://api.microservices.iscoresports.com/api"
load_dotenv()
LEAGUE_GUID = os.getenv("LEAGUE_GUID")
SEASON_GUID = os.getenv("SEASON_GUID")
HEADERS = {"Content-Type": "application/json"}


# iScore is occasionally flaky for a second or two. Caching the flake is not
# survivable, so every fetch raises on failure. st.cache_data does not memoize
# an exception, which means the next rerun re-fetches and the widget self-heals.
class UpstreamError(RuntimeError):
    """iScore could not be reached, or answered with an error status."""


# Without this a single hung connection holds a Streamlit script run open forever.
FETCH_TIMEOUT = (5, 20)


def fetch(endpoint, params=None):
    url = f"{BASE_URL}/{endpoint}"
    try:
        resp = requests.get(url, headers=HEADERS, params=params,
                            timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise UpstreamError(f"Error fetching {url}: {e}") from e


# Cache TTLs (seconds). get_player_stats is held strictly SHORTER than
# get_team_stats_aggregated so an aggregate rebuild re-pulls live data.
@st.cache_data(ttl=3600)
def get_league_teams():
    data = fetch(f"public/leagues/{LEAGUE_GUID}/teams")
    if not data:
        return pd.DataFrame()
    teams = data if isinstance(data, list) else data.get("items", data.get("data", []))
    df = pd.DataFrame(teams)
    df = df.rename(columns={"guid": "team_guid", "name": "TEAM"})
    return df


@st.cache_data(ttl=900)
def get_team_players(team_guid):
    data = fetch(f"public/teams/{team_guid}/players")
    if not data:
        return pd.DataFrame()
    players = data if isinstance(data, list) else data.get("items", data.get("data", []))
    df = pd.DataFrame(players)
    df = df.rename(columns={"guid": "player_guid", "name": "PLAYER"})
    return df


@st.cache_data(ttl=900)
def get_player_stats(player_guid):
    data = fetch("player-stats", params={"playerId": player_guid})
    if not data:
        return pd.DataFrame()
    rows = data if isinstance(data, list) else data.get("items", data.get("data", []))
    return pd.DataFrame(rows)


@st.cache_data(ttl=1800)
def get_team_stats_aggregated(team_guid, players_df):
    """Fetch stats for every player on the team and build batting + pitching tables."""
    batting_rows = []
    pitching_rows = []

    for _, player in players_df.iterrows():
        player_guid = player["player_guid"]
        name = player["PLAYER"]
        throws = player.get("throwsHand", "")
        bats = player.get("bats", "")

        # A failed stats call raises, so a short table is never cached as authoritative.
        stats_df = get_player_stats(player_guid)
        if stats_df.empty:
            continue

        raw_stats = stats_df.iloc[0]["stats"]

        for season_guid, season_data in select_season_rows(raw_stats, SEASON_GUID):
            b = season_data.get("batting", {}).get("overall", {})
            if b.get("PA", 0) > 0:
                r = b.get("RATES", {})
                batting_rows.append({
                    "PLAYER": name,
                    "BATS":   bats,
                    "PA":  b.get("PA"),  "AB":  b.get("AB"),
                    "H":   b.get("H"),   "2B":  b.get("2B"),
                    "3B":  b.get("3B"),  "HR":  b.get("HR"),
                    "R":   b.get("R"),   "RBI": b.get("RBI"),
                    "BB":  b.get("BB"),  "SO":  b.get("SO"),
                    "HBP": b.get("HBP"), "SB":  season_data.get("running", {}).get("overall", {}).get("SB", 0),
                    "AVG": round(r.get("AVG", 0), 3),
                    "OBP": round(r.get("OBP", 0), 3),
                    "SLG": round(r.get("SLG", 0), 3),
                    "OPS": round(r.get("OPS", 0), 3),
                })

            p = season_data.get("pitching", {}).get("overall", {})
            if p.get("BF", 0) > 0:
                r = p.get("RATES", {})
                outs = p.get("OUTS_PITCHED", 0)
                pitching_rows.append({
                    "PLAYER":  name,
                    "THROWS":  throws,
                    # Stored as a number (133.1 means 133 and one third) so clicking
                    # the IP header sorts 133.1 above 9.1, which a string would not.
                    "IP":   float(f"{outs // 3}.{outs % 3}"),
                    "BF":   p.get("BF"),    "H":  p.get("H"),
                    "R":    p.get("R"),     "ER": p.get("ER"),
                    "BB":   p.get("BB"),    "SO": p.get("SO"),
                    "HR":   p.get("HR"),    "NP": p.get("PITCHES"),
                    "ERA":  round(r.get("ERA",  0), 2),
                    "WHIP": round(r.get("WHIP", 0), 2),
                    "K9":   round(r.get("K9",   0), 2),
                    "BB9":  round(r.get("BB9",  0), 2),
                })

    batting_df = pd.DataFrame(batting_rows).drop_duplicates()
    pitching_df = pd.DataFrame(pitching_rows).drop_duplicates()

    return batting_df, pitching_df


def stop_on_upstream_error(error):
    """Report an outage as a live, retryable condition rather than a dead page."""
    st.warning("Couldn't reach the league stats feed just now.")
    st.caption(str(error))
    st.button("Try again")
    st.stop()


# -------------------
# Derived stats
# -------------------
def add_hitter_metrics(df):
    """ISO, BB% and K% are derived from columns iScore already gives us."""
    if df.empty:
        return df
    df = df.copy()
    pa = pd.to_numeric(df["PA"], errors="coerce")
    df["ISO"] = (pd.to_numeric(df["SLG"], errors="coerce")
                 - pd.to_numeric(df["AVG"], errors="coerce")).round(3)
    df["BB%"] = (100 * pd.to_numeric(df["BB"], errors="coerce") / pa).round(1)
    df["K%"] = (100 * pd.to_numeric(df["SO"], errors="coerce") / pa).round(1)
    return df


def add_pitcher_metrics(df):
    """K/BB is undefined with zero walks, so it is left blank rather than infinite."""
    if df.empty:
        return df
    df = df.copy()
    so = pd.to_numeric(df["SO"], errors="coerce")
    bb = pd.to_numeric(df["BB"], errors="coerce")
    df["K/BB"] = (so / bb.where(bb > 0)).round(2)
    return df


# -------------------
# Rendering
# -------------------
def column_config_for(columns):
    """The same formatting rules for every table, so a stat looks the same everywhere."""
    config = {}
    for col in columns:
        if col == "PLAYER":
            config[col] = st.column_config.TextColumn("PLAYER", pinned=True, width="medium")
        elif col in ("BATS", "THROWS"):
            config[col] = st.column_config.TextColumn(col, width="small")
        elif col in DECIMALS:
            config[col] = st.column_config.NumberColumn(
                col, format=f"%.{DECIMALS[col]}f", help=HELP.get(col))
        else:
            config[col] = st.column_config.NumberColumn(col, help=HELP.get(col))
    return config


def render_section(df, *, title, all_cols, views, sort_col, note, empty_msg,
                   view_key, picker_key, pdf_title, pdf_prefix, pdf_key, team):
    """A heading, a row of views, one table, and a PDF of exactly that table.

    Views are never empty. Only Custom can be, and an empty selection must never
    reach generate_pdf, because download_button builds its payload eagerly on every
    rerun and reportlab raises on a 0-column table, which would take the rest of
    the page down with it.
    """
    st.subheader(title)

    if df.empty:
        st.info(empty_msg)
        return

    # Regulars first, like a lineup card (plate appearances or batters faced).
    df = df.sort_values(sort_col, ascending=False, kind="stable")
    available = [c for c in all_cols if c in df.columns]

    names = list(views) + ["All", "Custom"]
    view = st.segmented_control("View", names, default=names[0], key=view_key) or names[0]

    if view == "Custom":
        description = "Pick any stats. They always appear in the standard order."
        picked = st.multiselect(
            "Select stats to display",
            options=available,
            default=[c for c in views[names[0]][1] if c in available],
            key=picker_key,
        )
        shown = [c for c in available if c in picked]
    elif view == "All":
        description = "Every available stat."
        shown = available
    else:
        description, cols = views[view]
        shown = [c for c in cols if c in available]

    st.caption(f"{description} {note}")
    st.dataframe(
        df[shown],
        column_config=column_config_for(shown),
        width="stretch",
        height="content",
        hide_index=True,
    )

    if shown:
        st.download_button(
            label="🖨️ Download PDF",
            data=generate_pdf(
                df=df,
                title=pdf_title,
                subtitle=f"Team: {team}",
                selected_cols=shown,
            ),
            file_name=pdf_filename(pdf_prefix),
            mime="application/pdf",
            key=pdf_key,
        )
    else:
        st.caption("Pick at least one column to export a PDF.")


# -------------------
# Page
# -------------------
st.title("ALPB Player Stats")

try:
    teams_df = get_league_teams()
except UpstreamError as e:
    stop_on_upstream_error(e)

if teams_df.empty:
    st.warning("The league returned no teams.")
    st.stop()

pick_col, _spacer = st.columns([2, 3])
with pick_col:
    selected_team = st.selectbox("Team", sorted(teams_df["TEAM"].dropna().unique()))
team_guid = teams_df[teams_df["TEAM"] == selected_team].iloc[0]["team_guid"]

try:
    players_df = get_team_players(team_guid)
    batting_df, pitching_df = get_team_stats_aggregated(team_guid, players_df)
except UpstreamError as e:
    stop_on_upstream_error(e)

batting_df = add_hitter_metrics(batting_df)
pitching_df = add_pitcher_metrics(pitching_df)

st.caption(f"{len(batting_df)} hitters and {len(pitching_df)} pitchers with season stats. "
           "Click any column header to sort. Hover a header for what the stat means.")

render_section(
    batting_df,
    title="Hitters",
    all_cols=HITTER_COLS,
    views=HITTER_VIEWS,
    sort_col="PA",
    note="Sorted by plate appearances.",
    empty_msg="No batting data available.",
    view_key="hitter_view",
    picker_key="hitter_cols",
    pdf_title="Batting Season Stats",
    pdf_prefix="batting_season",
    pdf_key="pdf_batting_season",
    team=selected_team,
)

st.divider()

render_section(
    pitching_df,
    title="Pitchers",
    all_cols=PITCHER_COLS,
    views=PITCHER_VIEWS,
    sort_col="BF",
    note="Sorted by batters faced.",
    empty_msg="No pitching data available.",
    view_key="pitcher_view",
    picker_key="pitcher_cols",
    pdf_title="Pitcher Season Stats",
    pdf_prefix="pitcher_season",
    pdf_key="pdf_pitcher_season",
    team=selected_team,
)
