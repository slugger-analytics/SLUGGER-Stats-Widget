"""Run the widget against a saved snapshot instead of the live iScore API.

    streamlit run scripts/preview_from_snapshot.py

Useful on a machine that cannot reach iScore, and for demos when the feed is
down. Reads the newest data/snapshot_*.json.
"""
import json
import os
import runpy
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LEAGUE_GUID", "snapshot-league")

snap = json.loads(sorted((ROOT / "data").glob("snapshot_*.json"))[-1].read_text())
os.environ["SEASON_GUID"] = snap["season_guid"]
_players = {t["guid"]: t["players"] for t in snap["teams"]}
_stats = {p["guid"]: p for t in snap["teams"] for p in t["players"]}


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _get(url, headers=None, params=None, timeout=None):
    if url.endswith("/teams"):
        return _Resp([{"guid": t["guid"], "name": t["name"]} for t in snap["teams"]])
    if url.endswith("/players"):
        guid = url.split("/teams/")[1].split("/")[0]
        return _Resp([{"guid": p["guid"], "name": p["name"], "bats": p["bats"],
                       "throwsHand": p["throws"]} for p in _players[guid]])
    if url.endswith("player-stats"):
        p = _stats[params["playerId"]]
        return _Resp([{"stats": {snap["season_guid"]: p["stats"]}}] if p["stats"] else [])
    return _Resp([])


requests.get = _get
runpy.run_path(str(ROOT / "widget.py"), run_name="__main__")
