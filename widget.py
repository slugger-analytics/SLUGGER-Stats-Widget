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
        .drop(columns=["is_pitcher", "is_hitter", "PITCH HAND"], errors="ignore")
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

    merged = game_info_df.merge(games_df, on="GAME_ID", how="left")

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
    pa_df = (
        df.sort_values("pitch_of_pa")
        .groupby(["game_id", "BATTER", "inning", "pa_of_inning"], as_index=False)
        .last()
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
    pa_df = (
        df.sort_values("pitch_of_pa")
        .groupby(["game_id", "BATTER", "inning", "pa_of_inning"], as_index=False)
        .last()
    )

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

    season_df["AVG"] = (season_df["H"] / season_df["AB"]).round(3)
    season_df["OBP"] = ((season_df["H"] + season_df["BB"] + season_df["HBP"]) / (season_df["AB"] + season_df["BB"] + season_df["HBP"])).round(3)
    season_df["SLG"] = ((season_df["singles"] + 2 * season_df["doubles"] + 3 * season_df["triples"] + 4 * season_df["HR"]) / season_df["AB"]).round(3)
    season_df["OPS"] = (season_df["OBP"] + season_df["SLG"]).round(3)
    season_df["MAX_EV"] = season_df["MAX_EV"].round(1)
    season_df = season_df.drop(columns=["singles", "doubles", "triples"])

    return season_df


def compute_hitter_rate_stats(df):
    df = df.copy()
    df["AVG"] = (df["H"] / df["AB"]).round(3)
    df["OBP"] = ((df["H"] + df["BB"] + df["HBP"]) / (df["AB"] + df["BB"] + df["HBP"])).round(3)
    df["SLG"] = ((df["singles"] + 2 * df["doubles"] + 3 * df["triples"] + 4 * df["HR"]) / df["AB"]).round(3)
    df["OPS"] = (df["OBP"] + df["SLG"]).round(3)
    df["MAX_EV"] = df["MAX_EV"].round(1)
    df["AVG_EV"] = df["AVG_EV"].round(1)
    df = df.drop(columns=["singles", "doubles", "triples"])
    return df


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


# -----------------------
# Compute rolling stat percentiles (last N games)
# -----------------------
def compute_rolling_percentiles(df, group_col, stat, pct_name, reverse=False, window=5):
    df = df.copy().sort_values("DATE")
    last_n = (
        df.groupby(group_col, group_keys=False)
        .tail(window)
        .copy()
    )
    last_n[pct_name] = last_n[stat].rank(
        pct=True,
        ascending=not reverse
    ) * 100

    df = df.merge(
        last_n[[group_col, "GAME_ID", pct_name]],
        on=[group_col, "GAME_ID"],
        how="left"
    )
    return df


# -----------------------
# Apply hot/cold labels to a df given a stat config
# -----------------------
def apply_hot_cold_labels(df, stat_config):
    """
    stat_config: dict of { stat_col: (percentile_col, reverse) }
    Applies hot_cold_label in-place and drops percentile columns.
    """
    df = df.copy()
    for stat, (pct_col, reverse) in stat_config.items():
        if stat in df.columns and pct_col in df.columns:
            df[stat] = df.apply(
                lambda row, s=stat, p=pct_col, r=reverse: hot_cold_label(row[s], row[p], r),
                axis=1
            )
    df = df.drop(columns=[v[0] for v in stat_config.values()], errors="ignore")
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
        filtered_games = enriched_games[enriched_games["NP"] > 0].copy()

    # -----------------------
    # All Pitchers: season stats with hot/cold
    # -----------------------
    if selected_pitcher == "All Pitchers":
        season_stats = get_pitcher_season_stats(pitches_throws)

        pitch_hand_lookup = filtered_pitchers[["PLAYER", "PITCH HAND"]].rename(columns={"PLAYER": "PITCHER"})
        season_stats = season_stats.merge(pitch_hand_lookup, on="PITCHER", how="left").copy()

        season_stats["MV"] = season_stats["MV"].apply(lambda x: int(round(x)) if pd.notna(x) else x)
        season_stats["BB"] = season_stats["BB"].apply(lambda x: int(round(x)) if pd.notna(x) else x)
        season_stats["MV_PERCENTILE"] = season_stats["MV"].rank(pct=True) * 100
        season_stats["BB_PERCENTILE"] = season_stats["BB"].rank(pct=True, ascending=False) * 100
        season_stats["HR_PERCENTILE"] = season_stats["HR"].rank(pct=True, ascending=False) * 100
        season_stats["R_PERCENTILE"] = season_stats["R"].rank(pct=True, ascending=False) * 100
        season_stats["H_PERCENTILE"] = season_stats["H"].rank(pct=True, ascending=False) * 100
        season_stats["SO_PERCENTILE"] = season_stats["SO"].rank(pct=True) * 100

        pitcher_stat_config = {
            "MV": ("MV_PERCENTILE", False),
            "BB": ("BB_PERCENTILE", True),
            "HR": ("HR_PERCENTILE", True),
            "R":  ("R_PERCENTILE",  True),
            "H":  ("H_PERCENTILE",  True),
            "SO": ("SO_PERCENTILE", False),
        }


        allowed_cols = ["PITCHER", "PITCH HAND", "G", "IP", "NP", "H", "R", "HR", "BB", "SO", "MV"]
        default_cols = ["PITCHER", "PITCH HAND", "G", "IP", "H", "R", "HR", "BB", "SO", "MV"]
        selected_columns = st.multiselect("Select stats to display", options=allowed_cols, default=default_cols)
        
        hot_cold_stats = st.multiselect(
            "🔥🧊 Show Hot/Cold labels for:",
            options=list(pitcher_stat_config.keys()),
            default=list(pitcher_stat_config.keys()),  # all on by default
            key="pitcher_season_hot_cold_stats"
        )

        filtered_config = {k: v for k, v in pitcher_stat_config.items() if k in hot_cold_stats}
        season_stats = apply_hot_cold_labels(season_stats, filtered_config)
        
        st.subheader("Pitcher's Season Stats")
        st.dataframe(
            season_stats[selected_columns].reset_index(drop=True),
            use_container_width=True,
            hide_index=True
        )

    # -----------------------
    # Individual pitcher: game log with rolling hot/cold
    # -----------------------
    else:
        pitcher_game_stat_list = [
            ("MV",  False),
            ("H",   True),
            ("HR",  True),
            ("BB",  True),
            ("SO",  False),
            ("R",   True),
        ]

        display_df = filtered_games.copy().reset_index(drop=True)

        for stat, reverse in pitcher_game_stat_list:
            display_df = compute_rolling_percentiles(
                display_df,
                group_col="PITCHER",
                stat=stat,
                pct_name=f"{stat}_PERCENTILE",
                reverse=reverse,
                window=5
        )

        pitcher_game_stat_config = {stat: (f"{stat}_PERCENTILE", reverse) for stat, reverse in pitcher_game_stat_list}
        display_df = apply_hot_cold_labels(display_df, pitcher_game_stat_config)

        allowed_cols = ["DATE", "OPPONENT", "LOCATION", "NP", "MV", "MAX_SPEED", "IP", "H", "R", "HR", "BB", "SO"]
        default_cols = ["DATE", "OPPONENT", "LOCATION", "NP", "MV", "IP", "H", "R", "HR", "BB", "SO"]
        selected_columns = st.multiselect("Select stats to display", options=allowed_cols, default=default_cols)

        hot_cold_stats = st.multiselect(
            "🔥🧊 Show Hot/Cold labels for:",
            options=list(pitcher_game_stat_config.keys()),
            default=list(pitcher_game_stat_config.keys()),  # all on by default
            key="pitcher_game_hot_cold_stats"
        )

        filtered_config = {k: v for k, v in pitcher_game_stat_config.items() if k in hot_cold_stats}
        season_stats = apply_hot_cold_labels(display_df, filtered_config)

        st.subheader(f"{selected_pitcher} Game By Game Stats")
        st.dataframe(
            display_df[selected_columns].reset_index(drop=True),
            use_container_width=True,
            hide_index=True
        )


# -----------------------
# Hitters tab
# -----------------------
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

    hitter_options = ["All Hitters"] + filtered_hitters["PLAYER"].unique().tolist()
    selected_hitter = st.selectbox("Select Hitter", hitter_options)

    if not team_atbats.empty:

        # -----------------------
        # Individual hitter: game log with rolling hot/cold
        # -----------------------
        if selected_hitter != "All Hitters":
            hitter_id = filtered_hitters[filtered_hitters["PLAYER"] == selected_hitter]["player_id"].iloc[0]
            hitter_atbats = team_atbats[team_atbats["batter_id"] == hitter_id]

            if not hitter_atbats.empty:
                game_log = get_hitter_game_stats(hitter_atbats)
                game_log = compute_hitter_rate_stats(game_log)
                game_log = game_log.rename(columns={"game_id": "GAME_ID"})

                games_df = get_all_games()
                game_ids = hitter_atbats["game_id"].dropna().unique().tolist()
                games_df = games_df[games_df["game_id"].isin(game_ids)]
                game_log = game_context(game_log, games_df, selected_team)

                hitter_game_stat_list = [
                    ("AVG", False),
                    ("OBP", False),
                    ("SLG", False),
                    ("OPS", False),
                    ("H",   False),
                    ("HR",  False),
                    ("BB",  False),
                    ("SO",  True),
                ]

                for stat, reverse in hitter_game_stat_list:
                    game_log = compute_rolling_percentiles(
                        game_log,
                        group_col="BATTER",
                        stat=stat,
                        pct_name=f"{stat}_PERCENTILE",
                        reverse=reverse,
                                window=5
                )

                hitter_game_stat_config = {stat: (f"{stat}_PERCENTILE", reverse) for stat, reverse in hitter_game_stat_list}

                allowed_cols = ["DATE", "OPPONENT", "LOCATION", "AB", "H", "HR", "BB", "SO", "HBP", "AVG", "OBP", "SLG", "OPS"]
                default_cols = ["DATE", "OPPONENT", "LOCATION", "AB", "H", "HR", "BB", "SO", "AVG", "OBP", "SLG", "OPS"]
                selected_hitter_cols = st.multiselect("Select stats to display", options=allowed_cols, default=default_cols, key="hitter_game_log_cols")

                hot_cold_stats = st.multiselect(
                    "🔥🧊 Show Hot/Cold labels for:",
                    options=list(hitter_game_stat_config.keys()),
                    default=list(hitter_game_stat_config.keys()),  # all on by default
                    key="hitter_game_hot_cold_stats"
                )

                filtered_config = {k: v for k, v in pitcher_stat_config.items() if k in hot_cold_stats}
                game_log = apply_hot_cold_labels(hitter_game_stat_config, filtered_config)

                st.subheader(f"{selected_hitter} Game By Game Stats")
                st.dataframe(
                    game_log[selected_hitter_cols].reset_index(drop=True),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.write("No game data available for this hitter")

        # -----------------------
        # All Hitters: season stats with hot/cold
        # -----------------------
        else:
            season_stats = get_hitter_season_stats(team_atbats)

            bat_hand_lookup = (
                filtered_hitters[["PLAYER", "BAT HAND"]]
                .drop_duplicates(subset="PLAYER")
                .rename(columns={"PLAYER": "BATTER"})
            )
            season_stats = season_stats.merge(bat_hand_lookup, on="BATTER", how="left")
            season_stats = season_stats.drop_duplicates(subset="BATTER")

            season_stats["AVG_PERCENTILE"] = season_stats["AVG"].rank(pct=True) * 100
            season_stats["OBP_PERCENTILE"] = season_stats["OBP"].rank(pct=True) * 100
            season_stats["SLG_PERCENTILE"] = season_stats["SLG"].rank(pct=True) * 100
            season_stats["OPS_PERCENTILE"] = season_stats["OPS"].rank(pct=True) * 100
            season_stats["H_PERCENTILE"]   = season_stats["H"].rank(pct=True) * 100
            season_stats["HR_PERCENTILE"]  = season_stats["HR"].rank(pct=True) * 100
            season_stats["BB_PERCENTILE"]  = season_stats["BB"].rank(pct=True) * 100
            season_stats["SO_PERCENTILE"]  = season_stats["SO"].rank(pct=True, ascending=False) * 100

            hitter_season_stat_config = {
                "AVG": ("AVG_PERCENTILE", False),
                "OBP": ("OBP_PERCENTILE", False),
                "SLG": ("SLG_PERCENTILE", False),
                "OPS": ("OPS_PERCENTILE", False),
                "H":   ("H_PERCENTILE",   False),
                "HR":  ("HR_PERCENTILE",  False),
                "BB":  ("BB_PERCENTILE",  False),
                "SO":  ("SO_PERCENTILE",  True),
            }

            allowed_cols = ["BATTER", "BAT HAND", "G", "AB", "H", "HR", "BB", "SO", "HBP", "AVG", "OBP", "SLG", "OPS", "MAX_EV"]
            default_cols = ["BATTER", "BAT HAND", "G", "AB", "H", "HR", "BB", "SO", "AVG", "OBP", "SLG", "OPS"]
            selected_columns = st.multiselect("Select stats to display", options=allowed_cols, default=default_cols)

            hot_cold_stats = st.multiselect(
                "🔥🧊 Show Hot/Cold labels for:",
                options=list(hitter_season_stat_config.keys()),
                default=list(hitter_season_stat_config.keys()),  # all on by default
                key="hitter_season_hot_cold_stats"
            )

            filtered_config = {k: v for k, v in hitter_season_stat_config.items() if k in hot_cold_stats}
            season_stats = apply_hot_cold_labels(season_stats, filtered_config)

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