# The feature blend: measured, and rejected

Written 2026-08-06. This closes the last open bullet of Phase 2 — "blend:
Dixon-Coles / count models + gradient boosting over the feature layer" — with a
negative result. The feature layer does not improve any market, and the blend is
not shipped. The code stays in the tree (`src/footy/models/blend.py`, reachable
via `counts_backtest.run(blend=True)`, off by default) so the finding can be
re-run rather than re-argued.

This mattered enough to test properly because the feature layer was built,
leakage-tested against four independent checks, and then used by nothing. Before
this, every model saw only who was playing, when, and the statistic it predicts.

## How the blend was built

As a correction to the fitted rate rather than a replacement for it:

    log(rate) = log(rate from the fitted model) + f(features)

Three reasons for that shape. The fitted models are good at pooling a decade of
matches into per-team strength, and a tree asked to rediscover that from
features would approximate it in step functions and lose for reasons having
nothing to do with the features. The current behaviour is exactly `f = 0`, so
the blend is a strict generalisation and the comparison is honest by
construction. And if the features carry nothing, the correction can collapse
toward zero on its own.

scikit-learn's boosting has no offset parameter, and it does not need one. For a
Poisson likelihood with offset `t`, writing `w = exp(t)` and `z = y / exp(t)`:

    exp(t + f) - y(t + f)  =  w * (exp(f) - z * f)  + terms free of f

so fitting `z` with weights `w` is the same optimisation. The dispersion is
refitted on the blended rates, because a correction that explains variance the
base model was absorbing as overdispersion would otherwise leave every
probability pulled toward the middle.

The market probabilities in `features.match` were excluded throughout. A model
meant to disagree with the market usefully cannot be trained on the market's
own answer.

## What was tried, in order

Each row is a different hypothesis about why the previous row failed. Evaluation
is a two-season holdout (2020-07 to 2022-07) unless stated, scored by
out-of-sample log-likelihood of the actual counts against the same base model.

| # | Setup | Result |
|---|---|---|
| 1 | GBM, all 86 features, 4 stats x 3 scopes, ENG-PL | worse in **12 of 12** |
| 2 | Regularisation sweep, 10 to 200 trees, 2 leaf sizes | damage rises monotonically with how hard the correction pushes |
| 3 | Only the 10 features the base models structurally cannot express (rest days, h2h, ClubElo, season position) | worse in **14 of 15** |
| 4 | Dixon-Coles goals + xG features, which it genuinely lacks | worse in **12 of 12** |
| 5 | Out-of-fold offsets, 8 time blocks — proper stacking | better in **5 of 20**; mean gain +0.0026 against mean loss -0.0234 |
| 6 | Small linear correction, 1-3 features picked on train residuals | better in **9 of 20** — a coin flip |

Roughly eighty configurations. Nothing improved consistently.

Step 5 is the committed harness and is reproducible in one command:

```bash
footy blend-check          # ~90s, prints the table and the verdict
```

Its summary line is the cleanest statement of the result: when the blend wins it
wins by an average of 0.0026, and when it loses it loses by 0.0234. Even if the
wins were real rather than noise, a nine-to-one ratio against would make the
trade a bad one.

### Step 2 is the one that settles it

The loss grows monotonically with the size of the adjustment, and the best
setting in every case is the one that adjusts least. Real signal produces an
interior optimum — some amount of correction that beats both none and too much.
A monotone slope toward zero says there is nothing to trade off against
variance.

```
corners total, ENG-PL     fouls total, ENG-PL
push_sd  delta            push_sd  delta
0.020   -0.00322          0.013   +0.00210
0.035   -0.00832          0.023   +0.00324
0.051   -0.01574          0.033   +0.00236
0.071   -0.02945          0.043   -0.01100
0.096   -0.05186          0.060   -0.03209
```

### Step 6 across all five leagues, out-of-fold and honestly selected

This variant replaced the booster with a one-to-three-feature Poisson term, on
the theory that an effect this small needs a low-variance estimator. It was an
exploration and is not in the harness; what carried over into `blend-check` is
its diagnostic, the identity of the feature chosen on training residuals.

| stat | ENG-PL | ESP-LL | GER-BL | ITA-SA | FRA-L1 | feature chosen on train |
|---|---|---|---|---|---|---|
| shots | -0.04696 | -0.03009 | +0.00825 | +0.01210 | +0.00590 | differs every league |
| fouls | -0.01401 | -0.02144 | -0.02453 | -0.02315 | -0.00410 | differs every league |
| corners | +0.00340 | +0.00950 | -0.01270 | +0.00906 | +0.00109 | differs every league |
| cards | +0.00593 | -0.00501 | -0.03636 | -0.03775 | +0.00004 | differs every league |

The last column is the real finding. The selected feature is different in every
league, and often mechanically implausible — `rating_diff` as the top predictor
of shots residuals in England, `home_shots_a_10` for fouls, `home_season_matches`
for cards. Unstable selection with inconsistent signs is what mining noise looks
like. A genuine effect would pick the same feature in most leagues and gain in
the same direction.

`blend-check` now measures this instead of leaving it to the reader: it reports
14 distinct features selected across 20 fits, and says so in the verdict.

### A mistake worth recording

Partway through, residual correlations were computed on the holdout and read as
evidence of remaining signal — `away_shots_a_5` at |r| = 0.163 against a noise
floor of 0.035 looked like four times noise and prompted step 6. It was an
artefact of measuring correlation on the evaluation set. When selection is done
honestly on training data, those features do not transfer, which is exactly what
the step-6 table shows. The lesson generalises: a diagnostic computed on the test
window is a form of selection on the test window.

## Why it fails

Not because the features duplicate the models. That was the first hypothesis and
it is wrong — the rolling averages correlate with the fitted rate at only
r = 0.06 to 0.08, so they carry largely different information. They just do not
carry *predictive* information.

The real reason is visible in the spread. For ENG-PL fouls the fitted rate
varies by 14% of its mean across fixtures, while the residual standard deviation
is 5.13 fouls per match; for shots, 8% against 5.71 shots. Match-to-match
variation in these counts is overwhelmingly irreducible. The models already
capture the part that is a property of the teams, and what is left is close to
noise. There is very little room for a covariate to work in, and a flexible
learner given 86 candidates will spend that room on variance.

The features that could plausibly have mattered are the ones that are currently
weakest:

- **Congestion is barely measured.** `rest_days` counts league rest only, as the
  schema's own comment warns. A side returning from a Tuesday away leg in Europe
  looks identically rested to one that had the week off. The feature that should
  carry congestion cannot see the fixtures that cause it.
- **Squad availability is not measured at all.** No injuries, no lineups, no
  minutes. Who is actually on the pitch is absent from every model.
- **Head to head is thin.** A handful of prior meetings, and the teams have
  changed.

## What this means for the roadmap

It is evidence *for* Phase 3, and for a sharper reason than optimism. The blend
failing does not show that features cannot help; it shows that *these* features
cannot. The two mechanisms with a real prior — congestion and squad strength —
are respectively crippled and absent, and both are exactly what the
API-Football month and the cup/European fixture backfill would supply.

It also inverts the order of the argument for spending the money. The earlier
concern was that buying player data before having a model that consumes features
would make the purchase unmeasurable. That concern is now resolved from the
other side: the harness exists, it is tested, and it is measurably neutral on
present data. When lineup and congestion features land they can be dropped
straight into `blend.py` and the same holdout will say whether they earned their
cost.

Concretely:

- Do not tune this further. Two of six steps were attempts to rescue it by
  regularisation, and both failed in the direction that says stop.
- Do not ship it. Nothing in `ml.market` changes; `footy predict` is untouched.
- Revisit after cup and European fixtures are loaded, so `rest_days` means what
  it claims, and after appearances and injuries exist.

## A note on rigour

Rejection was decided on a two-season holdout across five leagues rather than
the full walk-forward. That is deliberate: a walk-forward is what you need to
*ship* something, since it establishes the number you will publish. To reject,
a holdout that the candidate loses on in most cells is sufficient, and the full
walk-forward would have cost hours of compute to confirm a result that never
came close. If a future feature set shows promise on this holdout, it earns the
walk-forward before anything is published.
