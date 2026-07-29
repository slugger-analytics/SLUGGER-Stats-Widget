
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

def fetch(endpoint, params=None):
    url = f"{BASE_URL}/{endpoint}"
    try:
        resp = requests.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Error fetching {url}: {e}")
        return {}

@st.cache_data
def get_league_teams():
    data = fetch(f"public/leagues/{LEAGUE_GUID}/teams")
    if not data:
        return pd.DataFrame()
    teams = data if isinstance(data, list) else data.get("items", data.get("data", []))
    df = pd.DataFrame(teams)
    df = df.rename(columns={"guid": "team_guid", "name": "TEAM"})
    return df

@st.cache_data
def get_team_players(team_guid):
    data = fetch(f"public/teams/{team_guid}/players")
    if not data:
        return pd.DataFrame()
    players = data if isinstance(data, list) else data.get("items", data.get("data", []))
    df = pd.DataFrame(players)
    df = df.rename(columns={"guid": "player_guid", "name": "PLAYER"})
    return df

@st.cache_data
def get_player_stats(player_guid):
    data = fetch("player-stats", params={"playerId": player_guid})
    if not data:
        return pd.DataFrame()
    rows = data if isinstance(data, list) else data.get("items", data.get("data", []))
    return pd.DataFrame(rows)

def parse_player_stats(stats_df):
    """
    Extract the stats from the nested iScore response into flat dicts
    for batting, pitching, and fielding.
    """
    if stats_df.empty:
        return {}, {}, {}

    raw_stats = stats_df.iloc[0]["stats"]  # dict keyed by season GUID(s)

    # Merge across all seasons (usually just one active season)
    batting_overall = {}
    pitching_overall = {}
    fielding_overall = {}

    for season_guid, season_data in raw_stats.items():
        # BATTING
        b = season_data.get("batting", {}).get("overall", {})
        rates = b.pop("RATES", {})
        batting_overall.update(b)
        batting_overall.update(rates)

        # PITCHING
        p = season_data.get("pitching", {}).get("overall", {})
        rates = p.pop("RATES", {})
        pitching_overall.update(p)
        pitching_overall.update(rates)

        # FIELDING
        f = season_data.get("fielding", {}).get("overall", {})
        rates = f.pop("RATES", {})
        fielding_overall.update(f)
        fielding_overall.update(rates)

    return batting_overall, pitching_overall, fielding_overall

@st.cache_data
def get_team_stats_aggregated(team_guid, players_df):
    """Fetch stats for every player on the team and build batting + pitching tables."""
    batting_rows = []
    pitching_rows = []

    for _, player in players_df.iterrows():
        player_guid = player["player_guid"]
        name = player["PLAYER"]
        throws = player.get("throwsHand", "")
        bats = player.get("bats", "")

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

def hot_cold_label(val, pct, reverse=False):
    if pd.isna(pct):
        return str(val)
    if reverse:
        if pct >= 75:
            return f"🧊 {val}"
        elif pct <= 25:
            return f"🔥 {val}"
    else:
        if pct >= 75:
            return f"🔥 {val}"
        elif pct <= 25:
            return f"🧊 {val}"
    return str(val)



st.title("ALPB Player Stats")

teams_df = get_league_teams()
if teams_df.empty:
    st.warning("Could not load teams.")
    st.stop()

selected_team = st.selectbox("Select a Team", sorted(teams_df["TEAM"].dropna().unique()))
team_guid = teams_df[teams_df["TEAM"] == selected_team].iloc[0]["team_guid"]

players_df = get_team_players(team_guid)
batting_df, pitching_df = get_team_stats_aggregated(team_guid, players_df)

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