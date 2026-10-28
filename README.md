# SLUGGER Stats Widget

A Streamlit app that shows current-season hitting and pitching stats for every team in the Atlantic League of Professional Baseball (ALPB). Pick a team, see its pitchers and hitters ranked best first, choose which stats to display, and download the table as a PDF report. It is one widget in the SLUGGER project from the Johns Hopkins Sports Analytics Research Group.

All data comes live from the iScore public API. There is no database and nothing to load by hand.

## What you can do with it

- Select any ALPB team from a dropdown.
- Read a Pitchers tab sorted by innings pitched and a Hitters tab sorted by plate appearances, so the players with the biggest workloads lead and tiny samples sink to the bottom.
- Choose which stat columns appear. Click any column header to re-sort, for example by ERA or OPS.
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
- `test_upstream_resilience.py` covers an iScore outage not being cached, request timeouts, and clearing the column picker not crashing the page.
- `test_cache_ttls.py` checks that every cached function declares a time limit.
- `test_season_filter.py` covers the current-season selection logic in `stats_utils.py`.

## How it works

1. `get_league_teams` loads the team list.
2. `get_team_players` loads the roster for the selected team.
3. `get_team_stats_aggregated` requests every player's stats in parallel (up to 8 at a time), keeps only the configured season, and builds one batting table and one pitching table. A player appears in a table only if they have at least one plate appearance or batter faced.
4. The page sorts the tables by workload and renders them. The PDF is generated from the same sorted table and the columns you selected.

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

## Project structure

```
widget.py                     The Streamlit app, data fetching, and PDF export
stats_utils.py                Season selection logic, free of Streamlit so it is easy to test
find_guids.py                 Standalone tool for finding league and season GUIDs
tests/                        Pytest suite, no network access needed
requirements.txt              Runtime dependencies, pinned
requirements-dev.txt          Runtime dependencies plus pytest
.streamlit/config.toml        Navy and red theme
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
- The iScore leaderboard and games-by-player endpoints have not been made to work with this widget, so percentile rankings and hot and cold indicators are not built.

## Future work

- A Fielders tab, using the fielding data iScore provides.
- Game-level tables.
- Lefty and righty pitching splits, if iScore can separate stats when several pitchers appear in one game.
