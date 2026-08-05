
import streamlit as st
import pandas as pd
import requests
from datetime import datetime
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import LETTER, landscape
import os
from io import BytesIO
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from stats_utils import select_season_rows


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

    # -------------------
    # Header
    # -------------------
    now = datetime.now(ZoneInfo("America/New_York"))
    elements.append(Paragraph(now.strftime("Report Date: %B %d, %Y at %I:%M %p"), date_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(title, custom_title_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(subtitle, subtitle_style))
    elements.append(Spacer(1, 14))

    # -------------------
    # Clean Data (NO hot/cold logic)
    # -------------------
    display_df = df[selected_cols].copy()

    # ensure everything is string-safe for PDF
    data_rows = display_df.values.tolist()
    cleaned_data = [[str(cell) for cell in row] for row in data_rows]

    data = [display_df.columns.tolist()] + cleaned_data

    # -------------------
    # Table layout
    # -------------------
    col_count = len(selected_cols)
    col_width = 720 / col_count if col_count > 0 else 720

    table = Table(data, repeatRows=1, colWidths=[col_width] * col_count)

    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0072eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef3fb")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
    ]

    table.setStyle(TableStyle(table_style))

    elements.append(table)

    # -------------------
    # Build PDF
    # -------------------
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

# iScore is occasionally flaky for a second or two. That is survivable; caching
# the flake is not. Every fetch here feeds an @st.cache_data function, and a
# swallowed failure returning {} looks exactly like a successful empty response,
# so it used to be stored under the full TTL: one blip pinned the widget on
# "Could not load teams." for an hour after iScore had recovered, and a blip
# during an aggregate build silently dropped players from a team table that was
# then served as authoritative for 30 minutes. Raising instead means the cache
# stores nothing — st.cache_data does not memoize an exception — so the next
# rerun re-fetches and the widget self-heals.
class UpstreamError(RuntimeError):
    """iScore could not be reached, or answered with an error status."""


# Without this a single hung connection holds a Streamlit script run open
# indefinitely, and the user just sees a spinner that never resolves.
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

# Cache TTLs (seconds). The Fargate task lives for days, so an untimed cache
# freezes teams, rosters and stats until the container restarts — a player who
# signed today would never appear. get_player_stats is held strictly SHORTER
# than get_team_stats_aggregated so an aggregate rebuild re-pulls live data
# instead of re-serving its own cached per-player payloads.
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

        # A player whose stats call fails must not just vanish from the table.
        # Measured on Lancaster: two injected blips turned 26 batters into 25 and
        # 27 pitchers into 26, and the short table was then cached as the team's
        # authoritative roster for the full aggregate TTL with nothing on screen
        # saying it was incomplete. Failing the build keeps the cache empty, so a
        # rerun rebuilds it whole.
        stats_df = get_player_stats(player_guid)
        if stats_df.empty:
            continue

        raw_stats = stats_df.iloc[0]["stats"]

        # Constrain to the configured current season so junk ("DO-NOT-USE")
        # and prior seasons don't create duplicate per-player rows. When
        # SEASON_GUID is unset (e.g. local dev) this falls back to all seasons.
        for season_guid, season_data in select_season_rows(raw_stats, SEASON_GUID):
            # ── Batting ──────────────────────────────────────
            b = season_data.get("batting", {}).get("overall", {})
            if b.get("PA", 0) > 0:
                r = b.get("RATES", {})
                batting_rows.append({
                    "BATTER":   name,
                    "BAT HAND": bats,
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

            # ── Pitching ─────────────────────────────────────
            p = season_data.get("pitching", {}).get("overall", {})
            if p.get("BF", 0) > 0:
                r = p.get("RATES", {})
                outs = p.get("OUTS_PITCHED", 0)
                batting_rows_exist = any(row["BATTER"] == name for row in batting_rows)
                pitching_rows.append({
                    "PITCHER":     name,
                    "PITCH HAND":  throws,
                    "IP":   f"{outs // 3}.{outs % 3}",
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



st.title("ALPB Player Stats")

def stop_on_upstream_error(error):
    """Report an outage as a live, retryable condition rather than a dead page.

    Nothing was cached, so the retry genuinely re-fetches — unlike before, when
    the failure itself was cached and the banner outlived the outage.
    """
    st.warning("Couldn't reach the league stats feed just now.")
    st.caption(str(error))
    st.button("Try again")
    st.stop()


try:
    teams_df = get_league_teams()
except UpstreamError as e:
    stop_on_upstream_error(e)

if teams_df.empty:
    st.warning("The league returned no teams.")
    st.stop()

selected_team = st.selectbox("Select a Team", sorted(teams_df["TEAM"].dropna().unique()))
team_guid = teams_df[teams_df["TEAM"] == selected_team].iloc[0]["team_guid"]

try:
    players_df = get_team_players(team_guid)
    batting_df, pitching_df = get_team_stats_aggregated(team_guid, players_df)
except UpstreamError as e:
    stop_on_upstream_error(e)

tab1, tab2 = st.tabs(["Pitchers", "Hitters"])

# ── Tab 1: Pitchers ───────────────────────────────────────
with tab1:
    st.subheader("Pitchers")

    if pitching_df.empty:
        st.info("No pitching data available.")
    else:
        allowed_cols = [
            c for c in [
                "PITCHER","PITCH HAND","IP","NP",
                "H","R","ER","HR","BB","SO",
                "ERA","WHIP","K9","BB9"
            ]
            if c in pitching_df.columns
        ]

        default_cols = [
            c for c in [
                "PITCHER","PITCH HAND","IP",
                "H","R","ER", "HR","BB","SO",
                "ERA","WHIP"
            ]
            if c in pitching_df.columns
        ]

        selected_cols = st.multiselect(
            "Select stats to display",
            options=allowed_cols,
            default=default_cols,
            key="pitcher_cols"
        )

        st.subheader("Pitcher Season Stats")

        st.dataframe(
            pitching_df[selected_cols],
            use_container_width=True,
            hide_index=True
        )

        # download_button builds its payload EAGERLY on every rerun, so with no
        # columns selected generate_pdf would hand reportlab a 0-column table and
        # raise. That is a script-level exception: the page is replaced by a red
        # traceback, and because this tab is built first, clearing the pitcher
        # columns also took the Hitters tab down with it.
        if selected_cols:
            st.download_button(
                label="🖨️ Download PDF",
                data=generate_pdf(
                    df=pitching_df,
                    title="Pitcher Season Stats",
                    subtitle=f"Team: {selected_team}",
                    selected_cols=selected_cols,
                ),
                file_name=pdf_filename("pitcher_season"),
                mime="application/pdf",
                key="pdf_pitcher_season",
            )
        else:
            st.caption("Pick at least one column to export a PDF.")

# ── Tab 2: Hitters ────────────────────────────────────────
with tab2:
    st.subheader("Hitters")

    if batting_df.empty:
        st.info("No batting data available.")
    else:
        allowed_cols = [
            c for c in [
                "BATTER","BAT HAND","PA","AB","H",
                "2B","3B","HR","R","RBI",
                "BB","SO","HBP","SB",
                "AVG","OBP","SLG","OPS"
            ]
            if c in batting_df.columns
        ]

        default_cols = [
            c for c in [
                "BATTER","BAT HAND","AB","H",
                "HR","BB","SO",
                "AVG","OBP","SLG","OPS"
            ]
            if c in batting_df.columns
        ]

        selected_cols = st.multiselect(
            "Select stats to display",
            options=allowed_cols,
            default=default_cols,
            key="hitter_cols"
        )

        st.subheader("Hitter Season Stats")

        st.dataframe(
            batting_df[selected_cols],
            use_container_width=True,
            hide_index=True
        )

        # See the pitcher tab: an empty column selection must not crash the page.
        if selected_cols:
            st.download_button(
                label="🖨️ Download PDF",
                data=generate_pdf(
                    df=batting_df,
                    title="Batting Season Stats",
                    subtitle=f"Team: {selected_team}",
                    selected_cols=selected_cols,
                ),
                file_name=pdf_filename("batting_season"),
                mime="application/pdf",
                key="pdf_batting_season",
            )
        else:
            st.caption("Pick at least one column to export a PDF.")