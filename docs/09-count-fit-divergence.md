# The per-team count models were returning fouls rates of 1e12

Written 2026-08-11, found while building the style-of-play test (`docs/08`). A
one-line bug in the count model's starting point had been silently wrecking the
per-team fouls and shots models in four leagues out of five since Phase 1.

Nothing raised. No test failed. The match-total markets, which are what ships,
were never affected. But every per-team fouls and shots number ever reported here
was measured against a model that was broken for part of the walk.

## The symptom

Building style features for fouls meant fitting the per-team count model
fortnightly and reading off its rates. The Poisson correction refused to fit at
all: its objective evaluated to 1.16e10 where it should have been about 15,000.

The rates behind that: median 10.7 fouls, as expected — and a maximum of
**4.6e16**. Across a single league's walk, 155 of 2,992 fitted rates were above
100 fouls for one team in one match.

Sampling eight refit dates per league between 2019 and 2025:

| Statistic | Leagues affected | Worst rate | Attacks pinned at their bound |
|---|---|---|---|
| Fouls | 4 of 5 | 1.03e12 | up to 12 per fit |
| Shots | 2 of 5 | 6.83e6 | up to 9 per fit |
| Cards | 0 of 5 | 4.92 | none |
| Corners | 0 of 5 | 11.8 | none |

One bad refit poisons every fixture until the next one, so a single diverged fit
is a month of nonsense predictions.

## The cause

The per-team model is `rate = exp(attack_i + concede_j + home_advantage)`. That
parameterisation is redundant — adding a constant to every attack and subtracting
it from every concede leaves all rates unchanged — so attack is pinned to sum to
zero to identify it.

Which means **attack cannot carry any of the overall level.** Concede has to
carry all of it. The starting point gave it half:

```python
np.full(n, np.log(max(home_counts.mean(), 0.5)) / 2)   # concede starts here
np.zeros(n - 1)                                        # attack starts here
```

For fouls that starts every rate at exp(1.19) = 3.3 against a true mean of 10.7.
The optimiser has to find the missing 1.2 in log space, and the sum-to-zero
constraint forbids it from lifting all the attacks together to get it. So it
lifts *some* of them, into their bounds, while relegated teams — which time decay
leaves with effectively no weight, and which the data therefore says nothing
about — drift the other way to satisfy the constraint. L-BFGS-B then reports
successful convergence at a corner of the box with attack and concede both jammed
against their upper bounds, and `exp(3 + 5)` is 3,000 fouls.

Two things made this invisible for months:

- **It only bites when the mean is large.** Cards average 1.7 and corners 5.4, so
  half of the level is close enough to start from and the fit converges normally.
  Fouls average 10.7 and shots 12.7. Three of the four markets were fine, and the
  two that were not are the two nobody was reading per-team numbers off.
- **The match totals were never affected.** `fit_total` has an explicit intercept
  that carries the level, so its tempo parameters start at zero legitimately.
  Every shipped market runs through that path.

## The fix

Concede starts at the whole level rather than half of it, taking the mean over
both sides rather than the home side alone:

```python
level = np.log(max((home_counts.mean() + away_counts.mean()) / 2, 0.5))
```

After it, across the same 40 sample fits: no attack anywhere within 0.01 of its
bound, and the largest rate in any league for any statistic is 30.3 shots. Cards
and corners come out numerically identical to before, which is what a start-point
change should do where the fit was already converging.

## The regression test

`test_fitted_rates_stay_near_the_data_whatever_its_level` sweeps the four
statistics' levels and asserts that fitted rates stay within a factor of five of
the observed mean and that no attack reaches its bound.

Getting this test to fail on the old code took two attempts, and the reason is
the interesting part. Synthetic data with twelve teams that all play throughout
passes on the broken code: every parameter is identified, so nothing drifts and
the constraint has slack. The test only reproduces the bug once the synthetic
league has **relegated teams** — sides that appear only in the earliest seasons,
which time decay reduces to a weight of 0.014 against 18.8 for a current team.
Unidentified parameters bound by a constraint are what drag the identified ones
into the bounds.

So the test data generator models a decade of promotion and relegation, and the
test is parameterised over all four statistics' means rather than just fouls,
because at a mean of 1.7 the bug is genuinely absent and a single fixture would
have proved nothing.

## What it changes

Recalibrated gains over the rolling benchmark, before and after, at the
`test_from = 2022-07-01` walk:

| Market | Before | After |
|---|---|---|
| Fouls, match total (all leagues) | 5.2-7.1% | **unchanged to four decimals** |
| Cards and corners, all scopes | — | unchanged within 0.3 points |
| Fouls, per team, ENG-PL home | 0.37-1.32% | **2.24-4.38%** |
| Fouls, per team, ESP-LL home | 0.41-6.50% | **2.55-9.35%** |
| Shots, per team, ESP-LL home | 4.52-9.59% | **7.02-10.64%** |

Nothing already published needs revising downward: the totals are bit-identical
and no per-team fouls or shots market was ever shipping. What changed is that a
market previously dismissed as noise now looks real.

**Per-team shots**, recalibrated, after the fix:

| League | Min gain | Mean gain | Worst reliability bucket |
|---|---|---|---|
| ENG-PL | 8.99% | **10.10%** | 9.7% |
| FRA-L1 | 4.45% | 6.81% | 14.8% |
| ESP-LL | 3.46% | 6.72% | 4.7% |
| ITA-SA | 3.54% | 5.71% | 13.3% |
| GER-BL | 1.44% | 4.98% | 8.3% |

Every gain in every league at every line is now positive, against a documented
0.3-7.6% before. This is comfortably the strongest signal in the project outside
fouls totals — England's 10.1% mean beats fouls totals' 5.4-6.5%.

It still does not ship, and the reason is calibration rather than signal: France
at 14.8% and Italy at 13.3% worst-bucket error are well outside the standard that
held cards back at 9.4%. Per-team fouls does not ship either, on signal as well
as calibration — Germany is still negative at the 8.5 line (-1.81%) and worst
buckets reach 19.5%.

So the honest summary is that the fix promoted per-team shots from "no signal" to
"real signal, percentages not yet publishable", which is the same place cards
sits. That is a recalibration problem, and a well-defined next piece of work.

## Reproducing

```bash
pytest tests/test_counts.py -k level
footy backtest-counts --stat fouls --competition ESP-LL
footy backtest-counts --stat shots --competition ENG-PL
```
