# footy-analytics

Football data pipeline and prediction models for the top 5 European leagues,
2014/15 to 2025/26. Data lands in Supabase Postgres.

## Setup

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv is not installed
uv venv --python 3.12
uv pip install -e .
cp .env.example .env                              # then fill in DATABASE_URL
```

The system Python on macOS is 3.9 and too old; `uv` installs an isolated 3.12.

## Commands

```bash
.venv/bin/footy status    # show configuration and whether credentials are present
.venv/bin/footy fetch     # download football-data.co.uk CSVs (60 files, ~12 MB)
.venv/bin/footy parse     # parse and report counts without touching the database
.venv/bin/footy load      # load results, team stats and odds into Supabase
.venv/bin/footy verify    # integrity and coverage report
```

`load` is idempotent. Re-running it updates existing rows rather than duplicating
them, so it is safe to re-run after a partial failure or to refresh the current season:

```bash
.venv/bin/footy load --season 2025
```

## Database layout

Four schemas, in Supabase project `Football_Analysis` (`eu-west-1`):

| Schema | Purpose |
|---|---|
| `raw` | Immutable landing zone. Never edited — reprocess from here when parsing logic changes. |
| `core` | Canonical, provider-agnostic model of the game. Single source of truth. |
| `features` | Point-in-time-correct ML features. |
| `ml` | Model registry, predictions, realised outcomes. |

Only `public` is exposed through Supabase's Data API, so all four are reachable
solely via the service role. The web app will read from purpose-built views in
`public`, never from `core` directly.

### Two rules that matter

**Never string-match team names in application code.** Every provider spells teams
differently. Resolve through `core.team_alias`, and let `core.resolve_team()` log
misses to `core.unresolved_alias`. A missing alias should be loud; a wrong one is
silent corruption.

**Every row in `features` may only contain information that existed before its match
kicked off.** Data leakage is what makes football models look excellent in backtests
and lose money in production. It is the most common failure mode in this domain.

## Sources

| Data | Source | Cost | Coverage | Status |
|---|---|---|---|---|
| Results, shots, corners, fouls, cards, odds | football-data.co.uk | Free | 2014+, all 12 seasons | Implemented |
| xG, npxG, PPDA, deep completions | Understat | Free | 2014+ | Next |
| Elo ratings | ClubElo | Free | Full history | Next |
| Possession, passes, progressive actions | FBref | Free | 2017+ | Planned |
| Fixtures, lineups, injuries, live | API-Football | $19–29/mo | 1200+ leagues | Planned |
| Transfers, market values | transfermarkt-datasets | Free | Weekly refresh | Planned |
| News | RSS (BBC, Guardian, Sky) | Free | Unlimited | Planned |

`core.stat_coverage` records which source supplies which statistic and from when,
so ingestion can assert expected coverage instead of silently writing nulls.

Understat, FBref and Transfermarkt are scraped rather than licensed. Fine for
personal research and model training; republishing commercially would require a
licensed provider. `core.source.is_licensed` flags this per source.

## What football-data.co.uk does and does not give you

Verified against all 60 downloaded files rather than the provider's documentation:

- **Present in all 12 seasons:** shots, shots on target, corners, fouls, yellow
  cards, red cards, half-time score, referee.
- **Absent in this era:** possession, passes, offsides, woodwork, attendance, xG.
  The `core.match_team_stat` columns exist for them and fill in from Understat,
  FBref and API-Football later.
- **Kickoff times** only exist from 2019/20 and are UK time, not local time
  (verified: La Liga's 21:00 local appears as 20:00). They are converted to UTC on load.
- **Closing odds** exist for Pinnacle in all 12 seasons. Other bookmakers only have
  closing prices from 2019/20. Pinnacle is the sharpest book, so its closing line is
  the benchmark the model is measured against.
- **Aggregates:** the provider publishes its own average and maximum across ~20
  books. These are stored as bookmakers `_average` and `_maximum` with
  `core.bookmaker.kind = 'aggregate'`, and are excluded from any average taken over
  real books — the maximum is by construction the best price and would skew it.
