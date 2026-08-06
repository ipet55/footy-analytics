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

## Still to do in this phase

- `ml.model`, `ml.prediction`, `ml.outcome`, and the recalibration parameters
  stored per market and model version — a published probability is not
  reproducible without the calibration that produced it.
- `footy predict` writing the full probability table per fixture.
- The gradient-boosting blend over the feature layer. None of the four count
  models currently use a single feature from `features` — no rest days, no
  congestion, no opponent-strength weighting — so this is where the next real
  improvement should come from rather than from more tuning.
