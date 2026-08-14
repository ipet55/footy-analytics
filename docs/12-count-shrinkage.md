# Shrinking the count models, and being wrong about not needing to

The goals model got a penalty pulling attack and defence toward the league average
(`docs/10`). The obvious next question was whether the count models need the same,
and the answer recorded here was no.

That was wrong, and the way it was wrong is the useful part.

## The check that gave the wrong answer

Portugal was used to test it. Clubs with about one effective match came out within
15% of the league average, where the goals model had one rated at twice Porto's
scoring rate. Conclusion: the count models are structurally safer, no change
needed, do not alter a validated model without evidence.

The flaw was the sample. Académico de Viseu, Portugal's promoted club, had played
one match and that match had **no statistics** — so it was absent from the count
fit entirely and could not misbehave. The clubs that did appear at around one
effective match were established sides whose long histories had decayed, and a
decayed history still constrains a parameter. A club with one match and nothing
else does not.

## What it cost

The Eredivisie has a promoted club, Cambuur, with two matches of statistics. On
cards it was fitted to:

| | Rate |
|---|---|
| Cambuur v Den Haag | **0.009** |
| League mean | 1.59 |

A rate of 0.009 cards makes the over probabilities underflow to zero, and the
database rejects a probability of zero — so `footy refresh` failed on the
Eredivisie every run. It failed loudly, which is the only lucky part.

## The fix, and what it is not

The same L2 penalty, scaled per effective match. `concede` is penalised toward its
own mean rather than toward zero, because unlike `attack` it is not centred — it
carries the level of the statistic, so pulling it to zero would drag every team
toward one card a match, which is the bug rather than the fix.

Swept across seven leagues, four statistics and 308 market-lines, chosen on
2022-24 and reported on 2024-26:

| Strength | Choosing window | Reporting window |
|---|---|---|
| 0.00 | 4.543% | 4.501% |
| 0.02 | 4.544% | 4.515% |
| 0.05 | 4.544% | 4.522% |
| 0.10 | 4.546% | 4.532% |
| **0.25** | **4.550%** | **4.555%** |

**This is a robustness setting, not an accuracy one.** The spread across the whole
sweep is 0.05 percentage points, which is noise — and it is noise for exactly the
reason the bug was invisible in the first place: one club in one league does not
move a mean over 308 series. Anyone reading this table alone would conclude the
penalty does not matter.

0.25 was best on both windows and leaves the spread of team rates wide — 0.72 to
2.16 on Eredivisie cards against a mean of 1.59 — so informed teams keep their
signal while a club with two matches is no longer priced at a hundredth of the
league average.

## The lesson worth keeping

A structural weakness in a model can be invisible in every aggregate metric and
still break a page. Twice now the symptom has been a constraint violation or a
strange number on a fixture list, not a worse log-loss. Checking one league and
generalising is what produced the wrong answer here, and the league that looked
safe was safe only because its promoted club happened to have no data at all.

## Reproducing

```bash
pytest tests/test_counts.py -k gradient
python scripts/tune_count_shrinkage.py
```
