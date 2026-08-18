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

.venv/bin/footy link-fixtures     # attach API-Football ids to matches another source owns
.venv/bin/footy load-events       # goal, card and substitution minutes, and team sheets
.venv/bin/footy load-squads       # current rosters, one request per club
.venv/bin/footy load-absences     # who misses the coming fixtures, one request per date
.venv/bin/footy load-transfers    # moves in and out

.venv/bin/footy refresh           # a day's work: results in, features rebuilt, fixtures priced
.venv/bin/footy freshness         # assert the data is current, and exit non-zero when it is not
```

`refresh` runs the whole cycle in dependency order and is what a scheduler should
call. `freshness` is what says whether it is actually working, because a job that
has stopped running raises nothing at all.

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
.venv/bin/python -m pytest        # 121 tests, ~40s
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
| Shots, per team | 5.2–13.7%, every league, line and side | shipping — the strongest market here |
| Fouls, match total | 5.4–6.5% | shipping |
| Corners, per team | 1.9–6.3% | shipping |
| Shots, match total | 0.8–4.5% | shipping |
| Cards, match total, after referees landed | 0.6–5.0% | held — Italy would qualify alone, Germany and France do not |
| Fouls, per team | 2.6–9.1%, now positive everywhere | held — the 12.5 line miscalibrates in three leagues |
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

Squad strength looked like the one that works, and did not survive replication.
FBref team sheets for all five leagues — 8,982 matches, 100% coverage, one
failing to reconcile with the official score — gave the models something they
never had: who is actually on the pitch. How much of today's eleven is the
established eleven gains **0.0102 of 1X2 log-loss in the Premier League**, on
every held-out season, with a monotonic dose-response. Across the other four
leagues and 4,173 matches it gains **+0.0004, with a 95% interval of -0.0011 to
+0.0018**.

The mistake is worth more than the finding. Matches within a season are not
independent trials — the correction is fitted once per season and applied to all
of them — so t = 3.90 on 1,136 matches was measuring far less than it looked.
Cluster by season, the level the design actually varies at, and **England's own
result is p = 0.100**: never significant. "Positive in all three seasons" is
exactly what a p = 0.10 effect looks like three times running. Season-clustered
replication across independent leagues is now the bar here.
`docs/06-squad-strength.md` has the evidence; reproduce with `footy squad-check`.

Whether it could ever have been served was measured separately and also answered
no. A predicted eleven built from recent minutes, suspensions and players missing
from recent squads gets 8.2 of 11 starters right and still recovers only **10% of
the English gain**; the unguessable remainder carries 82%. The model already
knows what a team looks like at full strength, so the only news in a team sheet
is the departure from it — and that part cannot be predicted from past team
sheets. The player layer is kept regardless: the features were the wrong
hypothesis, but the data is validated and cheap to query.

Referees were the one genuine data gap that closed. `core.match.referee_id` was
100% for England and 0% everywhere else, because football-data.co.uk publishes the
column only for `E0` — so the cards model's referee term, built in Phase 1, had
nothing to fit in four leagues out of five. FBref names the referee on its
*schedule* page at full coverage back to 2014-15, one request per season rather
than per match, so 13,145 matches and 201 officials cost minutes. Referees vary by
1.2 to 2.2 cards a match depending on the league, and the improvement to cards
**tracks that spread across independent leagues**: Spain and Italy gain +0.0077
and +0.0118, the three leagues with tighter referee variation gain nothing.
Pooled over 15 league-seasons that is p = 0.039; clustered by league it is p ≈
0.20, so it is suggestive rather than established. Cards still do not ship — Italy
alone would now qualify, Germany and France are nowhere near.
`docs/07-referees.md` has the evidence.

Style of play is the cleanest rejection of the four, because for once the data is
beyond reproach. Understat's PPDA and deep completions cover every team-match in
all five leagues back to 2014-15, and they measure real traits: split-half
reliability is 0.91 for pressing and 0.93 for deep completions, and pressing
persists from season to season at r=0.73. Across **forty held-out league-seasons**
they add nothing to goals, fouls or cards, in any of five specifications, and
every added parameter makes it monotonically worse. The explanation is the same
property that made them look promising — a trait that stable is already inside the
attack and defence ratings the models fit over a decade, so restating it is close
to regressing on parameters the model already has. Reliability and predictive
value are different questions. `docs/08-style-of-play.md` has the evidence, and
closes roadmap Phase 5.

That investigation paid for itself by surfacing a real bug rather than a feature.
The per-team count models were **returning fouls rates of 1e12 in four leagues out
of five**, and shots rates of 1e6 in two, because `concede` started at half the
level it has to carry while `attack` is pinned to sum to zero — so the optimiser
made up the difference by driving parameters into their bounds. Cards and corners
were unaffected, their means being small enough to start from, and the match
totals were never affected at all because `fit_total` has an explicit intercept.
Fixing it left every shipped number bit-identical and promoted per-team shots from
a documented 0.3–7.6% to 1.4–11.7%, positive in all five leagues at every line —
the strongest signal in the project outside fouls totals.

It was then held on calibration rather than signal, and that turned out to be a
second bug wearing the first one's clothes. Unknown teams defaulted to a
parameter of zero, which is right for attack and wrong for `concede`, where it
prices a team at one shot a match instead of twelve. A backtest meets unknown
teams three times a league every season, on the clubs just promoted into it, and
a worst-bucket statistic reports exactly that kind of rare pathology. Correcting
the default — done to stop a crash on the 2026-27 promoted clubs, with no
expectation it would touch a backtest — took France from 14.8% to 6.4% and Italy
from 13.3% to 7.0%. Restoring the old default reproduces the published figures
exactly, which is what makes it a cause rather than a coincidence.

**Per-team shots therefore ships**: 5.2–13.7% over the rolling benchmark and
worst buckets of 1.1–7.0% across all thirty combinations of five leagues, three
lines and two sides. Per-team fouls is the counter-example that keeps the
standard meaningful — its signal is now positive everywhere too, but the 12.5
line still miscalibrates in three leagues, and status is per market rather than
per line. `docs/09-count-fit-divergence.md` has the evidence; reproduce with
`python scripts/market_trust.py`.

The 2026-27 calendars are loaded — 1,752 fixtures across the five leagues, from
La Liga's opening weekend on 15 August to the last day of May — and predictions
are stored for the opening rounds. Fixtures come from FBref's schedule pages
rather than football-data.co.uk, whose `fixtures.csv` is a rolling one-week
window and cannot give a season calendar. `footy load-fixtures` is safe to re-run
and updates kickoff dates in place, which matters because television moves them
constantly.

One limitation to state plainly, because it is invisible in the output: the five
promoted clubs have never played in a league we hold data for, so they are priced
at the league average. That is a neutral prior rather than a good one — promoted
teams are systematically weaker than average, and the model will overrate them
until they have played enough matches to be rated on their own. It is at least
now the actual average: unknown teams used to default to a parameter of zero,
which is right for attack, centred by the sum-to-zero constraint, and wrong for
defence and for the count models' `concede`, which carries the whole level of the
statistic. A promoted club was being priced at one foul a match instead of ten,
and the over probability underflowed hard enough to violate its own check
constraint. Both models now default to the mean of their fitted parameters.

## What the app serves

Nine of the fourteen competitions publish something, and they do not publish the
same things. Publication is decided per competition in `ml.market_competition`
and enforced by the views. Absence means no: a competition with no row publishes
nothing rather than inheriting a verdict earned on other data, which is asserted
in `tests/test_public_surface.py`.

| Competition | Markets |
|---|---|
| England, Spain, Italy, Germany, France | 11 |
| Portugal, Turkey | 11 |
| Belgium | 10 |
| Netherlands | 8 |

Which eleven differs. Portugal publishes away corners and withholds home corners;
Turkey publishes both; the Netherlands withholds all of them. That is not
arbitrariness, it is the calibration measured in each place.

Two rules do the deciding, and both must hold at *every* line, because status has
no line dimension and a market is published whole or not at all: beat the rolling
benchmark by at least a point, and keep the worst reliability bucket inside 8%.

The gain floor was added after the full assessment, because "positive at every
line" turned out to admit markets gaining 0.2%. Corner totals clear that bar in
three of the four new leagues while the original five found no signal there at all
— and the mechanism behind that finding, that dominance moves corners between the
sides rather than creating them, does not stop being true in the Eredivisie. One
percent is set by precedent rather than taste: shots totals ship globally on a
minimum of 0.8%.

Measuring one line and generalising cost three wrong calls, all corrected: Dutch
fouls totals and home corners, and Turkish fouls totals, were published on a single
line's evidence and fail once every line is checked.

Bulgaria, the Czech league, Eliteserien and the two UEFA competitions are loaded
and measured but publish nothing yet.

Alongside the predictions there is a Teams tab carrying the opposite kind of
number: counts of what happened in the matches a team played, split overall, at
home and away, from `public.team_season_measure` and `public.team_season_line`.
Galatasaray earned 5.50 corners a game in 2025/26 — 6.53 at home and 4.47 away —
and had more than their opponent in 82% of home games against 53% away. That
split is most of the information, and a single season average hides it.

Those two are materialized. As plain views they aggregated 99,000 team-match rows
across nine measures, several lines and two grouping sets on every request, which
took 3.4 seconds and exceeded the API's statement timeout — and a timed-out query
is indistinguishable from an unknown team, so the page returned 404. They are
refreshed by `footy build-features` alongside the odds views, because a stale team
page would show a season ending several matches early and look entirely plausible
doing it.

It is history and not prediction — it makes no adjustment for the opponent — and
both the view comments and the page say so, because it is the easiest number here
to misread as a forecast.

### Evidence, minutes and team sheets

A match page used to be a table of probabilities with nothing beside it, while
`core.match_team_stat` held between six and sixteen figures per team per match that
nothing displayed. It now shows them, both sides on one row with the split drawn as
a bar, because 16 shots against 10 says something 16 alone does not. A row the
competition does not record is omitted rather than zeroed — showing a number
against a blank invites the blank to be read as zero — which is why a Premier
League match shows expected goals and no possession and a Champions League match
the reverse.

Two things had to be loaded. `core.match_event` holds the minute of every goal,
card and substitution, and `core.match_lineup` with `core.match_lineup_player` holds
the eleven, the bench, the formation and the coach. 34,052 events across 2,090
matches, and 4,180 team sheets naming 88,523 players, kept current by
`footy refresh`. The referee needed no loading at
all: it has been on `core.match` since the FBref backfill, and it is the strongest
single driver in the card models, sitting beside the card markets it explains.

Minutes make the timing dashboards possible. Arsenal scored 67 league goals in
2025/26 with 16 of them between 31 and 45 minutes, opened the scoring in 66% of
their matches, and failed to score in 11%. An average first-goal minute of 38.9
tells you far less than that distribution.

Both were shaped by what the feed actually sends rather than what it should. The
minute can be negative — a booking in the tunnel — so the constraint starts at -30
and the bands fold anything below minute one into the first rather than clamping a
pre-match card into the opening quarter hour. More seriously, extra time and penalty
shootouts arrive as ordinary goal events: a qualifier recorded as 0-3 produced goals
at 95 and 100 minutes, and since the last band is "76 and after", shootout kicks
were landing there as late goals. That was 4.5% of Champions League goal events and
would have made every knockout competition look like it scored heavily at the death.
The timing views are regulation play only, and the timeline counts its own
regulation goals and says so when they disagree with the result — because a page
showing six goals above a 0-3 scoreline, unexplained, teaches a reader to distrust
everything else on it.

### Squads, absences and a projected eleven

Who is at each club, who is missing the next match and why, and — until the real
team sheet appears — who is likely to start. For all fourteen competitions, not
just the five with the richest data.

Absences turned out to be affordable everywhere because the provider's endpoint is
scoped to a date rather than a league: one request covers every competition at
once. They are stored per fixture rather than per player, because that is both how
the source reports it and the honest shape — a player is doubtful for a match, not
doubtful in general — as `out` or `doubtful`, keeping the provider's own reason.
"Ribs Injury" beats a bucket of ours, and putting an open vocabulary into
categories mostly produces wrong categories. Every load replaces a match's list, so
a recovered player stops being listed rather than staying injured forever.

Squads needed the player table opened up first. `core.player` had a global unique
index on the normalised name, workable while one source wrote full names and
broken the moment a second wrote abbreviations: of 88,523 names on team sheets,
2,563 resolved to an existing player. FBref says Bukayo Saka and API-Football says
B. Saka. Rather than pretend that gap is closed, the two populations are labelled
by `origin` and kept apart, FBref keeping its name-uniqueness as a partial index
over its own rows. The consequence is stated in the migration rather than hidden: a
squad list does not yet join to per-player match statistics.

The expected eleven is who has started most of a club's last ten team sheets, minus
anyone reported out. No formation is solved for — ranking by starts cannot tell a
full-back from a centre-half, and a tidier answer would not be a truer one.
Doubtful players stay in and are marked, because a doubtful first choice is likelier
to start than the twelfth man. Fenerbahce against Lyon showed it working: both
senior goalkeepers injured, so the third choice comes up with two starts from five.

Transfers are 131,700 moves, shown from the opening of the current window. The
work there is deduplication — the feed republishes a move days after announcing it,
so Bruno Guimarães joining Arsenal arrives on both 6 and 7 August.

Player names on both tables are text beside a nullable `player_id`.
`core.player.norm_name` is unique and these feeds bring in names from squads that
were never loaded as entities, so requiring a resolved id would mean either dropping
the data or inventing rows to hold it. Inventing entities to satisfy a display is
how a player table fills with duplicates — which is a mistake this project has
already made with clubs, twice.

## Shrinkage, found by looking at a page

The Liga Portugal fixture list priced newly promoted Académico de Viseu at 89% to
beat Santa Clara and 58% to beat Porto. No log-loss table said anything was wrong.

Time decay was doing it. A match last week has weight 1.0 and one from 2014 has
0.0004, so a promoted club's single game has full weight with nothing older to pull
against it, and the fit explains that one game as well as it can. Académico de
Viseu came out with a stronger attack than Benfica on 0.99 effective matches.

Attack and defence are now shrunk toward the league average, scaled per effective
match — the same treatment, for the same stated reason, that the count models
already gave referee effects. Strength chosen on 2022-24 and confirmed on 2024-26,
which was not used to choose it: it improves eight of the nine leagues with odds
and costs England 0.0007, England having the most history and least turnover and so
the least to gain. The optimum is interior, so it is a minimum rather than the edge
of the range searched. `docs/10-strength-shrinkage.md` has the tables.

Viseu's attack went from +1.18 to +0.35 while Porto's moved +0.51 to +0.47, which
is the test of whether a penalty is doing the right thing: barely touch the clubs
with fifty effective matches, move the one with a single match a long way.

Refitting also exposed a display bug worth recording. `ml.model` keeps every
version deliberately — no silent retraining — and `public.prediction` was showing
all of them, so changing the model duplicated 6,693 published rows and a match page
listed "over 2.5" twice with two different percentages. The view now publishes the
most recent version per market, with the complement rows derived after
deduplication so an "under" can never be the complement of a different version's
"over".

## Does it beat the bookmaker?

No, and now that is measured in nine leagues rather than one. Walk-forward 1X2
log-loss from 2022/23, against de-vigged closing odds:

| League | Base rate | Dixon-Coles | Market | Gap closed |
|---|---|---|---|---|
| Netherlands | 1.07047 | 0.96025 | **0.93356** | 81% |
| Portugal | 1.06761 | 0.92727 | **0.90085** | 84% |
| Turkey | 1.06552 | 0.98280 | **0.94841** | 71% |
| England | 1.06711 | 0.98565 | **0.96031** | 76% |
| Spain | 1.06196 | 0.97988 | **0.95972** | 80% |
| Italy | 1.08688 | 0.98773 | **0.96864** | 84% |
| Germany | 1.07387 | 0.99480 | **0.96986** | 76% |
| France | 1.07107 | 0.99963 | **0.97810** | 77% |
| Belgium | 1.07532 | 1.00636 | **0.98833** | 79% |

The market wins everywhere. What the model does reliably is close 71–93% of the
distance between a naive base rate and what the bookmaker knows, and it does that
consistently enough across nine independent leagues that the number is a property
of the model rather than of any one competition. Portugal has the lowest absolute
log-loss because the league is more predictable, not because the model is better
there — which is why the gap-closed column is the one to read.

This is the honest ceiling on the goals markets. The count markets have never
been compared to a bookmaker at all, because football-data.co.uk publishes no
odds for corners, fouls or shots, so "books price those lazily" remains the
central untested assumption of the project rather than a finding.

## Competitions

Nine leagues are loaded. The Eredivisie, Liga Portugal and Süper Lig were added
because football-data.co.uk publishes the same columns for them as for the
original five — shots, corners, fouls, cards and Pinnacle closing odds — so every
model applies unchanged. Detailed statistics begin in 2017/18 rather than 2014/15,
so the count markets train on nine seasons there instead of twelve; results and
odds go back the full twelve.

They are not published yet, and the reason is a limitation this exposed rather
than anything wrong with them. Walk-forward, from 2022/23:

| Market | Netherlands | Portugal | Turkey |
|---|---|---|---|
| Shots, per team (4.5/12.5) | 14.2%, cal 4.6% | 17.9%, cal 9.3% | 6.8%, cal 8.2% |
| Corners, home | 6.2%, cal 6.8% | 10.3%, cal 9.7% | 1.6%, cal 5.8% |
| Fouls, match total | 4.0%, cal 7.5% | 6.1%, cal 3.6% | 1.6%, cal 5.6% |
| Cards, match total | -0.1% | 0.2% | 0.4% |

Portugal's 17.9% on per-team shots is the largest gain anywhere in the project.
But `ml.market.status` carries one verdict per market for *all* competitions,
while the evidence is per league and per line. Shipping per-team shots globally
would publish Portugal at 9.3% and Turkey at 8.2% calibration error, both outside
the standard that holds cards back. So the registry needs a competition dimension
before any of this can go on the page, and until it does these leagues are loaded
and validated but not predicted.

Cards coming out at roughly zero in all three is a useful confirmation rather
than a disappointment: none of these leagues has referees loaded yet, and the
referee term is what carries cards where it carries them at all.

### Belgium, and the two-phase format

Belgium is now loaded in full, 3,285 matches. It used to stop at 2022/23 because
from 2023/24 the league plays a 240-match double round robin and then splits into
championship, Europa and relegation playoffs in which all sixteen clubs meet
opponents they have already played. Seventy-two pairings a season collided with a
natural key that assumed one meeting per pairing.

`core.match.stage` is the fix, and it is a widening rather than a change: every
existing row is `regular`, so nothing already stored moved. The phase is inferred
from the fixture list rather than declared by the source, on the rule that a
double round robin gives each ordered pair exactly one meeting, so a second
meeting is a second phase. Two independent checks say the rule reads the format
rather than a coincidence — the regular phase is a perfect 240-match round robin
in each affected season, and no regular fixture falls after the first playoff
one. Run across all nine leagues it marks Belgium's 215 playoff matches and
nothing else.

**Modelling the phases separately was measured and rejected.** The obvious design
is one model for the regular season and another for the playoff, and the data
does not support it. Comparing each club against itself across 48 team-seasons,
no statistic differs by more than about two standard errors — goals, corners,
fouls, cards and shots are all indistinguishable between phases. Walk-forward,
the model predicts playoff matches 0.028 of log-loss worse, which is 1.0 standard
error, so no difference is detectable at all. A separate fit would also be
starved: 215 playoff matches cannot support the 32 team parameters it would need.
One fit over both phases is the right answer, and the value of `stage` is that it
lets the fixtures be *stored*, which was the actual blocker.

Adding the missing seasons moved Belgium's own numbers. It previously appeared to
close 93% of the market gap, the best of any league; over the full history it
closes 79%, in line with everywhere else. The old figure was measured on a
truncated, easier period, which is a fair warning about reading one league's
number in isolation.

### Five more from API-Football

Fourteen competitions are now loaded, 49,524 played matches. Bulgaria, the Czech
league, Eliteserien and both UEFA club competitions come from API-Football, the
first paid source here, bought because neither free source could cover them:
football-data.co.uk does not publish any of the five, and FBref publishes them
but exposes no corner count per match.

It gives more per match than football-data.co.uk does for the original nine —
corners plus possession, passes, shots split inside and outside the box, and
expected goals. It gives no usable odds at all: prices live for seven days with
no archive, so these five can never be scored against a closing line. Whether the
model beats a bookmaker is unanswerable for them, permanently.

Statistic coverage is uneven and the provider's own season-level flag does not
predict it — that flag means "some fixture here has statistics", not all of them.
Measured: Norway 100%, Czech 85%, Champions League 81%, Bulgaria 76%, Europa
League 67%, the last dragged down by qualifying rounds. Goals are unaffected
everywhere, coming from the fixture record.

Walk-forward from 2022/23, against a rolling benchmark:

| | Bulgaria | Czech | Norway |
|---|---|---|---|
| 1X2, gain over base rate | 9.5% | 9.7% | 6.7% |
| Shots, per team | 23.8%, cal 8.2% | 11.0%, cal 9.7% | 10.6%, cal 6.8% |
| Corners, home | 8.1%, cal 5.8% | 3.5%, cal 9.8% | 5.9%, cal 4.9% |
| Fouls, match total | 1.0%, cal 17.9% | 2.6%, cal 9.2% | 6.6%, cal 12.3% |
| Cards, match total | -0.2% | 4.0% | insufficient data |

The goals model transfers cleanly to all three. The count markets are noisier than
in the established leagues and the samples are small — 315 to 704 matches against
several thousand elsewhere — so Bulgaria's 23.8% on per-team shots should be read
as encouraging rather than believed. Fouls calibrate badly everywhere here, and
cards carry nothing, which is consistent with cards needing referee variation the
model can see.

### Two clubs, one team, twenty-two times

Barcelona held 115 Champions League appearances under one team id and 494 league
matches under another. So did Sevilla, Tottenham, Inter, Villarreal, Marseille,
Lyon and sixteen more: two identities per club, created months apart by the
domestic loader and the UEFA loader. 815 matches sat detached from the record that
explains them, so anything reading across competitions saw a club with no league
history playing one with no European history and priced both as unknowns.

It surfaced sideways. Linking Premier League fixtures to provider ids reached 210 of
380 with every club aliased, which made no sense until the alias turned out to point
at `Newcastle` while the fixtures belonged to `Newcastle United`.

The lesson is about which detector to trust. Fuzzy name matching found 20 of the 22
and produced 8 false positives at identical scores: Rangers scored a perfect 1.00
against Queens Park Rangers, Arsenal Tula against Arsenal, Atlantas against
Atalanta. The metric rewards one name being a subset of the other, which is fine for
choosing among the twenty clubs in one league — the job it was written for — and
unfit for deciding identity across four thousand. Merging on it would have handed
QPR a European record.

It also missed two that no threshold can reach: `Lyon` shares no token with
`Olympique Lyonnais`, and `Stade Brestois 29` shares none with `Brest`. What found
those was Ligue 1 linking 239 of 306 fixtures. So the check that stays is coverage,
in `footy freshness`: every league must link 95% of its fixtures to provider ids. It
would have caught all 22 without anyone thinking to look, and it does not care why
two records disagree — only that a fixture found no partner, which is the actual
symptom. The merge lists themselves stay hand-checked.

None of it is publishable yet regardless, for the same reason the three
football-data leagues are not: one verdict per market covers all competitions.

### Where the remaining competitions would come from

FBref lists 158 competitions and covers the Czech First League, Eliteserien, the
UEFA Champions League and the UEFA Europa League — under those exact names, which
is worth stating because none of the obvious guesses matched. **Bulgaria is not
among them.** It is absent from football-data.co.uk too, so the efbet League needs
either a paid feed or a Sofascore scrape; there is no free, reliable source in the
stack today.

Eliteserien is on football-data.co.uk as well, but with results and closing odds
only and no shots, corners, fouls or cards, so from that source it supports the
goals markets alone.

The Champions and Europa Leagues remain a modelling problem rather than a loading
one. Attack and defence are centred within a competition, so an English rating and
a German rating are not on a common scale and the model cannot price Arsenal
against Bayern at all. That needs a cross-league rating, and ClubElo — already
loaded, 250k rating periods — is the obvious candidate. The `stage` column is a
prerequisite that is now in place, since a group stage and a knockout round can
pair the same clubs twice.

## Sources

| Data | Source | Cost | Coverage | Status |
|---|---|---|---|---|
| Results, shots, corners, fouls, cards, odds | football-data.co.uk | Free | 2014+, all 12 seasons | Implemented |
| Referees | FBref schedule | Free | 2014+, all five leagues | Implemented |
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
