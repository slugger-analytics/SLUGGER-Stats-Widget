"""Unit tests for the ``@st.cache_data`` TTLs in ``widget``.

These parse ``widget.py`` with ``ast`` rather than importing it, since its
module body executes network + Streamlit calls on import.
"""
import ast
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

WIDGET_PY = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "widget.py")
)

# The TTL each cached function is expected to declare, in seconds.
EXPECTED_TTLS = {
    "get_league_teams": 3600,
    "get_team_players": 900,
    "get_player_stats": 900,
    "get_team_stats_aggregated": 1800,
}
# The roster TTL the sibling pitcher widget settled on (ROSTER_TTL_SECONDS).
PITCHING_WIDGET_ROSTER_TTL = 900


def _module():
    with open(WIDGET_PY, encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _is_cache_data(decorator):
    """True for both ``@st.cache_data`` and ``@st.cache_data(...)``."""
    node = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(node, ast.Attribute) and node.attr == "cache_data"


def _cached_functions():
    """Map every ``@st.cache_data``-decorated function name to its decorator."""
    cached = {}
    for node in ast.walk(_module()):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if _is_cache_data(decorator):
                cached[node.name] = decorator
    return cached


def _ttl(decorator):
    """The literal ``ttl=`` value on a cache_data decorator, or None."""
    if not isinstance(decorator, ast.Call):
        return None
    for keyword in decorator.keywords:
        if keyword.arg == "ttl" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def test_every_cache_data_decorator_declares_a_ttl():
    """(a) A bare ``@st.cache_data`` freezes data for the container's life."""
    cached = _cached_functions()
    assert cached, "no @st.cache_data functions found — did widget.py move?"
    untimed = [
        name for name, decorator in cached.items() if _ttl(decorator) is None
    ]
    assert untimed == [], f"cache_data without a ttl: {untimed}"


def test_ttl_values():
    """(b) Each cached function carries the TTL it was tuned for."""
    cached = _cached_functions()
    assert {name: _ttl(cached[name]) for name in EXPECTED_TTLS} == EXPECTED_TTLS


def test_roster_ttl_matches_the_pitching_widget():
    """(c) A newly signed player surfaces in BOTH widgets in the same window."""
    ttl = _ttl(_cached_functions()["get_team_players"])
    assert ttl == PITCHING_WIDGET_ROSTER_TTL


def test_player_stats_ttl_shorter_than_aggregate_ttl():
    """(d) Otherwise an aggregate rebuild just re-serves its own cached rows."""
    cached = _cached_functions()
    assert _ttl(cached["get_player_stats"]) < _ttl(
        cached["get_team_stats_aggregated"]
    )


def test_dead_helpers_are_gone():
    """(e) Both bypassed the season filter and had zero call sites."""
    names = {
        node.name
        for node in ast.walk(_module())
        if isinstance(node, ast.FunctionDef)
    }
    assert "parse_player_stats" not in names
    assert "hot_cold_label" not in names
