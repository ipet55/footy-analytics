# Per-team home advantage: measured, and rejected

Written 2026-08-09, prompted by a question that deserved a real answer rather
than a plausible one: the model applies a single home advantage to the whole
league, so what about the side that is a fortress at home and a pushover away?
Sunderland conceded roughly a goal a game last season, but not evenly.

The answer is that the question is right about the model and wrong about the
world. The gap is real — the model genuinely cannot express a team-specific home
effect — but filling it makes predictions worse, because a team's home/away
split does not persist from one season to the next.

The code stays in the tree (`venue_penalty` on `dixon_coles.fit` and
`backtest.run`, off by default) so this can be re-run rather than re-argued.

## What the model already does

Worth separating from the venue question, because they get conflated. Opponent
strength is not an add-on to the goals model, it *is* the goals model:

    home rate = exp(attack_home + defence_away + home_advantage)
    away rate = exp(attack_away + defence_home)

Fitted by maximum likelihood over a decade, so a team's rating is inferred from
who it actually played. Raw averages never enter. Chelsea's expected away goals
against four opponents, fitted to 2025-26 through May:

| Opponent | Chelsea xG away | Opponent defence |
|---|---|---|
| Arsenal | 0.90 | -0.434 |
| Liverpool | 1.24 | -0.117 |
| Leeds United | 1.61 | +0.144 |
| Burnley | 1.97 | +0.345 |

A 2.2x swing driven entirely by the opponent. The count models have the same
shape, with `concede` in place of `defence`, so corners and cards are
opponent-adjusted too. The one exception is `fit_total`, the direct total model
for fouls and shots, which is symmetric in the two teams and carries no
opponent term — a known gap, separate from this one.

An aside worth recording, because it is counterintuitive. Over a *completed*
season, opponent adjustment barely reshuffles a league table: everyone plays
everyone twice, so the fixture list cancels and the adjusted defence ranking
moves at most two places from the raw goals-conceded ranking. It is not doing
nothing; it is doing its work per fixture, which is where predictions are made.

## The venue model

Each team gets two deviations from the league home advantage, applied only when
it plays at home — one on what it scores, one on what it concedes:

    home rate = exp(attack_home + venue_attack_home + defence_away + home_advantage)
    away rate = exp(attack_away + defence_home + venue_defence_home)

Both are shrunk toward zero by an L2 penalty. That penalty is what makes the
comparison honest: send it to infinity and the deviations vanish, so the plain
model is the venue model with the dial turned all the way down, and any
difference in log-loss is attributable to the deviations alone. It also resolves
the identifiability problem, since `venue_attack` would otherwise trade off
freely against the shared home advantage. `test_venue_terms_are_nested_inside_
the_plain_model` pins the nesting; the gradient is finite-difference checked at
two penalties.

## The result

Walk-forward over 2022-07-01 to 2024-07-01, five leagues, 3,578 matches,
refitting fortnightly. Log-loss, lower is better:

| Penalty | 1X2 | vs plain | O/U 2.5 | vs plain |
|---|---|---|---|---|
| none (plain) | 0.98751 | — | 0.67974 | — |
| 300 | 0.98753 | +0.00001 | 0.67979 | +0.00006 |
| 100 | 0.98758 | +0.00007 | 0.67992 | +0.00018 |
| 30 | 0.98788 | +0.00037 | 0.68041 | +0.00068 |
| 10 | 0.98895 | +0.00144 | 0.68173 | +0.00200 |
| 3 | 0.99137 | +0.00386 | 0.68418 | +0.00445 |

Monotonic in both markets: every amount of venue freedom hurts, and more hurts
more. The best setting is the one closest to not doing it at all. There was no
point running the held-out window, since nothing won the tuning window.

This is the same shape as the feature blend rejection, and the same lesson. A
monotonic loss curve in the direction of more flexibility is not a tuning
problem to be solved with a better penalty. It says the extra parameters are
fitting noise.

## Why: the split does not persist

The decisive test, and the one that explains the result. Fit the venue model
separately on each season, then ask whether a team's deviation in one season
predicts its deviation the next. Pooled over five leagues and ten consecutive
season pairs, 853 team-seasons:

| Parameter | Correlation season to season |
|---|---|
| attack | 0.648 |
| defence | 0.550 |
| venue attack | -0.055 |
| venue defence | -0.029 |

Overall quality persists. The home/away split does not — it is statistically
indistinguishable from zero, and marginally negative, which is what regression
to the mean looks like. Repeating this across two disjoint four-season blocks
instead of adjacent seasons gives the same answer: 0.057 and 0.152 for the venue
terms against 0.760 and 0.382 for attack and defence.

So the observed spread in home/away conceding — Arsenal +0.17 goals a game,
Bournemouth +0.49 over 2025-26 — is real as description and useless as
prediction. A team plays nineteen home games a season. That is not enough to
separate a genuine venue effect from a favourable run of home fixtures, and
whatever is left after the league-wide home advantage does not come back next
year.

## What this does not rule out

The test was on *goals*. Venue effects on cards and fouls have not been checked,
and there is a mechanism there that does not apply to goals: crowd pressure on
referees is a documented effect and referee assignment is known before kickoff.
The count models already carry a referee term for cards, which may absorb it.

It also does not rule out venue effects that are driven by something observable
rather than estimated from the team's own history — altitude, pitch dimensions,
travel distance for the visitor. Those are covariates, not free parameters per
team, and would be a different experiment.

## Reproducing

```python
from datetime import date
from footy.models import backtest as gb

gb.run("ENG-PL", test_from=date(2022, 7, 1), test_to=date(2024, 7, 1))
gb.run("ENG-PL", test_from=date(2022, 7, 1), test_to=date(2024, 7, 1), venue_penalty=30.0)
```
