"""Rebuild data/league_baselines.json from the newest data/snapshot_*.json.

    python scripts/snapshot_league.py        # pull iScore, about a minute
    python scripts/build_league_report.py    # crunch it, a few seconds

Commit the resulting data/league_baselines.json. The raw snapshot is about
20 MB and is git-ignored.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from league import build_league_report  # noqa: E402


def main():
    snaps = sorted((ROOT / "data").glob("snapshot_*.json"))
    if not snaps:
        sys.exit("No data/snapshot_*.json. Run scripts/snapshot_league.py first.")
    snap = json.loads(snaps[-1].read_text())
    report = build_league_report(snap)
    dest = ROOT / "data" / "league_baselines.json"
    dest.write_text(json.dumps(report, indent=1))
    m = report["meta"]
    print(f"{snaps[-1].name} -> {dest.relative_to(ROOT)}: "
          f"{m['hitters']} hitters, {m['pitchers']} pitchers")


if __name__ == "__main__":
    main()
