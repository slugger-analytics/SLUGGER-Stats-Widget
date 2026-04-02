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
@st.cache_data(show_spinner=False)
def get_pitcher_pitches(pitcher_id):

    all_data = []
    offset = 0
    limit = 100
    max_pages = 5
    pages = 0

    while True:
        resp = fetch("pitches", params={
            "pitcher_id": pitcher_id,
            "limit": limit,
            "offset": offset
        })

        data = resp.get("data", [])

        if not data:
            break

        all_data.extend(data)

        pages += 1
        if len(data) < limit or pages >= max_pages:
            break

        offset += limit

    return pd.DataFrame(all_data)

@st.cache_data(show_spinner=False)
def get_hitter_atbats(batter_id):

    all_data = []
    offset = 0
    limit = 100
    max_pages = 5
    pages = 0

    while True:
        resp = fetch("pitches", params={
            "batter_id": batter_id,
            "limit": limit,
            "offset": offset
        })

        data = resp.get("data", [])

        if not data:
            break

        all_data.extend(data)

        pages += 1
        if len(data) < limit or pages >= max_pages:
            break

        offset += limit

    return pd.DataFrame(all_data)

@st.cache_data(show_spinner=False)
def get_team_atbats(team_hitter_ids):

    dfs = []

    for bid in team_hitter_ids:
        df = get_hitter_atbats(bid)

        if not df.empty:
            dfs.append(df)

    if dfs:
        return pd.concat(dfs, ignore_index=True)

    return pd.DataFrame()


# -----------------------
# Load all team pitches once
# -----------------------
@st.cache_data(show_spinner=False)
def get_team_pitches(team_pitcher_ids):

    dfs = []

    for pid in team_pitcher_ids:
        df = get_pitcher_pitches(pid)

        if not df.empty:
            dfs.append(df)

    if dfs:
        return pd.concat(dfs, ignore_index=True)

    return pd.DataFrame()


# -----------------------
# Compute pitcher velocity percentiles
# -----------------------
def compute_pitcher_velo_percentiles(pitches_df):

    if pitches_df.empty:
        return pd.DataFrame()

    pitcher_velo = (
        pitches_df.groupby("pitcher_id")
        .agg(MAX_VELO=("rel_speed", "max"))
        .reset_index()
    )

    pitcher_velo["VELO_PERCENTILE"] = (
        pitcher_velo["MAX_VELO"].rank(pct=True) * 100
    )

    return pitcher_velo


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

    game_info = df.groupby(["game_id", "PITCHER"]).agg(
        DATE=("date", "first"),
        TOTAL_RUNS=("runs_scored", "sum"),
        TOTAL_INNINGS=("inning", "max"),
    ).reset_index()

    return game_info.rename(columns={
        "game_id": "GAME_ID",
        "TOTAL_RUNS": "R",
        "TOTAL_INNINGS": "IP",
    })

def get_pitcher_season_stats(df):
    
    # One row per game per pitcher first (same dedup logic)
    game_df = (
        df.groupby(["game_id", "PITCHER"]).agg(
            HR=("play_result", lambda x: sum(x == "HomeRun")),
            BB=("k_or_bb", lambda x: sum(x == "Walk")),
            SO=("k_or_bb", lambda x: sum(x == "Strikeout")),
            H=("play_result", lambda x: sum(x.isin(["Single", "Double", "Triple", "HomeRun"]))),
            R=("runs_scored", "sum"),
            IP=("inning", "max"),
            NP=("pitch_call", "count"),
            MV=("rel_speed", "max"),
        ).reset_index()
    )

    # Now aggregate to season level
    season_df = game_df.groupby("PITCHER").agg(
        G=("game_id", "count"),
        IP=("IP", "sum"),
        NP=("NP", "sum"),
        H=("H", "sum"),
        R=("R", "sum"),
        HR=("HR", "sum"),
        BB=("BB", "sum"),
        SO=("SO", "sum"),
        MV=("MV", lambda x: int(round(x.max()))),
    ).reset_index()

    # Rate stats
    season_df["K/9"] = ((season_df["SO"] / season_df["IP"]) * 9).round(2)
    season_df["BB/9"] = ((season_df["BB"] / season_df["IP"]) * 9).round(2)
    season_df["HR/9"] = ((season_df["HR"] / season_df["IP"]) * 9).round(2)

    return season_df


# -----------------------
# Add opponent + location
# -----------------------
def game_context(game_info_df, games_df, selected_team):

    if games_df.empty:
        return game_info_df

    if "game_id" in games_df.columns:
        games_df = games_df.rename(columns={"game_id": "GAME_ID"})

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

def get_hitter_game_stats(df):

    # Deduplicate to one row per plate appearance (last pitch of each PA)
    pa_df = (
        df.sort_values("pitch_of_pa")
        .groupby(["game_id", "BATTER", "inning", "pa_of_inning"], as_index=False)
        .last()  # last pitch of the PA = the outcome pitch
    )

    return pa_df.groupby(["game_id", "BATTER"]).agg(
        DATE=("date", "first"),
        PA=("pa_of_inning", "count"),
        H=("play_result", lambda x: sum(x.isin(["Single", "Double", "Triple", "HomeRun"]))),
        AB=("play_result", lambda x: sum(x.isin(["Single", "Double", "Triple", "HomeRun", "Out", "Error", "FieldersChoice"]))),
        singles=("play_result", lambda x: sum(x == "Single")),
        doubles=("play_result", lambda x: sum(x == "Double")),
        triples=("play_result", lambda x: sum(x == "Triple")),
        HR=("play_result", lambda x: sum(x == "HomeRun")),
        BB=("k_or_bb", lambda x: sum(x == "Walk")),
        SO=("k_or_bb", lambda x: sum(x == "Strikeout")),
        HBP=("pitch_call", lambda x: sum(x == "HitByPitch")),
        MAX_EV=("exit_speed", "max"),
        AVG_EV=("exit_speed", "mean"),
    ).reset_index()

def get_hitter_season_stats(df):

    # Deduplicate to one row per plate appearance
    pa_df = (
        df.sort_values("pitch_of_pa")
        .groupby(["game_id", "BATTER", "inning", "pa_of_inning"], as_index=False)
        .last()
    )

    # Game level first
    game_df = pa_df.groupby(["game_id", "BATTER"]).agg(
        H=("play_result", lambda x: sum(x.isin(["Single", "Double", "Triple", "HomeRun"]))),
        AB=("play_result", lambda x: sum(x.isin(["Single", "Double", "Triple", "HomeRun", "Out", "Error", "FieldersChoice"]))),
        singles=("play_result", lambda x: sum(x == "Single")),
        doubles=("play_result", lambda x: sum(x == "Double")),
        triples=("play_result", lambda x: sum(x == "Triple")),
        HR=("play_result", lambda x: sum(x == "HomeRun")),
        BB=("k_or_bb", lambda x: sum(x == "Walk")),
        SO=("k_or_bb", lambda x: sum(x == "Strikeout")),
        HBP=("pitch_call", lambda x: sum(x == "HitByPitch")),
        MAX_EV=("exit_speed", "max"),
    ).reset_index()

    # Season level
    season_df = game_df.groupby("BATTER").agg(
        G=("game_id", "count"),
        AB=("AB", "sum"),
        H=("H", "sum"),
        singles=("singles", "sum"),
        doubles=("doubles", "sum"),
        triples=("triples", "sum"),
        HR=("HR", "sum"),
        BB=("BB", "sum"),
        SO=("SO", "sum"),
        HBP=("HBP", "sum"),
        MAX_EV=("MAX_EV", "max"),
    ).reset_index()

    # Rate stats
    season_df["AVG"] = (season_df["H"] / season_df["AB"]).round(3)
    season_df["OBP"] = ((season_df["H"] + season_df["BB"] + season_df["HBP"]) / (season_df["AB"] + season_df["BB"] + season_df["HBP"])).round(3)
    season_df["SLG"] = ((season_df["singles"] + 2*season_df["doubles"] + 3*season_df["triples"] + 4*season_df["HR"]) / season_df["AB"]).round(3)
    season_df["OPS"] = (season_df["OBP"] + season_df["SLG"]).round(3)
    season_df["MAX_EV"] = season_df["MAX_EV"].round(1)

    season_df = season_df.drop(columns=["singles", "doubles", "triples"])

    return season_df

def compute_hitter_rate_stats(df):
    df = df.copy()
    df["AVG"] = (df["H"] / df["AB"]).round(3)
    df["OBP"] = ((df["H"] + df["BB"] + df["HBP"]) / (df["AB"] + df["BB"] + df["HBP"])).round(3)
    df["SLG"] = ((df["singles"] + 2*df["doubles"] + 3*df["triples"] + 4*df["HR"]) / df["AB"]).round(3)
    df["OPS"] = (df["OBP"] + df["SLG"]).round(3)
    df["MAX_EV"] = df["MAX_EV"].round(1)
    df["AVG_EV"] = df["AVG_EV"].round(1)

    # Drop the helper columns
    df = df.drop(columns=["singles", "doubles", "triples"])

    return df


# -----------------------
# UI
# -----------------------
st.title("ALPB League Stats")

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

    pitcher_options = ["All Pitchers"] + filtered_pitchers["PLAYER"].tolist()

    selected_pitcher = st.selectbox("Select Pitcher", pitcher_options)

    pitcher_lookup = filtered_pitchers[["player_id", "PLAYER"]].rename(
        columns={"player_id": "pitcher_id", "PLAYER": "PITCHER"}
    )

    team_pitcher_ids = filtered_pitchers["player_id"].tolist()
    team_pitches = get_team_pitches(team_pitcher_ids)
    team_pitches = team_pitches.merge(pitcher_lookup, on="pitcher_id", how="left")

    pitcher_percentiles_df = compute_pitcher_velo_percentiles(team_pitches)

    # -----------------------
    # Filter pitches
    # -----------------------
    if selected_pitcher == "All Pitchers":
        pitches_throws = team_pitches
    else:
        pitcher_id = filtered_pitchers[
            filtered_pitchers["PLAYER"] == selected_pitcher
        ]["player_id"].iloc[0]

        pitches_throws = team_pitches[team_pitches["pitcher_id"] == pitcher_id]

    if not pitches_throws.empty:

        game_ids = pitches_throws["game_id"].dropna().unique().tolist()
        games_df = get_all_games()
        games_df = games_df[games_df["game_id"].isin(game_ids)]

        game_info_df = get_game_info(pitches_throws)
        speed_df = game_pitch_speeds(pitches_throws)

        game_info_df = game_info_df.merge(speed_df, on="GAME_ID", how="left")

        # -----------------------
        # Pitch metrics
        # -----------------------
        def compute_pitch_metrics(df):
            return df.groupby("game_id").agg(
                STRIKE_COUNT=("pitch_call", lambda x: sum(x.isin(["StrikeCalled", "StrikeSwinging"]))),
                BALL_COUNT=("pitch_call", lambda x: sum(x.isin(["BallCalled", "BallIntentional", "BallInDirt"]))),
                SWINGING_STRIKE=("pitch_call", lambda x: sum(x == "StrikeSwinging")),
            ).reset_index()

        def get_pitch_results(df):
            return df.groupby("game_id").agg(
                NP=("pitch_call", "count"),
                HR=("play_result", lambda x: sum(x == "HomeRun")),
                BB=("k_or_bb", lambda x: sum(x == "Walk")),
                SO=("k_or_bb", lambda x: sum(x == "Strikeout")),
                H=("play_result", lambda x: sum(x.isin(["Single", "Double", "Triple", "HomeRun"])))
            ).reset_index()

        def get_max_velo(df):
            max_velo = df.groupby("game_id").agg(
                MV=("rel_speed", "max")
            ).reset_index()
            max_velo["MV"] = max_velo["MV"].round().astype(int)
            return max_velo

        # -----------------------
        # Rolling 5-game velo percentiles per pitcher
        # -----------------------
        def compute_rolling_velo_percentiles(df):
            df = df.copy().sort_values("DATE")

            # Get each pitcher's last 5 games only
            last5_per_pitcher = (
                df.groupby("PITCHER", group_keys=False)
                .tail(5)
                .copy()
            )

            # Rank MV across ALL pitchers' last 5 games combined
            last5_per_pitcher["MV_PERCENTILE"] = (
                last5_per_pitcher["MV"].rank(pct=True) * 100
            )

            # Merge percentiles back onto the full df
            df = df.merge(
                last5_per_pitcher[["GAME_ID", "PITCHER", "MV_PERCENTILE"]],
                on=["GAME_ID", "PITCHER"],
                how="left"
            )

            return df
        
        # -----------------------
        # Rolling 5-game BB percentiles per pitcher
        # -----------------------
        def compute_rolling_BB_percentiles(df):
            df = df.copy().sort_values("DATE")

            # Get each pitcher's last 5 games only
            last5_per_pitcher = (
                df.groupby("PITCHER", group_keys=False)
                .tail(5)
                .copy()
            )

            # Rank MV across ALL pitchers' last 5 games combined
            last5_per_pitcher["BB_PERCENTILE"] = (
                last5_per_pitcher["BB"].rank(pct=True, ascending=False) * 100
            )

            # Merge percentiles back onto the full df
            df["MV_PERCENTILE"] = last5_per_pitcher["MV_PERCENTILE"]
            df["MV_PERCENTILE"] = df["MV_PERCENTILE"].fillna(pd.NA)

            return df


        # -----------------------
        # Merge all metrics
        # -----------------------
        pitch_metrics_df = compute_pitch_metrics(pitches_throws)
        pitch_results_df = get_pitch_results(pitches_throws)
        game_max_velo_df = get_max_velo(pitches_throws)

        game_info_df = (
            game_info_df
            .merge(pitch_metrics_df, left_on="GAME_ID", right_on="game_id", how="left")
            .merge(pitch_results_df, left_on="GAME_ID", right_on="game_id", how="left")
            .merge(game_max_velo_df, left_on="GAME_ID", right_on="game_id", how="left")
        )

        enriched_games = game_context(game_info_df, games_df, selected_team)
        filtered_games = enriched_games[enriched_games["NP"] > 0]

        # -----------------------
        # Game log table
        # -----------------------
        st.subheader(f"{selected_pitcher} Game Info")

    if selected_pitcher == "All Pitchers":
        season_stats = get_pitcher_season_stats(pitches_throws)

        pitch_hand_lookup = filtered_pitchers[["PLAYER", "PITCH HAND"]].rename(columns={"PLAYER": "PITCHER"})
        season_stats = season_stats.merge(pitch_hand_lookup, on="PITCHER", how="left")

        season_stats["MV"] = season_stats["MV"].apply(lambda x: int(round(x)) if pd.notna(x) else x)
        season_stats["BB"] = season_stats["BB"].apply(lambda x: int(round(x)) if pd.notna(x) else x)

        # Rank MV across all pitchers
        season_stats["MV_PERCENTILE"] = season_stats["MV"].rank(pct=True) * 100
        season_stats["BB_PERCENTILE"] = season_stats["BB"].rank(pct=True, ascending=False) * 100

        def mv_season_label(row):
            mv = row["MV"]
            pct = row["MV_PERCENTILE"]
            if pd.isna(pct):
                return str(mv)
            elif pct >= 75:
                return f"🔥 {mv}"
            elif pct <= 25:
                return f"🧊 {mv}"
            else:
                return str(mv)
            
        def bb_season_label(row):
            bb = row["BB"]
            pct = row["BB_PERCENTILE"]
            if pd.isna(pct):
                return str(bb)
            elif pct >= 75:
                return f"🔥 {bb}"
            elif pct <= 25:
                return f"🧊 {bb}"
            else:
                return str(bb)

        season_stats["MV"] = season_stats.apply(mv_season_label, axis=1)
        season_stats["BB"] = season_stats.apply(bb_season_label, axis=1)
        season_stats = season_stats.drop(columns=["MV_PERCENTILE"])

        allowed_cols = ["PITCHER", "PITCH HAND", "G", "IP", "NP", "H", "R", "HR", "BB", "SO", "MV"]
        default_cols = ["PITCHER", "PITCH HAND", "G", "IP", "H", "R", "HR", "BB", "SO", "MV"]

        selected_columns = st.multiselect("Select stats to display", options=allowed_cols, default=default_cols)

        st.dataframe(
            season_stats[selected_columns].reset_index(drop=True),
            use_container_width=True,
            hide_index=True
        )

    else:
        # individual pitcher game log
        allowed_cols = ["DATE", "OPPONENT", "LOCATION", "NP", "MV", "MAX_SPEED", "IP", "H", "R", "HR", "BB", "SO"]
        default_cols = ["DATE", "OPPONENT", "LOCATION", "NP", "MV", "IP", "H", "R", "HR", "BB", "SO"]

        selected_columns = st.multiselect("Select stats to display", options=allowed_cols, default=default_cols)

        display_df = compute_rolling_velo_percentiles(filtered_games).reset_index(drop=True)

        def mv_label(row):
            mv = row["MV"]
            pct = row["MV_PERCENTILE"]
            if pd.isna(pct):
                return str(mv)
            elif pct >= 75:
                return f"🔥 {mv}"
            elif pct <= 25:
                return f"🧊 {mv}"
            else:
                return str(mv)

        display_df["MV_DISPLAY"] = display_df.apply(mv_label, axis=1)
        display_cols = [c if c != "MV" else "MV_DISPLAY" for c in selected_columns]
        clean_df = display_df[display_cols].rename(columns={"MV_DISPLAY": "MV"})

        st.subheader(f"{selected_pitcher} Game By Game Stats")
        st.dataframe(
            clean_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "MV": st.column_config.TextColumn("MV", help="🔥 top 25% | 🧊 bottom 25% of last 5 games")
            }
        )

# -----------------------
# Hitters tab
# ------------------
with tab2:
    st.subheader("Hitters")

    hitter_lookup = (
    filtered_hitters[["player_id", "PLAYER"]]
    .drop_duplicates(subset="player_id") 
    .rename(columns={"player_id": "batter_id", "PLAYER": "BATTER"})
    )

    team_hitter_ids = filtered_hitters["player_id"].tolist()
    team_atbats = get_team_atbats(tuple(team_hitter_ids))
    team_atbats = team_atbats.merge(hitter_lookup, on="batter_id", how="left")

    if not team_atbats.empty:
        season_stats = get_hitter_season_stats(team_atbats)
        bat_hand_lookup = (
            filtered_hitters[["PLAYER", "BAT HAND"]]
            .drop_duplicates(subset="PLAYER")
            .rename(columns={"PLAYER": "BATTER"})
        )
        season_stats = season_stats.merge(bat_hand_lookup, on="BATTER", how="left")
        season_stats = season_stats.drop_duplicates(subset="BATTER")

        hitter_options = ["All Hitters"] + filtered_hitters["PLAYER"].unique().tolist()
        selected_hitter = st.selectbox("Select Hitter", hitter_options)

        if selected_hitter != "All Hitters":
            hitter_id = filtered_hitters[filtered_hitters["PLAYER"] == selected_hitter]["player_id"].iloc[0]

            hitter_atbats = team_atbats[team_atbats["batter_id"] == hitter_id]

            if not hitter_atbats.empty:
                game_log = get_hitter_game_stats(hitter_atbats)
                game_log = compute_hitter_rate_stats(game_log)

                games_df = get_all_games()

                # Opponent and location Context
                game_ids = hitter_atbats["game_id"].dropna().unique().tolist()
                games_df = games_df[games_df["game_id"].isin(game_ids)]

                game_log = game_log.rename(columns={"game_id" : "GAME_ID"})
                game_log= game_context(game_log, games_df, selected_team)

                allowed_cols = ["DATE", "OPPONENT", "LOCATION", "AB", "H", "HR", "BB", "SO", "HBP", "AVG", "OBP", "SLG", "OPS"]
                default_cols = ["DATE", "OPPONENT", "LOCATION", "AB", "H", "HR", "BB", "SO", "AVG", "OBP", "SLG", "OPS"]
                selected_hitter_cols = st.multiselect("Select stats to display", options=allowed_cols, default=default_cols, key="hitter_game_log_cols")

                st.subheader(f"{selected_hitter} Game By Game Stats")
                st.dataframe(
                    game_log[selected_hitter_cols].reset_index(drop=True),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.write("No game data available for this hitter")
                
        else:
            allowed_cols = ["BATTER", "BAT HAND", "G", "AB", "H", "HR", "BB", "SO", "HBP", "AVG", "OBP", "SLG", "OPS", "MAX_EV"]
            default_cols = ["BATTER", "BAT HAND", "G", "AB", "H", "HR", "BB", "SO", "AVG", "OBP", "SLG", "OPS"]

            selected_columns = st.multiselect("Select stats to display", options=allowed_cols, default=default_cols)

            st.subheader("Hitter's Season Stats")
            st.dataframe(
                season_stats[selected_columns].reset_index(drop=True),
                use_container_width=True,
                hide_index=True
            )

    else:
        st.write("No at-bat data available.")

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
