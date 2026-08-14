# Shrinking attack and defence toward the league average

Found by looking at a page rather than at a metric. The Liga Portugal fixture
list priced Académico de Viseu, newly promoted, at 89% to beat Santa Clara at
home and 58% to beat Porto. Nothing in the log-loss tables said anything was
wrong.

## What was happening

The goals model weights a match by `exp(-xi * days_ago)` with `xi = 0.0018`. A
game played last week has weight 1.0; one from 2014 has weight 0.0004. That is
the point of time decay and it is right — a squad from a decade ago is a
different team.

It has a consequence nobody had looked for. A promoted club has played one match
in the league, and that match has full weight. There is nothing older to pull
against it, so the fit explains that single game as well as it can:

| Club | Effective matches | Attack |
|---|---|---|
| Académico de Viseu | 0.99 | **+1.18** |
| Benfica | 49.05 | +0.69 |
| Sporting CP | 49.03 | +0.79 |
| Porto | 49.02 | +0.51 |

A club with one game had the strongest attack in Portugal. It was priced to score
3.67 at home where Porto would score 1.88.

Clubs long gone from the league — Penafiel at 0.02 effective matches — do not
misbehave, because their weight is too small for the likelihood to care and they
stay near where the sum-to-zero constraint puts them. The damage is done at
around one effective match: enough to move the parameter, not enough to be worth
believing.

## The fix

An L2 penalty pulling attack and defence toward the league average, scaled per
effective match so it means the same in a league with a decade of history as in
one with two seasons.

The count models already do exactly this for referee effects, and the reasoning
there transfers word for word: some officials appear a handful of times and their
raw averages are noise. The goals model simply never had the equivalent.

## Choosing the strength

Chosen on 2022/23–2023/24 and reported on 2024/25–2025/26, which was not used to
choose it. Mean 1X2 log-loss across the nine leagues with odds:

| Strength | Choosing window | Reporting window |
|---|---|---|
| 0.00 | 0.97369 | 0.98719 |
| 0.02 | 0.97202 | 0.98557 |
| 0.05 | 0.97138 | 0.98491 |
| **0.10** | **0.97094** | **0.98452** |
| 0.20 | 0.97100 | 0.98463 |
| 0.40 | 0.97278 | 0.98627 |

Two things make this trustworthy rather than a lucky pick. The optimum is
interior — 0.20 and 0.40 are both worse — so it is a minimum and not the edge of
whatever range happened to be searched. And the setting chosen on the first window
is also the best available on the second, which it never saw.

Per league on the reporting window, 0.10 against no shrinkage:

| League | None | 0.10 |
|---|---|---|
| Netherlands | 0.98368 | **0.97587** |
| Belgium | 1.02383 | **1.01910** |
| Germany | 0.99966 | **0.99603** |
| Spain | 0.97918 | **0.97579** |
| Turkey | 0.98044 | **0.97825** |
| France | 0.98589 | **0.98443** |
| Italy | 0.98265 | **0.98188** |
| Portugal | 0.94129 | **0.94059** |
| England | **1.00810** | 1.00875 |

Eight of nine improve. England is 0.0007 worse, and that is the expected shape
rather than a puzzle: it has the most history and the least turnover, so it has
the least to gain from being told not to trust a small sample. The leagues that
gain most — the Netherlands and Belgium — are the ones with the most promotion
and relegation churn in the data.

## What it did to the fixture that started it

| | Before | After |
|---|---|---|
| Académico de Viseu attack | +1.18 | +0.35 |
| Expected goals at home to Santa Clara | 3.67 | 1.66 |
| Home win against Santa Clara | 89% | 58% |
| Home win against Porto | 58% | 27% |

Porto's own attack moved from +0.51 to +0.47 and Benfica's from +0.69 to +0.64,
which is the test of whether the penalty is doing the right thing: the clubs with
fifty effective matches are barely touched, and the one with a single match is
moved a long way.

## Reproducing

```bash
pytest tests/test_dixon_coles.py -k gradient
python scripts/tune_shrinkage.py
```

The gradient test is the one that matters. The penalty's derivative has to travel
through the sum-to-zero constraint on attack, where the pinned team's parameter is
minus the sum of the others, so its share of the penalty reaches every free
parameter with the opposite sign. Getting that wrong does not raise anything; it
quietly fits a slightly different model from the one written down. It is checked
at strengths of 0, 0.10 and 0.20 against finite differences.
