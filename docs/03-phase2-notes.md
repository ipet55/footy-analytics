# Phase 2 notes

Running log of what Phase 2 has established. The plan is in `01-roadmap.md`.

## Dixon-Coles is now fast enough to tune

The goals model got the same analytic-gradient treatment as the count models: a
Premier League walk-forward backtest went from **8m37s to 19.6s**, reproducing
0.98583 to five decimal places. Two things follow. Hyperparameters can now be
examined at all, and the live prediction path in Phase 6 can refit on demand
rather than on a schedule.

The rho correction was the delicate part. It applies to four scorelines only and
enters through both Poisson rates at once, so `tests/test_dixon_coles.py` checks
the gradient at several values of rho including zero, where the correction's
derivative vanishes and a sign error would leave no trace.

## Per-league time decay: tested and rejected

The count models all wanted to forget faster than the goals model's 0.0018, so
the obvious question was whether goals wanted a per-league rate too. Scored on
the test period alone, the answer looked like yes and the leagues disagreed
sharply — England appeared to want 0.0035 while Spain and Germany wanted 0.0010.

That is exactly the shape of a result that is about to waste a week. Choosing a
setting by its score on the period you then report is not walk-forward
validation; the choice has seen the answer. `backtest` therefore gained a
`--test-to` flag, the rate was selected on 2019–2022, and the selection was
applied to 2022–2026 without further adjustment:

| League | Selected on 2019–22 | Test log-loss | At global 0.0018 | Effect |
|---|---|---|---|---|
| ENG-PL | 0.0018 | 0.98583 | 0.98583 | unchanged |
| ESP-LL | 0.0026 | 0.98261 | 0.97993 | worse |
| ITA-SA | 0.0026 | 0.98891 | 0.98841 | worse |
| GER-BL | 0.0010 | 0.99427 | 0.99562 | better |
| FRA-L1 | 0.0026 | 1.00127 | 0.99992 | worse |

Worse in three leagues, better in one, net negative. The validation window also
picked a different rate than the test window did for Spain (0.0026 against
0.0010), which is the tell: the surface is flat and its minimum wanders between
periods. The per-league differences were noise dressed up as structure.

**The goals model keeps a single global 0.0018.** Recorded because the negative
result is the useful part — without the held-out window this would have shipped
as a per-league improvement and quietly made four leagues worse.

Note the contrast with the count models, where the decay change was kept: there
the effect was large (worst-bucket errors halving), consistent in direction
across leagues, and mechanically explicable. That is what a real
hyperparameter effect looks like next to this one.

## The ml schema

Migration `0010` adds four tables and two views. The shape follows from three
things that had to be impossible.

**A prediction that cannot be reproduced.** Every row in `ml.prediction` names
the fit that produced it and carries both `p_raw` and `p_calibrated`, and every
fit's hyperparameters and coefficients are stored in `ml.model`. Because what
gets published is `sigmoid(a + b * logit(raw))`, the calibration is part of the
model rather than a diagnostic beside it, so `ml.calibration` holds `a` and `b`
per market and line. A test recomputes the published number from the stored raw
probability and those two parameters, which is what makes the table auditable.

**A market being published before it has earned it.** The Phase 1 verdicts now
live in `ml.market.status`: nine markets `shipping`, seven `held`, and
`corners_total` `rejected` with the reason recorded on the row. The prediction
code reads the registry to decide what to compute and never computes a rejected
market, so the finding cannot be undone by a forgetful flag.

**Silent retraining.** Refitting appends a row rather than updating one, so an
old prediction still resolves to the version that made it. Re-running the same
prediction does not, because a fit is identified by its training window and
hyperparameters and is looked up before it is inserted.

Settlement is a view, not a table. `ml.observation` derives the realised value
per match, statistic and scope from `core`, and `ml.prediction_scored` joins
predictions to it and resolves `hit`. Storing results a second time would create
something that can disagree with the results themselves; deriving them means the
over/under, the two team lines and the match total cannot contradict each other.
Unplayed fixtures come back with `hit = null`.

### The gap the branch found

The schema was applied to a Supabase database branch first, which earned its
keep twice. It rejected `primary key nulls not distinct` — only unique
constraints accept that, and a primary key cannot hold the null that 1X2 and
both-teams-to-score need for their absent line. More usefully, a deliberate
probe of what the constraints *allowed* found that nothing stopped a prediction
being written from a model whose training window covered that very match.

That is leakage at write time — the exact failure this project spends most of
its care avoiding — and it cannot be expressed as a check constraint, because
the kickoff is on the match and the training bound is on the fit. It is now a
trigger, `ml.assert_prediction_is_out_of_sample`, enforced on insert and on any
update that repoints a row. A leaked prediction that has already been published
has already done its damage, so this is checked on write rather than audited
afterwards.

The trigger's `search_path` is pinned empty (`0011`). With a mutable one, the
caller chooses which tables the names inside the function resolve to, so a table
called `match` placed ahead of `core.match` could feed the guard a kickoff date
of its choosing — defeating the invariant the database exists to enforce
independently of the application. Supabase's linter still reports three
pre-existing `core` functions with the same warning; they are in the ingestion
path and worth pinning separately, rather than as a side effect of this work.

## `footy predict`

Fits as of a date, predicts the fixtures that follow it, stores both
probabilities. The as-of date is explicit rather than implied by "now" so the
command can be pointed at a past matchday and its output compared with results
that are already known — which is the only way to gain any confidence in it
before the 2026/27 fixtures land.

The recalibration is derived rather than assumed. Publishing `p_raw` would put
numbers on the page that are wrong by up to ten points at the extremes, so
`predict` replays the walk-forward over the preceding two seasons and keeps the
corrections it ends on, reusing the backtest itself rather than a
reimplementation of it. The slopes it derived independently for Premier League
corners were 0.47–0.67 — the same compression Phase 1 measured, which is a
reassuring consistency check on both.

Goals are stored with the **identity** calibration and `n_observations = 0`,
recorded explicitly rather than left absent. No goals recalibration has been
measured: Dixon-Coles prices every goals market off one score matrix and came
within four log-loss points of the closing line, so there is no evidence of the
overconfidence the count models showed. That is an absence of evidence rather
than evidence of absence, and measuring it is the obvious next job. Note that
`ml.calibration` is keyed by market and line, not by selection, which is
adequate for the identity but would need revisiting for a real 1X2 correction,
since home, draw and away could want different slopes and would then have to be
renormalised to sum to one.

One property worth its test: each line is recalibrated by its own two
parameters, and nothing in that transformation knows about the lines either
side. Monotonicity across lines — P(over 5.5) never exceeding P(over 4.5) —
therefore holds by luck of similar fitted slopes rather than by construction, so
`tests/test_predictions.py` checks it on every stored row.

## Still to do in this phase

- Measure whether the goals markets need recalibration, instead of assuming the
  identity.
- The gradient-boosting blend over the feature layer. None of the four count
  models currently use a single feature from `features` — no rest days, no
  congestion, no opponent-strength weighting — so this is where the next real
  improvement should come from rather than from more tuning.
- Purpose-built views in `public` for the application to read, filtered to
  `status = 'shipping'`. The `ml` schema is not exposed to clients.
