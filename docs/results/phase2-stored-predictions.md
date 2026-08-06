# Stored predictions: May 2026, all five leagues

Produced by fitting as of 2026-05-01 and predicting the 31 days that follow, for
each league in turn:

```
footy predict --competition ENG-PL --as-of 2026-05-01 --days 31
```

187 fixtures, 40 fits, 10,098 predictions. (The database also holds a 10-fixture
Premier League run fitted as of 2026-04-10, from testing the command; the
measurements below are over everything settled, so it is included there.) This
is an end-to-end check of the
`ml` schema and `footy predict` on real fixtures whose results are known. It is
**not** a substitute for the Phase 1 walk-forward, which covers four years and
is the authority on whether these markets work; one month is far too short to
judge a model on, and the reason for saying so is below.

## Recalibration improved every count market

Log-loss on the stored predictions, calibrated against raw:

| Market | raw | published | improvement |
|---|---|---|---|
| fouls_away | 0.67464 | 0.60815 | **-0.06649** |
| shots_away | 0.57650 | 0.55665 | -0.01985 |
| cards_total | 0.62258 | 0.60726 | -0.01532 |
| fouls_home | 0.61279 | 0.59926 | -0.01353 |
| corners_home | 0.65274 | 0.63947 | -0.01327 |
| shots_total | 0.59771 | 0.59019 | -0.00752 |
| cards_away | 0.53959 | 0.53241 | -0.00718 |
| corners_away | 0.58833 | 0.58408 | -0.00425 |
| fouls_total | 0.58599 | 0.58205 | -0.00394 |
| cards_home | 0.52061 | 0.51966 | -0.00095 |
| shots_home | 0.54464 | 0.54419 | -0.00045 |

Eleven markets, eleven improvements, and none made worse. The goals markets are
stored with the identity calibration by design, so their two columns are equal.

## The biases are league drift, not broken models

Several markets are off by more than Phase 1's worst-bucket figures would
suggest — published 56.4% against an actual 64.3% for `shots_home`, and +4.5
points the other way on `fouls_total`. Before reading that as a defect, note
what the league was doing that month:

| Statistic | May 2026 | Rest of 2025/26 | 2014–2025 | Bias direction |
|---|---|---|---|---|
| fouls | 22.57 | 23.61 | 25.19 | over-predicted (+4.5pp) |
| cards | 3.90 | 4.11 | 4.30 | over-predicted (+4.0pp) |
| shots | 25.88 | 25.07 | 24.65 | under-predicted (-5.7pp) |
| goals | 2.83 | 2.76 | 2.77 | under-predicted (-1.9pp) |
| corners | 9.74 | 9.54 | 9.87 | roughly unbiased (+2.2 / -4.8pp) |

Every notable bias points the same way as the drift. Fouls and cards have been
falling for a decade and the models, carrying that decade with a 173-day
half-life, still sit above where the league now is. Shots have been rising and
the models sit below. Corners, which have barely moved, are the market whose
bias has no consistent sign.

So this is a **level** error inherited from the training history, not a failure
to tell fixtures apart — which is the same phenomenon that made Phase 1 replace
the static base rate with a rolling one. It is also why one month of stored
predictions cannot settle anything: with roughly 190 fixtures, and several lines
per fixture moving together, the effective sample is small enough that a
four-point bias is around one standard error even before the drift is counted.

Two things follow, both for later:

- A league-season level term, or a faster decay on the intercept alone than on
  the team parameters, would attack this directly. Note that plain "decay
  faster" is already ruled out: Phase 1 tuned the decay walk-forward and 0.0040
  won. The level and the team strengths appear to want different rates, which is
  a more specific hypothesis than the one that was tested.
- The recalibration absorbs part of it and is fitted on a two-season replay. A
  shorter calibration window would track drift faster at the cost of a noisier
  correction, and the trade-off has not been measured.
