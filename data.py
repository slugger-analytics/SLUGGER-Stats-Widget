"""iScore access, caching, and assembly of one team's tables.

Every fetch raises ``UpstreamError`` on failure. ``st.cache_data`` never
memoizes an exception, so a blip is retried on the next rerun instead of being
cached as an empty or short table.
"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

from metrics import (
    STABILIZE,
    add_fip,
    batting_row,
    league_baselines,
    pitching_row,
    shrink,
)
from stats_utils import select_season_rows

BASE_URL = "https://api.microservices.iscoresports.com/api"
HEADERS = {"Content-Type": "application/json"}
REPORT_PATH = Path(__file__).resolve().parent / "data" / "league_baselines.json"

# Without a timeout one hung connection holds a Streamlit run open forever.
FETCH_TIMEOUT = (5, 20)
# Player calls are independent and network bound. Kept modest to be polite to iScore.
MAX_WORKERS = 8


def guids():
    load_dotenv()
    return os.getenv("LEAGUE_GUID"), os.getenv("SEASON_GUID")


class UpstreamError(RuntimeError):
    """iScore could not be reached, or answered with an error status."""


def fetch(endpoint, params=None):
    url = f"{BASE_URL}/{endpoint}"
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        raise UpstreamError(f"Error fetching {url}: {e}") from e


def _items(data):
    return data if isinstance(data, list) else data.get("items", data.get("data", []))


# Cache TTLs (seconds). Player stats are held strictly SHORTER than the team
# aggregate so an aggregate rebuild re-pulls live data.
@st.cache_data(ttl=3600)
def get_league_teams():
    league, _ = guids()
    data = fetch(f"public/leagues/{league}/teams")
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(_items(data)).rename(columns={"guid": "team_guid", "name": "TEAM"})


@st.cache_data(ttl=900)
def get_team_players(team_guid):
    data = fetch(f"public/teams/{team_guid}/players")
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(_items(data)).rename(columns={"guid": "player_guid", "name": "PLAYER"})


@st.cache_data(ttl=900)
def get_player_stats(player_guid):
    data = fetch("player-stats", params={"playerId": player_guid})
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(_items(data))


def fetch_all_player_stats(player_guids):
    """Fetch every player's stats concurrently, preserving input order.

    Worker threads get the script run context attached, or Streamlit warns
    once per thread. The first UpstreamError propagates out of ``pool.map``,
    which fails the whole build and keeps a partial team out of the cache.
    """
    ctx = get_script_run_ctx()

    def _attach():
        if ctx is not None:
            add_script_run_ctx(threading.current_thread(), ctx)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS, initializer=_attach) as pool:
        return list(pool.map(get_player_stats, player_guids))


@st.cache_data(ttl=1800)
def get_team_stats_aggregated(team_guid, players_df):
    """One batting row and one pitching row per player, splits included."""
    if players_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    _, season_guid = guids()
    all_stats = fetch_all_player_stats(players_df["player_guid"].tolist())

    hit, pit = [], []
    for (_, player), stats_df in zip(players_df.iterrows(), all_stats):
        if stats_df.empty:
            continue
        raw = stats_df.iloc[0]["stats"]
        for _, season in select_season_rows(raw, season_guid):
            b = batting_row(player["PLAYER"], player.get("bats", ""), season)
            if b:
                hit.append(b)
            p = pitching_row(player["PLAYER"], player.get("throwsHand", ""), season)
            if p:
                pit.append(p)
    return pd.DataFrame(hit), pd.DataFrame(pit)


# ---------------------------------------------------------------------------
# League context
# ---------------------------------------------------------------------------
@st.cache_data(ttl=86400)
def load_league_report():
    """The precomputed league report, or None if it has not been built."""
    try:
        return json.loads(REPORT_PATH.read_text())
    except (OSError, ValueError):
        return None


def enrich(hit: pd.DataFrame, pit: pd.DataFrame, report: dict | None):
    """Add FIP and the regressed x stats, against league rates when we have them.

    Without the league report the team's own pooled rates stand in, which is
    noisier and is flagged on screen.
    """
    if report:
        base = report["base"]
    elif not hit.empty and not pit.empty:
        base = league_baselines(hit, pit)
    else:
        base = None

    if not pit.empty:
        pit = add_fip(pit, base["FIP_C"] if base else 4.0)
        if base:
            pit["xK%"] = 100 * shrink(pit["SO"], pit["BF"], base["pit_K%"], STABILIZE["pit_K%"])
            pit["xBB%"] = 100 * shrink(pit["BB"], pit["BF"], base["pit_BB%"], STABILIZE["pit_BB%"])
    if not hit.empty and base:
        hit = hit.copy()
        hit["xK%"] = 100 * shrink(hit["SO"], hit["PA"], base["hit_K%"], STABILIZE["hit_K%"])
        hit["xBB%"] = 100 * shrink(hit["BB"], hit["PA"], base["hit_BB%"], STABILIZE["hit_BB%"])
        hit["xBABIP"] = shrink(hit["_HNOHR"], hit["_BIP"].clip(lower=0),
                               base["hit_BABIP"], STABILIZE["hit_BABIP"])
    return hit, pit, base


def percentile(report: dict | None, group: str, stat: str, value, high_is_good: bool):
    """League percentile among qualified players, 100 is best. None if unknown."""
    if not report or value is None or pd.isna(value):
        return None
    table = report.get("percentiles", {}).get(group, {}).get(stat)
    if not table:
        return None
    below = sum(1 for q in table if q < float(value))
    pct = round(100 * below / len(table))
    return pct if high_is_good else 100 - pct
