# SLUGGER Stats Widget

A Streamlit app that shows current-season hitting and pitching stats for every team in the Atlantic League of Professional Baseball (ALPB). Pick a team, see its pitchers and hitters ranked best first, choose which stats to display, and download the table as a PDF report. It is one widget in the SLUGGER project from the Johns Hopkins Sports Analytics Research Group.

All data comes live from the iScore public API. There is no database and nothing to load by hand.

## What you can do with it

- Select any ALPB team from a dropdown.
- Switch between separate Hitters and Pitchers tabs. Hitters are sorted by plate appearances and pitchers by batters faced, so the players with the biggest workloads lead and tiny samples sink to the bottom.
- Select a row to open a player card with that player's line, team rank, league percentile, a regressed skill estimate and a short usage note.
- Open the Team tab to see where a team ranks in the league on offense, pitching, defense and park effects.
- Open the Findings tab for league research on what is skill and what is luck, with the strength of each result labeled.
- Open Team Insights to set minimum playing time and cutoff lines, view a quadrant chart (plate discipline for hitters, strikeouts and walks for pitchers) and read rule-based insights.
- Switch between views built the way scouting reports are. Hitters have Traditional, Slash Line, Power, Discipline, Advanced and Splits. Pitchers have Traditional, Rates, Advanced, Command, Splits and Workload. All shows every stat and Custom lets you pick your own.
- Click any column header to re-sort, for example by ERA or OPS, and hover a header for what the stat means.
- Download the exact table you are looking at as a landscape PDF, ready to print for a scouting sheet or a pregame meeting.

## Quick start

Requires Python 3.13, the version used by the Docker image and by CI.

```bash
git clone https://github.com/slugger-analytics/SLUGGER-Stats-Widget.git
cd SLUGGER-Stats-Widget
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a file named `.env` in the project root with the two identifiers the app needs.

```
LEAGUE_GUID=your-league-guid
SEASON_GUID=your-current-season-guid
```

Then start the app.

```bash
streamlit run widget.py
```

Streamlit prints a local address, normally http://localhost:8501, and opens it in your browser. Choose a team and the tables load. The first load of each team takes a few seconds because the app requests every player separately. Later loads of that team are instant until the cache expires.

### Where the two GUIDs come from

Both are public identifiers from iScore. The values used by the deployed app are set in `aws/task-definition.json` under `environment`. To look up identifiers for another league or season, run the helper tool.

```bash
streamlit run find_guids.py
```

It walks through the iScore endpoints step by step and shows where each GUID appears in the response.

`LEAGUE_GUID` is required. Without it the app cannot load the team list and shows an error banner. `SEASON_GUID` is strongly recommended. Without it the app logs a warning and combines every season iScore returns, which includes a junk season named "DO-NOT-USE" and all prior seasons, so players appear more than once with the wrong totals.

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests never contact iScore. They replace the network layer with a stub and drive the real app through Streamlit's `AppTest`, so they check what a visitor would actually see. They cover the following.

- `test_load_speed_and_warmup.py` covers concurrent fetching, workload sorting, a team with no roster, and the cache warm-up link.
- `test_upstream_resilience.py` covers the views and derived stats, an iScore outage not being cached, request timeouts, and clearing the custom column picker not crashing the page.
- `test_cache_ttls.py` checks that every cached function declares a time limit.
- `test_season_filter.py` covers the current-season selection logic in `stats_utils.py`.
- `test_metrics_and_league.py` covers the stat math, the multiple-testing correction, and the shape of the league report.

## How it works

1. `get_league_teams` loads the team list.
2. `get_team_players` loads the roster for the selected team.
3. `get_team_stats_aggregated` requests every player's stats in parallel (up to 8 at a time), keeps only the configured season, and builds one batting table and one pitching table. A player appears in a table only if they have at least one plate appearance or batter faced.
4. The page adds derived stats (ISO, BB%, K% and K/BB), sorts by workload and renders one table per view. The PDF is generated from the same sorted table and the columns on screen.

### Caching and failure handling

Responses are cached in the server process so repeat visits are fast.

| Data | Cache time |
|---|---|
| Team list | 60 minutes |
| Team roster | 15 minutes |
| One player's stats | 15 minutes |
| A team's finished tables | 30 minutes |

A failed request is never cached. If iScore is unreachable, even for one player, the app shows a retryable warning and builds nothing, rather than showing a team table with players silently missing. Pressing "Try again" fetches fresh data. Every request has a timeout so a hung connection cannot freeze the page.

### Warming the cache before a demo

Open the app with `?warm=1` added to the address to load every team into the cache in one pass. Cached tables last 30 minutes, so do this shortly before you present.

```
http://localhost:8501/?warm=1
```

On the deployed app the address is `https://www.alpb-analytics.com/widgets/stats/?warm=1`.

## League research

The Findings and Team tabs read `data/league_baselines.json`, a small file built from a snapshot of every ALPB player. League context needs all 539 players, which is about 550 iScore calls, so the app reads it from the file instead of fetching it on each visit. The 2026 season is over, so it does not go stale. To rebuild it, for example next season, run these from the repo root.

```bash
python scripts/snapshot_league.py        # pull iScore, about a minute, writes data/snapshot_YYYYMMDD.json
python scripts/build_league_report.py    # crunch it, writes data/league_baselines.json
```

Commit `league_baselines.json`. The raw snapshot is about 20 MB and is git-ignored. To run the app against a snapshot with no network, use `streamlit run scripts/preview_from_snapshot.py`.

If the file is missing the app still works. The Team and Findings tabs show a note, and the Advanced stats fall back to the selected team's own rates.

### Method notes

- wOBA uses MLB linear weights, since ALPB run values are not available. It ranks hitters well but its scale is approximate.
- Regressed estimates (xK%, xBB%, xBABIP) pull a rate toward the league rate by sample size, using published stabilization points listed in `metrics.py`.
- Skill versus luck is measured by correlating each player's home games with his road games and scaling the result to a full season.
- Individual split and situation tests use a Benjamini-Hochberg false discovery correction, because testing a hundred hitters guarantees a handful of flukes at p < .05.

## Project structure

```
widget.py                     The page layout and tabs
data.py                       iScore access, caching, and team table assembly
metrics.py                    Stat math (wOBA, FIP, BABIP, shrinkage, tests), no Streamlit
league.py                     League report builder and research, no Streamlit
findings.py                   The Findings tab text, read from the league report
charts.py                     Matplotlib figures
display.py                    Column order, views, decimals, help text, palette
report_pdf.py                 PDF export
stats_utils.py                Season selection, quadrants and coaching notes, free of Streamlit
find_guids.py                 Standalone tool for finding league and season GUIDs
scripts/                      Snapshot, report build, and offline preview tools
data/league_baselines.json    Precomputed league context
tests/                        Pytest suite, no network access needed
requirements.txt              Runtime dependencies, pinned
requirements-dev.txt          Runtime dependencies plus pytest
.streamlit/config.toml        Dark navy and red theme
Dockerfile                    Container image used in production
aws/task-definition.json      ECS Fargate task definition
.github/workflows/deploy.yml  Build, deploy, and smoke test on every push to main
.devcontainer/                GitHub Codespaces configuration
```

## Docker

```bash
docker build -t widget-stats .
docker run --rm -p 8501:8501 -e LEAGUE_GUID=your-league-guid -e SEASON_GUID=your-season-guid widget-stats
```

The container serves under the path `/widgets/stats`, so open http://localhost:8501/widgets/stats instead of the root address.

## Deployment

`.github/workflows/deploy.yml` runs the test suite on every pull request into `main` and on every push to `main`. Deploys happen only from `main`, and only if the tests pass. A push that changes more than Markdown files then builds the image for amd64, pushes it to Amazon ECR, deploys it to the `slugger-stats-service` ECS Fargate service in the `slugger-cluster` cluster, and waits for the service to become stable. It then checks the Streamlit health endpoint through the public load balancer and fails the run if the app does not answer.

The workflow signs in to AWS through GitHub OIDC, so no AWS keys are stored in the repository. It needs one repository secret, `AWS_DEPLOY_ROLE_ARN`. The service runs a single task on purpose, because Streamlit keeps a websocket open per visitor and one task keeps each session on one server.

## Known limits

- Stats are season totals only. There are no game logs, fielding stats, or lefty and righty splits yet.
- Numbers are as fresh as the cache, so they can lag iScore by up to 30 minutes.
- Hot and cold indicators need game logs, which the iScore endpoints used here do not provide.
- League percentiles and findings come from a 2026 snapshot, not live data.
- Home and road splits give a rough park factor, not a true one.

## Future work

- A Fielders tab, using the fielding data iScore provides.
- Game-level tables.
- Lefty and righty pitching splits, if iScore can separate stats when several pitchers appear in one game.
