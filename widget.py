"""
Baseball Performance Widget
---------------------------
This Streamlit app pulls player statistics from the Pointstreak API for a given baseball season and displays
batting, fielding, and pitching data with filtering capabilities. The user can generate and download a PDF
report summarizing the top filtered results.

Main Features:
- Interactive UI with team/player/sort filters for batting, fielding, and pitching.
- Pulls and cleans data from Pointstreak's public API.
- Displays data tables using Streamlit and generates a stylized PDF report.
- Handles time zones and ensures report filenames are timestamped appropriately.

Dependencies:
- streamlit, pandas, requests, reportlab, zoneinfo
"""

# -------------------------
# Imports and Configuration
# -------------------------

# Core libraries

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

# -------------------
# Pointstreak API Setup
# -------------------

load_dotenv()

# Get API key from environment
if os.path.exists(".env"):
    load_dotenv()
    API_KEY = os.getenv("API_KEY")
else:
    API_KEY = st.secrets["API_KEY"]
    
BASE_URL = "https://1ywv9dczq5.execute-api.us-east-2.amazonaws.com/ALPBAPI"
HEADERS = {"x-api-key": API_KEY}
SEASON_ID = 34052

# -------------------
# API Fetch Function
# -------------------

# def fetch(endpoint):
#     url = f"{BASE_URL}/{endpoint}"
#     try:
#         response = requests.get(url, headers=HEADERS)
#         response.raise_for_status()
#         return response.json()
#     except requests.exceptions.HTTPError as e:
#         if response.status_code == 404:
#             print(f"404 Not Found: {url}")
#         else:
#             print(f"Error fetching {url}: {e}")
#         return {}


def fetch(endpoint, params=None):
    url = f"{BASE_URL}/{endpoint}"
    try:
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError:
        st.error(f"HTTP Error {response.status_code} for {url}")
        return {}
    except Exception as e:
        st.error(f"Error fetching {url}: {e}")
        return {}


# -----------------------
# Get players data
# -----------------------
@st.cache_data
def get_all_players():
    resp = fetch("players", params={"limit": 1000})
    players = resp.get("data", [])

    if not players:
        return pd.DataFrame(), pd.DataFrame()
    
    df = pd.DataFrame(players)

    df = (
        df.drop_duplicates(subset="player_id")
        .rename(columns={
            "player_name": "PLAYER",
            "team_name": "TEAM",
            "player_pitching_handedness": "PITCH HAND",
            "player_batting_handedness": "BAT HAND",
        })
    )

    pitchers_df = (
        df[df["is_pitcher"]]
        .drop(columns=["is_pitcher", "is_hitter", "BAT HAND"], errors="ignore")
    )

    hitters_df = (
        df[df["is_hitter"]]
        .drop(columns=["is_pitcher","is_hitter", "PITCH HAND"], errors="ignore")
    )

    return pitchers_df, hitters_df

# -----------------------
# Get pitches
# -----------------------
def get_pitcher_pitches(pitcher_id):
    resp = fetch("pitches", params={
        "pitcher_id": pitcher_id,
        "limit": 1000
    })
    return pd.DataFrame(resp.get("data", []))

# -----------------------
# Get ALL games
# -----------------------
def get_all_games():
    resp = fetch("games", params={"limit": 1000})
    return pd.DataFrame(resp.get("data", []))

# -----------------------
# Throw speed stats
# -----------------------
def game_pitch_speeds(pitches_df):
    if pitches_df.empty:
        return pd.DataFrame()

    df = pitches_df.dropna(subset=["throw_speed", "game_id"])

    grouped = df.groupby("game_id").agg(
        MAX_SPEED=("throw_speed", "max")
    ).reset_index()

    return grouped.rename(columns={"game_id": "GAME_ID"})
 

# -----------------------
# Game aggregation 
# -----------------------
def get_game_info(pitches_df):
    if pitches_df.empty or "game_id" not in pitches_df.columns:
        return pd.DataFrame()
        
    df = pitches_df.dropna(subset=["game_id"])
    
    game_info = df.groupby("game_id").agg(
        DATE=("date", "first"),
        TOTAL_RUNS=("runs_scored", "sum"),
        TOTAL_INNINGS=("inning", "max"),
    ).reset_index()
    
    return game_info.rename(columns={
        "game_id": "GAME_ID",
        "TOTAL_RUNS": "R",
        "TOTAL_INNINGS": "IP",
    })

# -----------------------
# Add opponent + location
# -----------------------
def game_context(game_info_df, games_df, selected_team):

    if games_df.empty:
        st.write("games_df is empty")
        return game_info_df

    if "game_id" in games_df.columns:
        games_df = games_df.rename(columns={"game_id": "GAME_ID"})
    elif "GAME_ID" not in games_df.columns:
        st.write("No game_id column found in games_df")
        st.write(games_df.columns)
        return game_info_df
    
    merged = game_info_df.merge(
        games_df,
        on="GAME_ID",
        how="left"
    )

    def get_opponent(row):
        if row["home_team_name"] == selected_team:
            return row["visiting_team_name"]
        else:
            return row["home_team_name"]

    def get_location(row):
        if row["home_team_name"] == selected_team:
            return "HOME"
        else:
            return "AWAY"

    merged["OPPONENT"] = merged.apply(get_opponent, axis=1)
    merged["LOCATION"] = merged.apply(get_location, axis=1)

    return merged


# -----------------------
# UI
# -----------------------
st.title("League Stats Testing")

pitchers_df, hitters_df = get_all_players()

all_teams = sorted(
    pd.concat([pitchers_df, hitters_df])["TEAM"].dropna().unique()
)

selected_team = st.selectbox("Select a Team", all_teams)

filtered_pitchers = pitchers_df[pitchers_df["TEAM"] == selected_team]
filtered_hitters = hitters_df[hitters_df["TEAM"] == selected_team]

tab1, tab2 = st.tabs(["Pitchers", "Hitters"])


# -----------------------
# Pitchers tab
# -----------------------
with tab1:
    st.subheader("Pitchers")
    st.dataframe(
        filtered_pitchers.drop(columns=["player_id","TEAM"], errors="ignore"),
        use_container_width=True,
        hide_index=True
    )

    selected_pitcher = st.selectbox(
        "Select Pitcher",
        filtered_pitchers["PLAYER"]
    )

    pitcher_id = filtered_pitchers[
        filtered_pitchers["PLAYER"] == selected_pitcher
    ]["player_id"].iloc[0]
    
    pitches_throws = get_pitcher_pitches(pitcher_id)
    # st.write("Pitches preview:")
    # st.write(pitches_throws.head())
    # st.write("Columns:")
    # st.write(list(pitches_throws.columns))

    #st.write("One pitch example:", pitches_throws.iloc[0].to_dict())

    # walks = pitches_throws[pitches_throws["k_or_bb"] == "Walk"]
    
    # # Home Runs
    # home_runs = pitches_throws[pitches_throws["play_result"] == "HomeRun"]
    
    # st.write("Walks for this pitcher:", len(walks))
    # st.write("Home Runs for this pitcher:", len(home_runs))
    
    if not pitches_throws.empty:

        game_ids = pitches_throws["game_id"].dropna().unique().tolist()

        games_df = get_all_games()

        games_df = games_df[games_df["game_id"].isin(game_ids)]

        #st.write("One game example:", games_df.iloc[0].to_dict())
        

        game_info_df = get_game_info(pitches_throws)
        speed_df = game_pitch_speeds(pitches_throws)

        game_info_df = game_info_df.merge(
            speed_df,
            on="GAME_ID",
            how="left"
        )

        # -----------------------
        # Compute Strike %, Ball %, Swinging Strike %
        # -----------------------
        def compute_pitch_metrics(df):
            metrics = df.groupby("game_id").agg(
                STRIKE_COUNT=("pitch_call", lambda x: sum(x.isin(["StrikeCalled", "StrikeSwinging"]))),
                BALL_COUNT=("pitch_call", lambda x: sum(x.isin(["BallCalled", "BallIntentional", "BallInDirt"]))),
                SWINGING_STRIKE=("pitch_call", lambda x: sum(x == "StrikeSwinging")),
            ).reset_index()
            return metrics

        def get_pitch_results(df):
            results = df.groupby("game_id").agg(
                NP = ("pitch_call", "count"),
                HR = ("play_result",lambda x: sum(x=="HomeRun")),
                BB = ("k_or_bb",lambda x: sum(x=="Walk")),
                SO = ("k_or_bb",lambda x: sum(x=="Strikeout")),
                H =("play_result", lambda x: sum(x.isin(["Single", "Double", "Triple", "HomeRun"])))
            ).reset_index()
            return results
        
        def get_max_velo(df):
            max_velo = df.groupby("game_id").agg(
                MV =("rel_speed", "max"),
            ).reset_index()
            return max_velo
        
        pitch_metrics_df = compute_pitch_metrics(pitches_throws)
        pitch_results_df = get_pitch_results(pitches_throws)
        game_max_velo_df = get_max_velo(pitches_throws)

        # Merge metrics into game_info_df
        game_info_df = game_info_df.merge(
            pitch_metrics_df,
            left_on="GAME_ID",
            right_on="game_id",
            how="left"
        )
        
        game_info_df = game_info_df.merge(
            pitch_results_df,
            left_on="GAME_ID",
            right_on="game_id",
            how="left"
        )
        
        game_info_df = game_info_df.merge(
            game_max_velo_df,
            left_on="GAME_ID",
            right_on="game_id",
            how="left"
        )

        enriched_games = game_context(
            game_info_df,
            games_df,
            selected_team
        )


        filtered_games = enriched_games[enriched_games["NP"] > 0]
        
        default_cols = [
            "DATE",
            "OPPONENT",
            "LOCATION",
            "NP",
            "MV",
            "IP",
            "H",
            "R",
            "HR",
            "BB",
            "SO"
        ]

        allowed_cols = [
            "DATE",
            "OPPONENT",
            "LOCATION",
            "NP",
            "MV",
            "MAX_SPEED",
            "IP",
            "H",
            "R",
            "HR",
            "BB",
            "SO"
        ]

        all_cols = list(filtered_games.columns)

        selected_columns = st.multiselect(
            "Select stats to display",
            options=allowed_cols,
            default=default_cols
        )

        clean_df = filtered_games[selected_columns]

        st.subheader(f"{selected_pitcher}'s Game Info")
        st.dataframe(clean_df, use_container_width=True, hide_index=True)
                
    else:
        st.write("No pitch data available for this pitcher.")


# -----------------------
# Hitters tab
# -----------------------
with tab2:
    st.subheader("Hitters")

    clean_hitters = filtered_hitters.drop(columns=["player_id","TEAM"], errors="ignore")

    st.dataframe(clean_hitters, use_container_width=True, hide_index=True)


# ------------------------
# Data Cleaning Functions
# ------------------------



# def clean_batting_df(df):
#     """Clean and structure batting stats DataFrame."""
#     if "teamname" in df.columns:
#         df["teamname"] = df["teamname"].apply(lambda x: x.get("$t") if isinstance(x, dict) else x)
    
#     df = df.drop(columns=[col for col in ["playerlinkid", "playerid", "firstname", "lastname"] if col in df.columns])
    
#     rename_map = {"playername": "PLAYER", "teamname": "TEAM", "jersey": "JERSEY", "position": "P"}
#     df = df.rename(columns=rename_map)
#     df.columns = [rename_map.get(col, col.upper()) for col in df.columns]
    
    
#     numeric_cols = ["AVG", "AB", "RUNS", "HITS", "HR", "RBI", "BB", "HP", "SO", "SF", "SB", "DP", "BIB", "TRIB", "OBP", "SLG"]
#     for col in numeric_cols:
#         if col in df.columns:
#             df[col] = pd.to_numeric(df[col], errors="coerce")
    
#     # Reorganizing the order of the columns
#     order = ["PLAYER", "JERSEY", "TEAM", "P", "AVG", "AB", "RUNS", "HITS", "HR", "RBI", "BB", "HP", "SO", "SF", "SB", "DP"]
#     return df[[col for col in order if col in df.columns] + [col for col in df.columns if col not in order]]

# def clean_pitching_df(df):
#     """Clean and structure pitching stats DataFrame."""
#     if "teamname" in df.columns:
#         df["teamname"] = df["teamname"].apply(lambda x: x.get("$t") if isinstance(x, dict) else x)
#     df = df.drop(columns=[col for col in ["playerlinkid", "playerid", "firstname", "lastname", "oobp", "oslg", "oavg"] if col in df.columns])
#     rename_map = {"playername": "PLAYER", "teamname": "TEAM", "jersey": "JERSEY", "games": "G"}
#     df = df.rename(columns=rename_map)
#     df.columns = [rename_map.get(col, col.upper()) for col in df.columns]
    
#     numeric_cols = ["ERA", "G", "GS", "CG", "CGL", "IP", "HITS", "RUNS", "ER", "BB", "SO", "SV", "BSV", "WINS", "LOSSES", "BF", "SHO"]
#     for col in numeric_cols:
#         if col in df.columns:
#             df[col] = pd.to_numeric(df[col], errors="coerce")
    
#     order = ["PLAYER", "JERSEY", "TEAM", "ERA", "G", "GS", "CG", "CGL", "IP", "HITS", "RUNS", "ER", "BB", "SO", "WINS", "LOSSES", "SV", "BSV"]
#     return df[[col for col in order if col in df.columns] + [col for col in df.columns if col not in order]]

# def clean_fielding_df(df):
#     """Clean and structure fielding stats DataFrame."""
#     if "teamname" in df.columns:
#         df["teamname"] = df["teamname"].apply(lambda x: x.get("$t") if isinstance(x, dict) else x)
#     df = df.drop(columns=[col for col in ["playerlinkid"] if col in df.columns])
#     rename_map = {"name": "PLAYER", "jersey": "JERSEY", "teamname": "TEAM", "position": "P"}
#     df = df.rename(columns=rename_map)
#     df.columns = [rename_map.get(col, col.upper()) for col in df.columns]
#     numeric_cols = ["FPCT", "GP", "PO", "A"]
#     for col in numeric_cols:
#         if col in df.columns:
#             df[col] = pd.to_numeric(df[col], errors="coerce")
#     order = ["PLAYER", "JERSEY", "TEAM", "P", "FPCT", "GP", "PO", "A"]
#     return df[[col for col in order if col in df.columns] + [col for col in df.columns if col not in order]]

# -----------------------
# PDF Generation Function
# -----------------------


# def generate_pdf(batting_df, fielding_df, pitching_df, batting_filters, fielding_filters, pitching_filters):
#     """
#     Generate a PDF report of the filtered data tables.

#     Args:
#         batting_df (DataFrame), fielding_df (DataFrame), pitching_df (DataFrame): Cleaned stat data.
#         batting_filters, fielding_filters, pitching_filters: Tuple of (team, player, sort) for display.

#     Returns:
#         BytesIO: In-memory PDF document stream.
#     """
#     buffer = BytesIO()
#     doc = SimpleDocTemplate(buffer, pagesize=landscape(LETTER))
#     elements = []
#     styles = getSampleStyleSheet()
#     custom_title_style = ParagraphStyle(name="CustomTitle", parent=styles['Title'], textColor=colors.HexColor("#000c66"), fontSize=14, alignment=1)
#     filter_style = ParagraphStyle(name="FilterStyle", parent=styles['Normal'], textColor=colors.HexColor("#c62127"), fontSize=8, alignment=1)
#     date_style = ParagraphStyle(name="DateStyle", parent=styles['Normal'], textColor=colors.HexColor("#000c66"), fontSize=7, alignment=1)

#     # Add header
#     if os.path.exists("WidgetHeader.png"):
#         elements.append(Image("WidgetHeader.png", width=500, height=80))
#         elements.append(Spacer(1, 12))

#     # Add current date and time
#     now = datetime.now(ZoneInfo("America/New_York"))
#     report_date = now.strftime("Report Date: %B %d, %Y at %I:%M %p")
#     elements.append(Paragraph(report_date, date_style))
#     elements.append(Spacer(1, 24))

#     # Helper function to add a table section
#     def add_title_and_table(title, df, filters):
#         team, player, sort = filters
#         elements.append(Paragraph(title, custom_title_style))
#         elements.append(Spacer(1, 6))
#         filter_text = f"Filters: Team = {team}, Player = {player}, Sort = {sort}"
#         if title.startswith("Batting") and batting_position:
#             filter_text += f", Position = {batting_position}"
#         elif title.startswith("Fielding") and fielding_position:
#             filter_text += f", Position = {fielding_position}"
#         elements.append(Paragraph(filter_text, filter_style))
#         elements.append(Spacer(1, 12))
#         data = [df.columns.tolist()] + df.values.tolist()
#         data = [[str(cell) for cell in row] for row in data]
#         table = Table(data, repeatRows=1)
#         table.setStyle(TableStyle([
#             ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0072eb")),
#             ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
#             ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
#             ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
#             ('FONTNAME', (1, 1), (-1, -1), 'Helvetica'),
#             ('FONTSIZE', (0, 0), (-1, 0), 9),     # header row
#             ('FONTSIZE', (1, 1), (-1, -1), 8),    # table body
#             ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
#             ('BOTTOMPADDING', (1, 1), (-1, -1), 6),
#             ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
#         ]))
#         elements.append(table)
#         elements.append(Spacer(1, 24))

#     add_title_and_table("Batting Stats", batting_df, batting_filters)
#     add_title_and_table("Fielding Stats", fielding_df, fielding_filters)
#     add_title_and_table("Pitching Stats", pitching_df, pitching_filters)

#     doc.build(elements)
#     buffer.seek(0)
#     return buffer


# # --------------------
# # Data Load & Cleaning
# # --------------------

# batting_data = clean_batting_df(get_batting_stats(SEASON_ID))
# pitching_data = clean_pitching_df(get_pitching_stats(SEASON_ID))
# fielding_data = clean_fielding_df(get_fielding_stats(SEASON_ID))

# # -----------------------
# # Streamlit UI Definition
# # -----------------------

# # Configure Streamlit page
# st.set_page_config(page_title="Baseball Performance Widget", layout="wide")
# PRIMARY_COLOR = "#c62127"
# SECONDARY_COLOR = "#000c66"
# TERTIARY_COLOR = "#0072eb"

# # Display app title and subtitle
# st.markdown(
#     f"""
#     <div style='background-color:{SECONDARY_COLOR}; padding:10px; border-radius:10px;'>
#     <h1 style='color:{TERTIARY_COLOR}; text-align:center;'>Baseball Performance Widget</h1>
#     <p style='color:white; text-align:center;'>Filter and View Key Player Statistics for Batting, Fielding, and Pitching</p>
#     </div>
#     """,
#     unsafe_allow_html=True
# )

# # --------------------------
# # Sidebar Filters (3 columns)
# # --------------------------

# col1, col2, col3 = st.columns(3)

# with col1:
#     st.subheader("Batting Stats")
#     batting_team = st.selectbox("Select Team (Batting)", ["All"] + sorted(batting_data["TEAM"].unique()))
#     batting_player = st.selectbox("Select Player (Batting)", ["All"] + sorted(batting_data["PLAYER"].unique()))
#     batting_position = st.selectbox("Select Position (Batting)", ["All"] + sorted(batting_data["P"].dropna().unique()))
#     batting_sort = st.selectbox("Sort By (Batting)", ["None"] + [col for col in batting_data.columns if pd.api.types.is_numeric_dtype(batting_data[col])])

# with col2:
#     st.subheader("Fielding Stats")
#     fielding_team = st.selectbox("Select Team (Fielding)", ["All"] + sorted(fielding_data["TEAM"].unique()))
#     fielding_player = st.selectbox("Select Player (Fielding)", ["All"] + sorted(fielding_data["PLAYER"].unique()))
#     fielding_position = st.selectbox("Select Position (Fielding)", ["All"] + sorted(fielding_data["P"].dropna().unique()))
#     fielding_sort = st.selectbox("Sort By (Fielding)", ["None"] + [col for col in fielding_data.columns if pd.api.types.is_numeric_dtype(fielding_data[col])])

# with col3:
#     st.subheader("Pitching Stats")
#     pitching_team = st.selectbox("Select Team (Pitching)", ["All"] + sorted(pitching_data["TEAM"].unique()))
#     pitching_player = st.selectbox("Select Player (Pitching)", ["All"] + sorted(pitching_data["PLAYER"].unique()))
#     pitching_sort = st.selectbox("Sort By (Pitching)", ["None"] + [col for col in pitching_data.columns if pd.api.types.is_numeric_dtype(pitching_data[col])])
#     st.markdown("<div style='height: 85px;'></div>", unsafe_allow_html=True)

# # --------------------
# # Filter the datasets
# # --------------------

# batting_filtered = batting_data.copy()
# if batting_team != "All":
#     batting_filtered = batting_filtered[batting_filtered["TEAM"] == batting_team]
# if batting_player != "All":
#     batting_filtered = batting_filtered[batting_filtered["PLAYER"] == batting_player]
# if batting_position != "All":
#     batting_filtered = batting_filtered[batting_filtered["P"] == batting_position]
# if batting_sort != "None":
#     batting_filtered = batting_filtered.sort_values(by=batting_sort, ascending=False)

# fielding_filtered = fielding_data.copy()
# if fielding_team != "All":
#     fielding_filtered = fielding_filtered[fielding_filtered["TEAM"] == fielding_team]
# if fielding_player != "All":
#     fielding_filtered = fielding_filtered[fielding_filtered["PLAYER"] == fielding_player]
# if fielding_position != "All":
#     fielding_filtered = fielding_filtered[fielding_filtered["P"] == fielding_position]
# if fielding_sort != "None":
#     fielding_filtered = fielding_filtered.sort_values(by=fielding_sort, ascending=False)

# pitching_filtered = pitching_data.copy()
# if pitching_team != "All":
#     pitching_filtered = pitching_filtered[pitching_filtered["TEAM"] == pitching_team]
# if pitching_player != "All":
#     pitching_filtered = pitching_filtered[pitching_filtered["PLAYER"] == pitching_player]
# if pitching_sort != "None":
#     pitching_filtered = pitching_filtered.sort_values(by=pitching_sort, ascending=False)

# # --------------------
# # Download PDF Report
# # --------------------

# now = datetime.now(ZoneInfo("America/New_York"))
# now_str = now.strftime("%Y-%m-%d_%H-%M")

# st.download_button(
#     label="🖨️ Generate and Download PDF",
#     data=generate_pdf(
#         batting_filtered, fielding_filtered, pitching_filtered,
#         batting_filters=(batting_team, batting_player, batting_sort),
#         fielding_filters=(fielding_team, fielding_player, fielding_sort),
#         pitching_filters=(pitching_team, pitching_player, pitching_sort)
#     ),
#     file_name=f"stats_report_{now_str}.pdf",
#     mime="application/pdf"
# )

# # ---------------------
# # Display Filtered Tables
# # ---------------------

# col1.dataframe(batting_filtered, use_container_width=True)
# col2.dataframe(fielding_filtered, use_container_width=True)
# col3.dataframe(pitching_filtered, use_container_width=True)
