"""SLUGGER's Trackman API, the pitch-level feed behind the advanced stats.

iScore only knows outcomes. Swing and zone rates, exit velocity and pitch
velocity come from Trackman, through the same API the pitching widget uses.
Stat math lives in advanced.py. This module only fetches and caches.

The key and season dates are read on every call, not at import, so tests and
a changed ``.env`` take effect without restarting the process.
"""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

import advanced as adv
from data import FETCH_TIMEOUT, UpstreamError, threaded_map

DEFAULT_BASE_URL = "https://1ywv9dczq5.execute-api.us-east-2.amazonaws.com/ALPBAPI"
PAGE_SIZE = 1000
MAX_PAGES = 25


def settings():
    """``(base_url, api_key, start_date, end_date)`` from the environment.

    Trackman has no season id, so the season is a date range. It defaults to
    the current calendar year.
    """
    load_dotenv()
    year = datetime.now(ZoneInfo("America/New_York")).year
    return (os.getenv("ALPB_BASE_URL", DEFAULT_BASE_URL),
            os.getenv("ALPB_API_KEY", ""),
            os.getenv("TRACKMAN_START_DATE", f"{year}-01-01"),
            os.getenv("TRACKMAN_END_DATE", f"{year}-12-31"))


def api_key():
    return settings()[1]


def alpb_fetch(endpoint, params):
    """One call to the Trackman API. Raises UpstreamError on any failure."""
    base, key, _, _ = settings()
    url = f"{base}/{endpoint}"
    try:
        resp = requests.get(url, headers={"x-api-key": key}, params=params,
                            timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        raise UpstreamError(f"Error fetching {url}: {e}") from e


def _pages(endpoint, params):
    """Every row of a paginated endpoint. A failed page fails the whole read,
    so a partial season is never cached as a complete one."""
    rows = []
    for page in range(1, MAX_PAGES + 1):
        data = alpb_fetch(endpoint, {**params, "page": page, "limit": PAGE_SIZE})
        # Rows come wrapped as {"data": [...]}. A bare list is accepted too.
        # Anything else is a bad reply, and raising UpstreamError leaves the
        # Trackman columns blank instead of taking the whole page down.
        batch = data.get("data") if isinstance(data, dict) else data
        if batch is None:
            batch = []
        if not isinstance(batch, list) or not all(isinstance(r, dict) for r in batch):
            raise UpstreamError(f"Unexpected reply from Trackman {endpoint}: "
                                f"{type(data).__name__}")
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    return rows


@st.cache_data(ttl=21600)
def get_players():
    df = pd.DataFrame(_pages("players", {}))
    for col in ("player_id", "player_name", "team_name"):
        if col not in df.columns:
            df[col] = ""
    return df[["player_id", "player_name", "team_name"]]


@st.cache_data(ttl=1800)
def get_pitches(player_id, role, start, end):
    """Every Trackman pitch in the date range where the player was the batter
    or pitcher. Only the columns advanced.py reads are kept."""
    rows = _pages("pitches", {f"{role}_id": player_id,
                              "date_range_start": start, "date_range_end": end})
    return adv.trim(pd.DataFrame(rows)) if rows else pd.DataFrame()


def player_pitches(player_ids, role):
    """One player's season across all his Trackman ids, as one table.

    Each pitch row has exactly one batter id and one pitcher id, so the same
    pitch can never come back under two ids and nothing needs de-duplicating.
    """
    _, _, start, end = settings()
    frames = [get_pitches(pid, role, start, end) for pid in player_ids]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _summarize(kind):
    return adv.hitter_advanced if kind == "hitter" else adv.pitcher_advanced


@st.cache_data(ttl=1800, show_spinner=False)
def get_team_summary(names, kind):
    """Trackman summary for every player on a team, one row per name.

    The API can only be queried one player at a time, so this is the slowest
    load on the page. It runs only when a view with Trackman columns is open,
    uses the same thread pool as the iScore load, and any failed request fails
    the whole call so a half-empty table is never cached.
    """
    roster = get_players()
    role = "batter" if kind == "hitter" else "pitcher"

    def one(name):
        ids = adv.match_player_ids(name, roster)
        return _summarize(kind)(player_pitches(ids, role)) if ids else {}

    return pd.DataFrame(threaded_map(one, list(names)), index=list(names))


def add_columns(df, kind):
    """``(df with every Trackman column, message)``. Columns are blank when the
    feed is unavailable or a player has no match, and the message says why."""
    message = None
    stats = pd.DataFrame(index=df["PLAYER"])
    if not api_key():
        message = "Trackman columns are blank because ALPB_API_KEY is not set."
    else:
        try:
            with st.spinner(f"Loading Trackman pitches for {len(df)} players. "
                            "The first load for a team can take a while."):
                stats = get_team_summary(tuple(df["PLAYER"]), kind)
        except UpstreamError as e:
            message = f"Couldn't reach the Trackman feed, so those columns are blank. {e}"
        except Exception as e:  # noqa: BLE001  Trackman is optional, never break the table
            message = f"Trackman data couldn't be read, so those columns are blank. {e}"
    out = df.copy()
    for col in adv.STAT_INFO:
        values = stats[col] if col in stats.columns else pd.Series(index=stats.index, dtype=float)
        out[col] = df["PLAYER"].map(values.to_dict()).astype(float)
    return out, message


def player_summary(name, kind):
    """``(summary, message)`` for one player's card. ``message`` explains a gap."""
    if not api_key():
        return {}, "Trackman stats need ALPB_API_KEY set."
    try:
        ids = adv.match_player_ids(name, get_players())
        if not ids:
            return {}, f"No Trackman match found for {name}."
        pitches = player_pitches(ids, "batter" if kind == "hitter" else "pitcher")
    except UpstreamError as e:
        return {}, f"Couldn't reach the Trackman feed just now. {e}"
    except Exception as e:  # noqa: BLE001
        return {}, f"Trackman data couldn't be read just now. {e}"
    summary = _summarize(kind)(pitches)
    if not summary:
        _, _, start, end = settings()
        return {}, f"No Trackman pitches for {name} between {start} and {end}."
    return summary, None
