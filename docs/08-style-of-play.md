# Style of play: measured well, worth nothing

Written 2026-08-11. The roadmap's Phase 5 asked whether *how* a team plays adds
to *how well* the model thinks it plays — pressing intensity, territorial
penetration, high-press against build-up. Tested across three markets and forty
held-out league-seasons: **it does not, in any form tried.**

This is the fourth feature idea to be built, measured and rejected here, and the
most informative of them, because for once the data is beyond reproach. The
failure is not a measurement failure and it comes with an explanation.

## The measures are excellent

Two Understat columns, both at 100% coverage on full-time rows in all five
leagues from 2014-15 to 2025-26 — 43,178 team-matches:

- `ppda`: passes the opponent completes per defensive action. Low means a high
  press. Right-skewed at 4.24, so the log is used throughout, which brings it to
  0.35.
- `deep_completions`: passes completed within roughly 20 metres of goal.

Before modelling anything, the question of whether these are traits or noise.
Split-half reliability within a team-season, odd matches against even, over 1,170
team-seasons, Spearman-Brown corrected:

| Measure | Split-half r | Full-measure r |
|---|---|---|
| Deep completions | 0.871 | **0.931** |
| Pressing | 0.828 | **0.906** |
| Fouls | 0.808 | 0.894 |
| xG | 0.752 | 0.858 |

And pressing persists from one season to the next at **r = 0.731** over 922
team-season pairs.

That is the test per-team home advantage failed outright (`docs/05`): there, the
thing being measured did not exist from one year to the next. Here it plainly
does. Whatever goes wrong below is not the data.

## The test

The same harness as squad strength (`docs/06`), and deliberately so — a
multiplicative correction on the fitted rate, one shared pair of coefficients per
feature across home and away, with the plain model as the special case where
every coefficient is zero:

    home rate = model_rate * exp(a + b1*press_home + b2*press_away + ...)
    away rate = model_rate * exp(a + b1*press_away + b2*press_home + ...)

Two things learned from the squad-strength retraction are built in.

**The holdout is wide.** Style data reaches back to 2014-15 in every league, so
this is eight held-out seasons in five leagues — **forty league-seasons** — where
squad strength had three, in one league. Features come from a twenty-match
window, long because a stable trait is limited by estimation noise rather than by
staleness.

**Significance is clustered.** League-seasons are not independent trials: styles
persist across seasons and the same fixture round appears in every league at
once. Every gain below is tested twice, clustering by season and by league, and
the weaker reading is the one reported.

Point-in-time correctness is structural, as in `squad`: matches are walked in
order, features are read off the state accumulated so far, and only then is the
match folded into that state. Two leakage tests assert that appending future
matches cannot change any earlier feature.

## The results

Held-out gains, pooled over forty league-seasons. Positive means style helped.

**Goals (1X2 log-loss), plain model 0.9898:**

| Variant | Params | Gain | p (season) | p (league) | Seasons won |
|---|---|---|---|---|---|
| intercept only | 1 | -0.0002 | 1.00 | 0.95 | 15/40 |
| press | 3 | -0.0001 | 0.92 | 0.88 | 19/40 |
| deep completions | 5 | +0.0000 | 0.52 | 0.51 | 17/40 |
| all three | 7 | -0.0002 | 0.75 | 0.65 | 16/40 |
| recent shift | 5 | -0.0007 | 0.98 | 0.94 | 18/40 |

**Fouls (log-likelihood per team-match), plain model 2.6902:**

| Variant | Gain | p (season) | p (league) | Seasons won |
|---|---|---|---|---|
| intercept only | -0.0000 | 0.52 | 0.52 | 21/40 |
| press | -0.0005 | 0.70 | 0.80 | 19/40 |
| deep completions | -0.0010 | 0.75 | 0.81 | 17/40 |
| all three | -0.0020 | 0.93 | 0.98 | 14/40 |
| recent shift | **+0.0005** | 0.36 | 0.29 | 21/40 |

**Cards, plain model 1.7185:**

| Variant | Gain | p (season) | p (league) | Seasons won |
|---|---|---|---|---|
| intercept only | -0.0004 | 0.97 | 0.99 | 14/40 |
| press | -0.0010 | 1.00 | 1.00 | 10/40 |
| deep completions | -0.0014 | 1.00 | 0.98 | 12/40 |
| all three | -0.0019 | 1.00 | 0.99 | 8/40 |
| recent shift | -0.0007 | 0.97 | 0.99 | 15/40 |

Nineteen of forty seasons won is a coin flip, and that is the *best* of the
level variants on goals. No league carries a consistent effect: the per-league
pressing gains on goals run -0.0003 to +0.0001, with the sign varying by league
and by season within league.

The one directionally positive cell is the recent-shift variant on fouls,
+0.0005 in 21 of 40 seasons at p = 0.29 clustered by league. It is the variant
the mechanism predicts, which is the only reason it is worth naming — but a
p-value of 0.29 on the most favourable of fifteen cells tested is what noise
looks like, and it does not move the market it would have to move: the gain at
the over-10.5 fouls line is -0.0001.

## Why it fails, and why the failure makes sense

Note the shape of the tables: **every added parameter makes it worse, in order.**
On cards, going from one parameter to seven takes the gain from -0.0004 to
-0.0019, monotonically. That is the signature of variance with no bias to trade
against it — the features are not fighting the model and losing, they are adding
nothing at all and paying for the privilege.

The reason is the same property that made the measures look so promising. Style
is a *stable* trait, r = 0.73 from season to season. Dixon-Coles fits each club
an attack rating and a defence rating over a decade of matches, and the count
models fit each club a rate for producing fouls and a rate for conceding them.
A team that has pressed hard for five years has been having its pressing
absorbed into those ratings for five years. Restating it as a feature is close to
regressing on a linear combination of parameters the model already has.

The measures are informative about football and uninformative about the residual,
which is the only thing a correction can use. Reliability and predictive value
are different questions, and this is the cleanest example of the gap between them
in the project so far.

That reasoning has a testable consequence, which is where the recent-shift
variant came from: what a decade-long rating *cannot* absorb is a team that has
just changed how it plays. Recent form against the team's own baseline is
orthogonal to the level by construction. It was tested for that reason and it
failed too — though it is the only variant that failed less badly than the levels
on fouls, and if any part of this is ever revisited, that is where to look, with
a manager-change flag rather than a rolling delta.

## What this closes

Phase 5 of the roadmap is answered and closed. Specifically **not** worth doing:

- Style interaction features in a GBM (high-press against build-up). The main
  effects carry nothing; interactions between two things that carry nothing are
  a larger version of the same bet, and the blend already lost this argument once
  in `docs/04`.
- Buying possession or passing data to extend the style vector. The constraint is
  not the breadth of the style description; it is that team ratings already price
  stable traits. Better style data would measure the same absorbed thing better.

The features and both harnesses are kept, because a negative result is only worth
having if it can be re-run when something changes:

```bash
footy style-check                            # goals, five leagues, eight seasons
footy style-counts-check --stat fouls        # and --stat cards
```

## A note on what this investigation did find

The style test itself is a null result, but building it surfaced a real bug: the
per-team count models were diverging and returning fouls rates in the billions in
four leagues out of five. See `docs/09`. That was worth more than the feature
would have been.
