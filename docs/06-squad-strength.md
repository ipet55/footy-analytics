# Squad strength: measured, and rejected

Written 2026-08-10 claiming a win, retracted 2026-08-11 when it failed to
replicate on four more leagues.

**The claim was that lineup continuity gains 0.0102 of 1X2 log-loss. It does, in
the Premier League, and in no other league tested.** Across Spain, Italy,
Germany and France — 4,173 matches — the gain is +0.0004, with a 95% interval of
-0.0011 to +0.0018.

The sections below are kept as written, with the retraction in place rather than
edited into them, because how this one fooled us is worth more than the finding
would have been. Read `## The replication` before relying on anything above it.

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

## Can we serve this without a lineup feed? No

The result above uses the eleven that actually started, published about an hour
before kickoff. FBref only has it afterwards. So the question that decides
whether any of this reaches production is whether a *predicted* eleven, built
from data we already hold, recovers the gain.

It does not. **The guessable part of continuity is worth 10% of the total; the
part we cannot guess is worth 82%.**

| Correction uses | 1X2 log-loss | Gain | Share of the actual-XI gain |
|---|---|---|---|
| plain model | 0.9728 | — | — |
| forecast eleven | 0.9718 | +0.0010 | 10% |
| the surprise (actual − forecast) | 0.9644 | +0.0084 | 82% |
| actual eleven | 0.9626 | +0.0102 | 100% |

The forecast is not a strawman. It takes the most-used recent players, drops
anyone sent off last match, and drops anyone who has vanished from the squad for
two matches running — the suspension and injury signals that are knowable in
advance and already sitting in the appearance data. It gets **8.2 of 11 starters
right**, and its continuity correlates 0.70 with the real thing.

That accuracy is exactly why it is worthless. A predicted eleven is by
construction the side that normally plays, so it looks close to full strength
every week: its spread is 64% of the real measure's and centred 0.10 higher. The
model already knows what a team looks like at full strength — that is what its
attack and defence ratings *are*. The only new information in a team sheet is the
departure from it, and the departure is precisely the part that cannot be
predicted from past team sheets.

This is a clean negative result with a clear consequence: **serving this feature
requires a pre-match lineup or injury feed.** Until then the measurement stands
as a measurement, and the ceiling on any lineup feed we might buy is 0.0102 —
0.0092 of it above what we can already manage for free.

## The replication

All five leagues were scraped by 2026-08-11: 8,982 matches, 100% coverage. The
data is sound — across all of it, one match fails to reconcile with the official
score and seven team sheets out of ~18,000 do not have eleven starters. Same
harness, same feature, same held-out seasons:

| League | Matches | Gain | Std err | t | Own coef | Opp coef |
|---|---|---|---|---|---|---|
| ENG-PL | 1,136 | +0.0102 | 0.0026 | 3.90 | +0.0331 | -0.0021 |
| ESP-LL | 1,136 | +0.0006 | 0.0008 | 0.67 | +0.0175 | -0.0049 |
| ITA-SA | 1,135 | +0.0004 | 0.0007 | 0.52 | -0.0007 | -0.0196 |
| GER-BL | 914 | +0.0010 | 0.0028 | 0.34 | +0.0775 | -0.0381 |
| FRA-L1 | 988 | -0.0004 | 0.0011 | -0.35 | +0.0089 | **+0.0273** |
| **Other four** | **4,173** | **+0.0004** | **0.0007** | **0.51** | | |

England differs from the rest by +0.0099, standard error 0.0027. The other four
bound the effect tightly around zero, and the interval excludes anything close to
the English figure.

The coefficients say the same thing less politely. The original write-up argued
they came out "the right shape without being told to be" — own continuity
positive, opponent's negative. Across five leagues that shape does not hold: in
Italy a team's own continuity does nothing, in France the opponent's coefficient
has the *wrong sign*, and Germany fits the largest coefficients of any league
while gaining nothing at all, which is what overfitting looks like on the
smallest sample.

It is not a data problem and not the feature behaving differently. Continuity has
a standard deviation of 0.10 in every league and rotation is comparable, with
68-72% of minutes going to each club's top eleven.

### The mistake, which is the useful part

Three held-out seasons of one league, all positive, with a monotonic
dose-response. That felt conclusive. It was one experiment reported as three.

**Matches within a season are not independent trials.** The correction is fitted
once per season and applied to every match in it, so the 1,136 matches behind
t = 3.90 carry nothing like 1,136 degrees of freedom. Cluster by season, which is
the level the experiment actually varies at, and the same evidence reads:

| League | 2022-23 | 2023-24 | 2024-25 | Mean | t (2 df) | p |
|---|---|---|---|---|---|---|
| ENG-PL | +0.0058 | +0.0078 | +0.0172 | +0.0102 | 2.91 | **0.100** |
| ESP-LL | -0.0010 | -0.0001 | +0.0027 | +0.0006 | 0.49 | 0.672 |
| ITA-SA | +0.0001 | +0.0019 | -0.0009 | +0.0004 | 0.45 | 0.696 |
| GER-BL | -0.0043 | +0.0039 | +0.0034 | +0.0010 | 0.37 | 0.746 |
| FRA-L1 | -0.0025 | -0.0006 | +0.0024 | -0.0002 | -0.15 | 0.892 |

**England was never significant.** p = 0.100 on its own data, at the only
clustering level the design justifies. The per-match standard error made a
p = 0.10 result look like p = 0.0001, and "positive in all three seasons" is
exactly what a p = 0.10 effect looks like three times running.

The same-league seasons compounded it: the same twenty clubs recur and the fitted
ratings carry the same biases year to year, so a correction that exploits those
biases looks good in every season of that league and carries nothing to another.

### Consequences

- **Rejected.** The correction stays out of the serving path. This joins the
  feature blend (`docs/04`) and per-team home advantage (`docs/05`) as measured
  and filed.
- **The lineup feed stays unbought.** The measured 0.0092 above what free data
  can reach applies to one league in five, in a result that was never significant
  on its own terms.
- **The player layer is kept.** 8,982 matches and ~390,000 appearances are
  scraped, validated and cheap to query. The features were the wrong hypothesis;
  the data may still support a better one.
- **The harness earns its keep.** Season-clustered replication across independent
  leagues is now the bar for any future claim here, and it is the cheapest way
  this project has found to avoid being wrong in production.

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
  kickoff. Predicted lineups were then built and measured, and recover only 10%
  of the gain, so this needs a live feed to be served at all. See above.
- **2025-26 is missing.** FBref serves the 2026-27 page for the 2025-26 URL, so
  the most recent completed season is unreachable this way.
- **Nothing here is in the serving path yet.** `ml.prediction` is still written
  by the uncorrected model.

## Reproducing

```bash
footy load-lineups --competition ENG-PL --from-year 2020 --to-year 2024
footy squad-check
```
