"""Save every ALPB player's raw iScore stats to one JSON file.

The widget reads iScore live, which is right for a dashboard but useless for
analysis you want to reproduce. This pulls the whole league once, so findings
can be computed, checked and re-run offline against a fixed snapshot.

Usage (from the repo root, with LEAGUE_GUID and SEASON_GUID in .env or the
environment; falls back to the production values in aws/task-definition.json)

    python scripts/snapshot_league.py

Writes data/snapshot_<YYYYMMDD>.json. Takes about a minute.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://api.microservices.iscoresports.com/api"
ROOT = Path(__file__).resolve().parent.parent


def _guids():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    league, season = os.getenv("LEAGUE_GUID"), os.getenv("SEASON_GUID")
    if not (league and season):
        env = json.loads((ROOT / "aws" / "task-definition.json").read_text())
        values = {e["name"]: e["value"]
                  for c in env["containerDefinitions"] for e in c.get("environment", [])}
        league = league or values["LEAGUE_GUID"]
        season = season or values["SEASON_GUID"]
    return league, season


def get(endpoint, params=None, tries=3):
    for attempt in range(tries):
        try:
            r = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=(5, 30))
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            if attempt == tries - 1:
                raise
            print(f"  retry {endpoint}: {e}", file=sys.stderr)
            time.sleep(1.5 * (attempt + 1))


def items(data):
    return data if isinstance(data, list) else data.get("items", data.get("data", []))


def main():
    league, season = _guids()
    teams = items(get(f"public/leagues/{league}/teams"))
    print(f"{len(teams)} teams")
    out = {"taken_at": datetime.now().isoformat(timespec="seconds"),
           "league_guid": league, "season_guid": season, "teams": []}

    with ThreadPoolExecutor(max_workers=8) as pool:
        for t in teams:
            players = items(get(f"public/teams/{t['guid']}/players"))
            stats = list(pool.map(
                lambda p: items(get("player-stats", {"playerId": p["guid"]})), players))
            team = {"guid": t["guid"], "name": t["name"], "players": []}
            for p, s in zip(players, stats):
                season_stats = (s[0].get("stats", {}) if s else {}).get(season)
                team["players"].append({
                    "guid": p["guid"], "name": p.get("name"),
                    "bats": p.get("bats"), "throws": p.get("throwsHand"),
                    "position": p.get("positionGroup"), "stats": season_stats,
                })
            print(f"  {t['name']}: {len(players)} players")
            out["teams"].append(team)

    dest = ROOT / "data" / f"snapshot_{datetime.now():%Y%m%d}.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(out))
    print(f"wrote {dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
