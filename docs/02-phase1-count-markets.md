# Phase 1 results: the count markets

Corners, cards, fouls and shots, validated walk-forward on all five leagues over
2022/23–2025/26. The full run is kept in
`docs/results/phase1-counts-walkforward.txt`; reproduce any row with
`footy backtest-counts --stat <stat> --competition <code>`.

## What ships

Only markets that beat an adaptive benchmark in **every** league and whose
published percentages are accurate to roughly a bucket-error of 9 points or
better. Everything published is calibrated; the raw model is never shown.

| Market | Gain vs benchmark | Worst bucket error | Decision |
|---|---|---|---|
| **Fouls, match total** | 5.4–6.5% (median 6.0) | 5–10% | **Ship.** Strongest market found. |
| **Corners, home team** | 2.1–6.3% (median 4.0) | 5–9% | **Ship.** |
| **Corners, away team** | 1.9–3.9% (median 3.2) | 5–10% | **Ship.** |
| **Shots, match total** | 0.8–4.5% (median 2.1) | 5–9% | **Ship**, thin edge. |
| Cards, all scopes | 0.3–3.2% | 7–11% | Hold. Real but small; see referees below. |
| Shots, per team | 4.4–7.6% | 7–14% | Hold. Good ranking, percentages not yet publishable. |
| Fouls, per team | −1.2–4.3% | 14–20% | Do not ship. |
| **Corners, match total** | −0.6–1.3% | 9% | **Do not ship.** No signal. |

Gains are the percentage of the benchmark's log-loss removed, median across the
lines of that market, and the range is across the five leagues.

## Four findings that changed the model

### 1. Corner totals are unpredictable; corner counts are not

The most useful negative result here. A corner total sits at roughly the same
number whatever the fixture, because dominance transfers corners from one side to
the other rather than creating them — home and away corners correlate at −0.31.
Predicting *how many corners the match has* is close to hopeless (0% gain, and
negative in three leagues). Predicting *how many the home side wins* works in all
five (median 4.0%).

So the product should offer corners per team and not a corners total, which is
the opposite of how these markets are usually presented.

### 2. The independence assumption was doing real damage

The previous session replaced a total built by convolving two independent
per-team distributions with a model of the total fitted directly, on the grounds
that the sides are not independent. Both were kept in the backtest so the claim
could be checked rather than believed:

| Statistic | Direct model better in | Mean gain difference |
|---|---|---|
| fouls | 19 of 20 league-lines | **+6.65 points** |
| shots | 13 of 15 | **+4.26 points** |
| cards | 14 of 20 | +0.27 points |
| corners | 10 of 25 | +0.00 points |

The fix was worth a great deal for fouls and shots, a little for cards, and
nothing at all for corners — which is consistent, because a model of a quantity
that carries no signal cannot be improved by describing its spread correctly.
Without the direct model, fouls and shots totals would both have been discarded
as unpredictable. They are the two markets that ship on totals.

### 3. A fixed base rate is not an honest benchmark

The first pass showed a 23% gain on Bundesliga foul totals, which would be an
extraordinary edge. It was an artefact. Bundesliga fouls fell from 15.3 per team
in 2014/15 to 10.4 in 2025/26 — a third of the level, gone. The benchmark was
frozen at the training period's frequency, so by the test period it was simply
wrong about the league, and any model that tracked the trend beat it easily
without saying anything useful about an individual match.

Every market is now scored against a rolling frequency over the previous 380
matches, which moves with the league. The Bundesliga fouls gain drops from 23%
to 5.9%, and that 5.9% is real. The Premier League, where fouls are stable,
barely moved (5.5% → 5.4%) — which is the check that the new benchmark is
measuring what it should.

This is worth remembering for every future market: **if a gain looks
extraordinary, suspect the benchmark before believing the model.**

### 4. Counts go stale faster than quality

The time decay was inherited from the goals model, where a match's weight halves
after roughly 400 days. That is right for how good a team is and wrong for how it
plays. Tuned walk-forward, every count wanted to forget faster: corners, cards
and fouls at 0.0040 (half-life ~170 days) and shots at 0.0070 (~100 days). Each
statistic now carries its own rate in `CountSpec`.

## Why everything published is calibrated

The raw models rank fixtures well and state the wrong numbers. Every league
showed the same distortion: matches called 34% came in at 40%, matches called
59% came in at 49%. The ordering was right and the confidence was too high,
which is what fitting team strengths on a few hundred matches does.

A two-parameter correction on the log-odds fixes it —
`calibrated = sigmoid(a + b·logit(raw))` — and it cannot invent signal or
reorder anything, so it is safe to apply everywhere. Across all 218 line-league
combinations it improved log-loss in 202 and reliability in 188.

The parameters are fitted on the model's own past predictions for matches that
have since been played, which is exactly what a live system can do. An earlier
attempt fitted them against a deliberately weakened copy of the model (trained
with 540 fewer days of history) and made things worse, because it learned to
correct an overconfidence the real model does not have. That mistake is worth
recording: **calibrate a model against itself, never against a proxy for it.**
The cost is a warm-up period of 400 predictions before the correction switches
on, which is honest — a new market genuinely cannot be published on day one.

## Engineering

Both fitters now supply analytic gradients instead of letting the optimiser
estimate ~100 partial derivatives by finite differences. **A Premier League
corners backtest went from 11m56s to 17s**, identical to four decimal places.
This is what made a 20-combination sweep, and then a decay-tuning sweep on top
of it, practical at all. The same change is available for the goals model, which
still takes 8.6 minutes for one league.

The gradients are verified against finite differences in `tests/test_counts.py`.
That test matters more than it looks: a wrong analytic gradient does not raise,
it just stops the optimiser somewhere that is not the maximum likelihood, and
every number downstream is quietly wrong.

## Open items for later phases

- **Referees exist only for the Premier League.** football-data.co.uk does not
  publish officials for the other four, so the referee term — worth a 63% swing
  in cards in England — is dead weight elsewhere. This is a concrete argument
  for the API-Football backfill, independent of the player data.
- **Cards are held back**, and the referee gap is the likely reason: the two
  leagues where cards calibrate worst (Bundesliga 11%, Ligue 1 11%) are both
  leagues with no referee data.
- **Per-team shots rank well (4.4–7.6%) but calibrate poorly (up to 14%).** The
  two-parameter correction is not enough; this probably needs the spread modelled
  per fixture rather than one dispersion for the whole league.
- **All four models use only team identity and time.** None of the feature layer
  is in them yet — no rest days, no congestion, no opponent-strength weighting.
  That is Phase 2's blend, and it is where the next real improvement should come
  from.
