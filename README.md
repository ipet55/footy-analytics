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

.venv/bin/footy load-xg          # enrich matches with Understat xG
.venv/bin/footy load-elo         # fetch ClubElo rating histories
.venv/bin/footy build-elo        # compute own Elo variants from stored results
.venv/bin/footy build-features   # populate the point-in-time feature layer

.venv/bin/footy backtest                        # Dixon-Coles goals, vs closing odds
.venv/bin/footy backtest-counts --stat fouls     # corners, cards, fouls, shots
.venv/bin/footy blend-check                      # does the feature layer help? (no)

.venv/bin/footy predict --as-of 2026-05-01 --days 7   # store probabilities for fixtures
.venv/bin/footy show-predictions --market corners_home
```

`predict` fits as of a date and predicts only what follows it. Pointing `--as-of`
at a past matchday is how to check the output against results that are already
known — the models still see nothing later than the date given, and the database
refuses any prediction whose match falls inside its model's training window.

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
| `ml` | Model registry, calibrations, predictions, and the settlement views. |

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

The same rule reaches `ml`, where it is enforced rather than trusted: a trigger
rejects any prediction whose match kicked off before its model's training window
closed. It spans three tables, so it cannot be a check constraint.

### Reading predictions

`ml.market.status` decides what may be published — `shipping`, `held` or
`rejected` — so filter on the database rather than on a hardcoded list. A
published probability is `p_calibrated`; `p_raw` is what the model said before
its recalibration and is kept so the correction can be revisited. Both the
correction and the fit that produced any prediction are on file, which is what
makes a number on the page reproducible.

`ml.prediction_scored` joins predictions to what happened, with `hit` null for
fixtures not yet played.

## The app

```bash
cd web && cp .env.example .env.local && npm install && npm run dev
```

Fixture list, a match page showing every published market against the closing
price, and a calibration page. It reads the nine views in `public` and cannot
reach anything else: `anon` has no access to `core`, `ml`, `features` or `raw`,
so a held market or an uncalibrated probability cannot be rendered even by
mistake. Details in `web/README.md`.

## Tests

```bash
.venv/bin/python -m pytest        # 69 tests, ~40s
```

The model tests check the analytic gradients against finite differences, because
a wrong gradient does not raise — it silently stops the optimiser short of the
maximum likelihood. The leakage tests recompute feature values from scratch
against the live database, and the prediction tests re-derive every published
probability from its stored calibration. Both are skipped when `DATABASE_URL` is
absent. The blend tests pin the *mechanism* of a rejected experiment rather than
its result, since a negative finding is only worth keeping if the thing that
produced it demonstrably worked. The public-surface tests measure what the
`anon` role can actually read, which is the claim the security posture rests on.

## Model status

Validated walk-forward on 2022/23–2025/26, all five leagues. Detail in
`docs/02-phase1-count-markets.md`.

| Market | Benchmark beaten by | Status |
|---|---|---|
| 1X2 (Dixon-Coles) | closes 76% of the base-rate-to-market gap | baseline |
| Fouls, match total | 5.4–6.5% | shipping |
| Corners, per team | 1.9–6.3% | shipping |
| Shots, match total | 0.8–4.5% | shipping |
| Cards; per-team shots | 0.3–7.6% | held: percentages not accurate enough yet |
| Corners, match total | ~0% | not shipping — no signal exists |

Two rules the numbers imposed: published probabilities are always recalibrated,
never raw; and markets are scored against a *rolling* frequency, because a fixed
base rate flatters any model whenever a league drifts.

These verdicts are stored in `ml.market.status` rather than left in this table,
so the application cannot publish a market that has not earned it. Predictions
for all five leagues have been generated and settled end to end; see
`docs/results/phase2-stored-predictions.md`, which also shows the residual biases
tracking league-level drift rather than any failure to separate fixtures.

Nothing above uses the feature layer. Gradient boosting over it was built and
measured across ~80 configurations and improved no market, for a diagnosable
reason: congestion is currently derived from league fixtures alone, and squad
availability is not recorded at all. `docs/04-phase2-feature-blend.md` has the
evidence. The harness stays in `src/footy/models/blend.py`, off by default, so
that player and congestion data can be judged the moment it lands.

Per-team home advantage was measured the same way and also rejected. Opponent
strength is already the core of every model — Chelsea's expected away goals run
from 0.90 at Arsenal to 1.97 at Burnley — but the league shares one home
advantage, so "fortress at home, pushover away" is something the model cannot
say. Letting each team have its own, with shrinkage, made every market worse at
every setting. The reason is in the data: across 853 team-seasons, attack
persists year to year at r=0.65 and defence at 0.55, while the home/away split
sits at -0.055. It describes the past and predicts nothing.
`docs/05-venue-effects.md` has the evidence; `venue_penalty` on
`dixon_coles.fit` is off by default.

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
