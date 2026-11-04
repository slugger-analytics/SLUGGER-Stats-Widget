import streamlit as st
import pandas as pd
import requests
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import os
from io import BytesIO
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
from stats_utils import (
    select_season_rows,
    ip_to_innings,
    filter_min_sample,
    median_cut,
    classify_hitters,
    classify_pitchers,
    hitter_actions,
    pitcher_actions,
    HITTER_QUADRANTS,
    PITCHER_QUADRANTS,
    rank_among,
    ordinal,
)

st.set_page_config(page_title="ALPB Player Stats", layout="wide")


# -------------------
# Brand palette (single place to change colors)
# -------------------
# Placeholder SARG palette, ink and red with warm accents and no blue. Swap in
# the official SARG hex values here and in .streamlit/config.toml.
INK = "#1b1f2a"
ACCENT = "#c62127"
PANEL = "#f5f4ef"
QUAD_GOOD = "#1f9d8a"     # best quadrant
QUAD_MIXED_A = "#e0a800"  # good on the y stat only
QUAD_MIXED_B = "#e8853d"  # good on the x stat only
QUAD_BAD = "#c62127"      # worst quadrant


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
        textColor=colors.HexColor(INK),
        fontSize=14,
        alignment=1
    )

    subtitle_style = ParagraphStyle(
        name="SubtitleStyle",
        parent=styles["Normal"],
        textColor=colors.HexColor(ACCENT),
        fontSize=9,
        alignment=1
    )

    date_style = ParagraphStyle(
        name="DateStyle",
        parent=styles["Normal"],
        textColor=colors.HexColor(INK),
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
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), body_size),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(PANEL)]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9ca3af")),
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

# A cold team used to cost one sequential round trip per player. The calls are
# independent and network bound, so a small pool cuts a cold load from roughly
# (players x latency) to (players x latency / MAX_WORKERS). Kept modest so one
# page load does not hammer iScore.
MAX_WORKERS = 8


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


def fetch_all_player_stats(player_guids):
    """Fetch every player's stats concurrently, preserving input order.

    Worker threads need the script run context attached or Streamlit logs a
    "missing ScriptRunContext" warning per thread. If any fetch raises, the
    first UpstreamError propagates out of ``pool.map`` when its result is
    reached, which fails the whole aggregate build and so keeps a partial team
    table out of the cache, exactly as the sequential loop did.
    """
    ctx = get_script_run_ctx()

    def _attach_context():
        if ctx is not None:
            add_script_run_ctx(threading.current_thread(), ctx)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS,
                            initializer=_attach_context) as pool:
        return list(pool.map(get_player_stats, player_guids))


@st.cache_data(ttl=1800)
def get_team_stats_aggregated(team_guid, players_df):
    """Fetch stats for every player on the team and build batting + pitching tables."""
    batting_rows = []
    pitching_rows = []

    # A team with no roster yet comes back as a column-less DataFrame.
    if players_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    # A player whose stats call fails must not just vanish from the table.
    # Measured on Lancaster: two injected blips turned 26 batters into 25 and
    # 27 pitchers into 26, and the short table was then cached as the team's
    # authoritative roster for the full aggregate TTL with nothing on screen
    # saying it was incomplete. Failing the build keeps the cache empty, so a
    # rerun rebuilds it whole.
    all_stats = fetch_all_player_stats(players_df["player_guid"].tolist())

    for (_, player), stats_df in zip(players_df.iterrows(), all_stats):
        name = player["PLAYER"]
        throws = player.get("throwsHand", "")
        bats = player.get("bats", "")

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

STYLE = """
<style>
#MainMenu, footer, header {visibility: hidden;}
.block-container {padding-top: 1.5rem;}
h1 {border-bottom: 3px solid #c62127; padding-bottom: .5rem;}

/* Column picker chips, quiet grey pills instead of loud red blocks */
span[data-tag] {
    background-color: #e5e7eb !important;
    color: #1b1f2a !important;
    border-radius: 999px !important;
    font-size: 0.8rem;
}
span[data-tag] svg {fill: #6b7280 !important;}
</style>
"""


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
# Quadrants and insights
# -------------------
def short_name(name):
    """'Batter, Bob' becomes 'Batter B.' so teammates sharing a surname stay distinct."""
    parts = str(name).split(",")
    if len(parts) > 1 and parts[1].strip():
        return f"{parts[0].strip()} {parts[1].strip()[:1]}."
    return str(name)


def quadrant_chart(df, x_col, y_col, x_cut, y_cut, x_low_good, y_low_good,
                   x_label, y_label, quad_map, highlight=None, title=None):
    """Scatter with cutoff lines. Both axes are oriented so good is right and up."""
    quad_colors = {
        quad_map[(True, True)]: QUAD_GOOD,
        quad_map[(False, True)]: QUAD_MIXED_A,
        quad_map[(True, False)]: QUAD_MIXED_B,
        quad_map[(False, False)]: QUAD_BAD,
    }
    xs = pd.to_numeric(df[x_col], errors="coerce")
    ys = pd.to_numeric(df[y_col], errors="coerce")

    def bounds(vals, cut):
        lo, hi = min(vals.min(), cut), max(vals.max(), cut)
        pad = (hi - lo) * 0.12 or 1.0
        return lo - pad, hi + pad

    x_lo, x_hi = bounds(xs, x_cut)
    y_lo, y_hi = bounds(ys, y_cut)

    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    x_good = (x_lo, x_cut) if x_low_good else (x_cut, x_hi)
    x_bad = (x_cut, x_hi) if x_low_good else (x_lo, x_cut)
    y_good = (y_lo, y_cut) if y_low_good else (y_cut, y_hi)
    y_bad = (y_cut, y_hi) if y_low_good else (y_lo, y_cut)
    shade = [
        (x_good, y_good, QUAD_GOOD),
        (x_bad, y_good, QUAD_MIXED_A),
        (x_good, y_bad, QUAD_MIXED_B),
        (x_bad, y_bad, QUAD_BAD),
    ]
    for (xa, xb), (ya, yb), color in shade:
        ax.add_patch(Rectangle((xa, ya), xb - xa, yb - ya,
                               facecolor=color, alpha=0.10, linewidth=0, zorder=1))

    ax.scatter(xs, ys, c=[quad_colors[q] for q in df["QUADRANT"]], s=70,
               edgecolor="white", linewidth=0.8, zorder=3)
    if highlight is not None:
        picked = df["PLAYER"] == highlight
        if picked.any():
            ax.scatter(xs[picked], ys[picked], s=240, facecolors="none",
                       edgecolors=INK, linewidths=2, zorder=6)
    for name, x, y in zip(df["PLAYER"], xs, ys):
        ax.annotate(short_name(name), (x, y), xytext=(5, 4),
                    textcoords="offset points", fontsize=7, color=INK, zorder=4)

    ax.axvline(x_cut, color=INK, linestyle="--", linewidth=1, zorder=2)
    ax.axhline(y_cut, color=INK, linestyle="--", linewidth=1, zorder=2)
    ax.set_xlim((x_hi, x_lo) if x_low_good else (x_lo, x_hi))
    ax.set_ylim((y_hi, y_lo) if y_low_good else (y_lo, y_hi))
    ax.set_xlabel(x_label + (" (lower is better)" if x_low_good else " (higher is better)"))
    ax.set_ylabel(y_label + (" (lower is better)" if y_low_good else " (higher is better)"))

    corners = [
        (0.98, 0.97, "right", "top", quad_map[(True, True)], QUAD_GOOD),
        (0.02, 0.97, "left", "top", quad_map[(False, True)], QUAD_MIXED_A),
        (0.98, 0.03, "right", "bottom", quad_map[(True, False)], QUAD_MIXED_B),
        (0.02, 0.03, "left", "bottom", quad_map[(False, False)], QUAD_BAD),
    ]
    for cx, cy, ha, va, label, color in corners:
        ax.text(cx, cy, label, transform=ax.transAxes, ha=ha, va=va,
                fontsize=9, fontweight="bold", color=color, zorder=5)

    if title:
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=INK)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    return fig


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

    Everything lives in one collapsed section so the page stays short. The
    minimum sample and the cutoff lines only shape the chart and the insights.
    The table above keeps every player so nobody disappears from the box score.
    Returns the context a player card needs to judge one player the same way.
    """
    if kind == "hitter":
        size_label, size_max, size_default = "Minimum Plate Appearances", 250, 20
        x_col, y_col = "K%", "BB%"
        x_low_good, y_low_good = True, False
        quad_map, digits = HITTER_QUADRANTS, 1
        chart_title = "Plate Discipline"
        classify, actions = classify_hitters, hitter_actions
        step = 0.5
    else:
        size_label, size_max, size_default = "Minimum Innings Pitched", 60, 5
        x_col, y_col = "K9", "BB9"
        x_low_good, y_low_good = False, True
        quad_map, digits = PITCHER_QUADRANTS, 2
        chart_title = "Strikeouts and Walks"
        classify, actions = classify_pitchers, pitcher_actions
        step = 0.1

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
                ("OPS", True), ("HR", True), ("K%", False), ("BB%", True)]
PITCHER_TILES = [("IP", None), ("ERA", False), ("WHIP", False), ("K9", True),
                 ("BB9", False), ("K/BB", True)]


def render_player_card(player, ctx, kind):
    """One player's line, where they rank on the team, and a note on how to use them."""
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
                    ranked = rank_among(pool, player.get(col), col, high_good)
                    if ranked:
                        st.caption(f"{ordinal(ranked[0])} of {ranked[1]}")

        st.markdown(f"**{note[1]}.** {note[2]}")


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
                   view_key, picker_key, pdf_title, pdf_prefix, pdf_key, team, quad_kind):
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

    st.caption(f"{description} {note} Select a row to view the player card.")
    event = st.dataframe(
        df[shown],
        column_config=column_config_for(shown),
        width="stretch",
        height="content",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"{view_key}_table_{team}",
    )

    if shown:
        st.download_button(
            label="Download PDF",
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

    rows = list(event.selection.rows) if event is not None else []
    picked = df.iloc[rows[0]] if rows and rows[0] < len(df) else None
    card_slot = st.container()
    ctx = render_quadrants(df, quad_kind, key=view_key, team=team,
                           highlight=None if picked is None else picked["PLAYER"])
    if picked is not None:
        with card_slot:
            render_player_card(picked, ctx, quad_kind)


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

# Visiting the app with ?warm=1 loads every team into the server's cache so the
# first real visitor never waits on a cold team. The cache lives in the server
# process, so a separate script cannot do this. Entries expire with
# get_team_stats_aggregated's TTL, so re-warm shortly before a demo.
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

batting_df = add_hitter_metrics(batting_df)
pitching_df = add_pitcher_metrics(pitching_df)

st.caption(f"{len(batting_df)} hitters and {len(pitching_df)} pitchers with season stats. "
           "Click any column header to sort. Hover a header for what the stat means.")

hitters_tab, pitchers_tab = st.tabs(["Hitters", "Pitchers"])

with hitters_tab:
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
        quad_kind="hitter",
    )

with pitchers_tab:
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
        quad_kind="pitcher",
    )
