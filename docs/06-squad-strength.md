# Squad strength: measured, and it works

Written 2026-08-10. The first thing in this project that has improved a model.
The feature blend (`docs/04`) and per-team home advantage (`docs/05`) were both
built properly, measured properly and rejected. This one replicates on every
held-out season, so it gets shipped rather than filed.

The finding, in one line: **how much of today's eleven is the established eleven
is worth 0.0102 of 1X2 log-loss, which is about a third of the remaining gap to
the bookmaker's closing line.** Nothing else about the team sheet mattered
nearly as much, and nothing at all showed up in over/under.

## What the models could not see

Dixon-Coles gives a club one attack rating and one defence rating estimated over
a decade. It cannot know that seven of tonight's eleven were reserves a month
ago. Chelsea with Palmer and Chelsea without him were the same team to it.

So: 1,900 Premier League match sheets from FBref, 2020-21 to 2024-25, 75,358
appearances, 1,609 players. Validated before being trusted — every one of the
3,800 team-matches reconciles with the official score once own goals are
credited to the opposition, and every match has exactly 22 starters.

## The features, and why continuity won

Five were built (`footy/models/squad.py`): lineup continuity, count of
regulars, goal threat, experience, and absent key players. Point-in-time
correctness is structural rather than filtered — matches are walked in order and
folded into history only after their features are taken, so a feature cannot see
its own match. Two tests assert exactly that.

Continuity is the share of the last ten team matches' minutes that today's
starters account for. One means an unchanged side; zero means eleven players who
have not featured.

The first attempt used all ten features, five for each side, and it failed the
way the blend failed:

| Correction uses | Parameters | Out-of-sample deviance vs plain |
|---|---|---|
| all ten features | 11 | +0.0036 worse |
| absences, both sides | 3 | -0.0010 better |
| continuity, one side | 2 | -0.0030 better |
| **continuity, both sides** | **3** | **-0.0075 better** |
| continuity + absences | 5 | -0.0067 better |

Same lesson a third time: the signal is real but thin, and every extra parameter
spends more of it on noise than it recovers. Ten features fit in sample — the
joint likelihood-ratio test is 37.2 on 10 degrees of freedom, p < 0.001 — and
still lost out of sample. Three parameters won.

## The result

Each season held out, the correction trained only on what came before it. 1X2
log-loss, lower is better:

| Holdout | Matches | Plain | Intercept only | With squad | Gain | O/U gain | Market |
|---|---|---|---|---|---|---|---|
| 2022-23 | 378 | 1.0022 | 1.0024 | 0.9964 | +0.0058 | -0.0009 | 0.9620 |
| 2023-24 | 379 | 0.9247 | 0.9244 | 0.9170 | +0.0078 | +0.0049 | 0.9023 |
| 2024-25 | 379 | 0.9917 | 0.9931 | 0.9745 | +0.0172 | -0.0030 | 0.9684 |
| **Pooled** | **1136** | **0.9728** | **0.9733** | **0.9626** | **+0.0102** | **+0.0003** | **0.9442** |

Better in all three seasons. Reproduce with `footy squad-check`.

The intercept-only column is the control, and it is the reason this is
believable. The correction carries an intercept that absorbs any global bias in
the fitted rates, so a gain from plain recalibration would otherwise look
identical to a gain from squad strength. Recalibration alone accounts for
**-0.0004** — nothing. All of the improvement is the features.

Coefficients are the right shape without being told to be. On standardised
continuity, a side's own is **+0.065** and its opponent's is **-0.046**: a
stronger eleven scores more, and facing a stronger eleven scores less, at
comparable magnitude.

The dose-response is monotonic, which is what a mechanism looks like as opposed
to a fitted coincidence:

| Key regulars missing | Team-matches | Actual / expected goals |
|---|---|---|
| 0 | 1058 | 1.064 |
| 1 | 1152 | 1.059 |
| 2 | 585 | 0.990 |
| 3 or more | 231 | 0.945 |

A full-strength side beats the model's expectation by 6%; one missing three
regulars falls 5% short. A 12% swing the team model had no way to express.

## Why 1X2 and not over/under

Over/under 2.5 gained +0.0003, which is nothing. That is the expected result
rather than a disappointment: continuity moves goals *between* the sides. A
weakened team both scores less and concedes more, which changes who wins while
leaving the total roughly alone. Markets on the balance benefit; markets on the
total do not.

## Scale, and the honest caveats

The gap to the closing line on these matches was 0.9728 - 0.9442 = 0.0286. This
closes 0.0102 of it, roughly 36%. And the comparison is fair in our disfavour:
the closing line is priced after lineups are published, so this is ground gained
on a benchmark that already had the same information.

What this does not yet establish:

- **One league, 1,136 scored matches.** The direction is consistent across three
  seasons but the other four leagues are unscraped, and replication there is the
  next thing that should happen.
- **It uses the eleven that actually started**, known about an hour before
  kickoff. That is genuinely usable — it is when the closing line forms — but it
  is not usable for a prediction published the day before. Predicted lineups are
  a different and weaker feature, and this result is the ceiling for them.
- **2025-26 is missing.** FBref serves the 2026-27 page for the 2025-26 URL, so
  the most recent completed season is unreachable this way.
- **Nothing here is in the serving path yet.** `ml.prediction` is still written
  by the uncorrected model.

## Reproducing

```bash
footy load-lineups --competition ENG-PL --from-year 2020 --to-year 2024
footy squad-check
```
