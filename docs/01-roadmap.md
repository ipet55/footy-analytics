# Roadmap: from here to a full prediction product

Written 2026-08-06, after the Dixon-Coles baseline and during count-model work.
This is the master plan. Each phase ends with something measurable.

## Where the project stands

| Asset | State |
|---|---|
| Schema (`raw`/`core`/`features`/`ml`) | Live in Supabase, identity layer tested |
| Matches | 21,589 — top 5 leagues, 2014/15–2025/26 |
| Team-match stat rows | 129,522 (goals, shots, corners, fouls, cards) |
| Odds rows | 1,376,205 incl. Pinnacle closing for all seasons |
| xG (Understat) | On every match (43,178 stat rows) |
| Ratings | 250,050 Elo periods (ClubElo + own elo_goals/elo_xg) |
| Feature layer | Built, passed 4 independent leakage tests — but measurably adds nothing to any model yet (`docs/04-phase2-feature-blend.md`) |
| Blend harness | Built and tested, off by default; waiting on features worth blending |
| Per-team home advantage | Measured and rejected — the home/away split does not persist season to season (`docs/05-venue-effects.md`) |
| Style of play (PPDA, deep completions) | 100% coverage in `core.match_team_stat`, absent from the feature layer, **never tested** |
| Player layer | All five leagues 2020-21 to 2024-25: 8,982 match sheets at 100% coverage. One match in 8,982 fails to reconcile with the official score |
| Squad strength | **Measured and rejected.** Lineup continuity gains 0.0102 of 1X2 log-loss in ENG-PL and +0.0004 across the other four leagues (4,173 matches). Clustered by season, even England is p = 0.100 — never significant (`docs/06-squad-strength.md`) |
| Serving squad strength | Moot. A predicted eleven from free data recovers 10% of a gain that does not replicate, so no lineup feed is worth buying |
| Dixon-Coles 1X2 | Log-loss 0.98583 vs market 0.96031 — 76% of the base-rate-to-market gap closed |
| Count models (corners/cards/fouls/shots) | Backtested; nine markets shipping, seven held, corners totals rejected |
| Referees | 100% coverage in all five leagues, backfilled from the FBref schedule. Previously England only (`docs/07-referees.md`) |
| Cards | Improved by the referee term where referees actually vary (ESP +0.0077, ITA +0.0118), unchanged elsewhere. **Still held** — Italy alone would qualify, Germany and France do not |
| DB size | 474 MB, on Pro |

## Verdict on the FootyStats API

Skip it. What it sells (over/under %, BTTS %, corners-per-match, form) are
pre-computed aggregates over exactly the raw data we already hold — and our own
aggregates are point-in-time correct, which theirs are not guaranteed to be for
training purposes. Its per-team "710+ data points" are current-snapshot stats:
training on them leaks future information. £29.99/mo buys nothing the pipeline
can't derive, and it does NOT cover the actual gaps (injuries, confirmed
lineups, player minutes, transfers).

The FootyStats H2H page (e.g. Liverpool vs Brentford) stays as the **product
design target** — we rebuild that page from our own database, with our model's
probabilities next to the market's.

Percentages like "over 0.5 home goals: 93%" must come from the model's fitted
distribution, never from raw historical frequency. "Liverpool scored in 93% of
past home games" is a description; a prediction has to adjust for who they are
playing, current squad and form. That is the whole point of the model.

## Data purchases (total: one-off ~$29, then ~$19+25/mo)

1. **API-Football Ultra, one month (~$29)** — backfill lineups, player match
   stats, injuries, and *cup + European fixtures* for all 12 seasons
   (~66k requests, fits in one day's 75k quota). Then drop to Pro ($19/mo)
   for ongoing fixtures/lineups/injuries.
2. **transfermarkt-datasets (free)** — transfers, market values, weekly refresh.
3. **Understat player pages (free)** — per-player xG/xA/minutes per match,
   same source we already use, aligns perfectly with existing IDs.
4. **Supabase Pro ($25/mo)** — required before the player layer lands;
   402 MB already used of the 500 MB free tier.

## Phases

### Phase 1 — the count markets — DONE
Results and reasoning in `docs/02-phase1-count-markets.md`. In short:
- Shipping fouls totals (6.0% gain), corners per team (4.0% home, 3.2% away)
  and shots totals (2.1%), each validated in all five leagues.
- Corners *totals* carry no signal and are not shipped; corners *per team* do.
  Dominance moves corners between sides rather than creating them.
- Cards and per-team shots held back — real ranking, percentages not yet
  accurate enough to publish.
- The direct total model was worth +6.65 log-loss points on fouls and +4.26 on
  shots over the convolution it replaced, and nothing on corners.
- Benchmark changed to a rolling 380-match frequency; the fixed base rate had
  been inflating gains wherever a league drifted (Bundesliga fouls fell a third
  over the period).
- Every published probability is recalibrated on the model's own past
  predictions. Improved log-loss in 202 of 218 cases, reliability in 188.
- Analytic gradients cut a league backtest from 11m56s to 17s.

### Phase 2 — ml schema + prediction pipeline — DONE
Notes in `docs/03-phase2-notes.md`; the blend result in
`docs/04-phase2-feature-blend.md`. The first four bullets shipped. The fifth was
measured over ~80 configurations and **rejected**: the feature layer does not
improve any market, because congestion is measured on league fixtures only and
squad availability is not measured at all. The harness is kept and tested, so
Phase 3/4 features can be evaluated the moment they exist.

- Give Dixon-Coles the same analytic gradient treatment as the count models;
  one league currently takes 8.6 minutes, which makes tuning it impractical.
- `ml.model` (registry, params, training window), `ml.prediction`
  (match, market, line, probability, model version, predicted_at),
  `ml.outcome` for realised results.
- Store the recalibration parameters per market alongside the model version.
  A prediction is not reproducible without them.
- A `footy predict` command that writes the full probability table per fixture:
  1X2, O/U 0.5–5.5 goals (match and per-team), BTTS, corners lines, cards lines.
- ~~Blend: Dixon-Coles / count models + gradient boosting over the feature
  layer~~ — built and rejected on the evidence; see above.

### Phase 6/7 (partly done, out of order) — public views + the web app
Built early, ahead of the player layer, because nine validated markets were
sitting in a database with no way to look at them, and squeezing another point
of log-loss is worth less than being able to see what already works.
- `public` views are live: fixtures, markets, predictions with settled results,
  de-vigged market prices, form, head to head, track record. They are the access
  control — `anon` can read those nine views and nothing else, asserted in
  `tests/test_public_surface.py`.
- Next.js app in `web/`: fixture list, match page with the model against the
  closing price, and a calibration page.
- Still to do here: the GitHub Actions cron that keeps fixtures and predictions
  fresh, and the generated per-fixture summary.

### Phase 3 — player layer (scraped for all five leagues; hypothesis rejected)
The plan was to run the free upper-bound test before paying, so the size of the
prize would be known before spending anything. Doing that saved the money.

The test came back positive on England — knowing the true eleven appeared to be
worth 0.0102 of 1X2 log-loss — and flat on all four other leagues, at +0.0004
over 4,173 matches. Clustered by season, England itself is p = 0.100
(`docs/06-squad-strength.md`). A predicted eleven, which is what a free pipeline
could actually serve, recovers 10% of even that.

So the API-Football month stays unbought, and the roadmap's own rule — replicate
before spending — is what caught it. The scraped data stays: 8,982 validated
match sheets are a fixed cost already paid, and a better hypothesis may yet use
them.

- New tables: `core.player` (+ `player_alias`), `core.appearance`
  (match, player, minutes, position, goals, assists, cards),
  `core.injury`, `core.transfer`, `core.manager` + spells.
- Backfill 12 seasons; extend `core.match` natural key for cup/two-legged ties
  (already flagged in the index comment).
- European + domestic cup fixtures loaded for the same clubs — required for
  congestion features even if we never predict those matches.

### Phase 4 — squad-strength and congestion features (user's points 1 & 2)
These are now the *specific* features the blend was missing, which is the whole
case for Phase 3 preceding them: `rest_days` currently ignores midweek European
trips, and nothing anywhere records who is fit to play.

- Lineup strength: share of season xG+xA contribution missing from today's
  lineup (sold / injured / rested), share of usual starting XI minutes present.
- Congestion: days since last match, matches in last 7/14 days,
  European fixture within ±4 days, travel (home leg vs away leg).
- Retrain Phase-2 models with these features; keep them only if the
  walk-forward numbers improve.

### Phase 5 — style and matchup features (user's point 3)
- Style vectors per team from what we already store: PPDA (pressing),
  deep completions, directness (xG per shot), shot volume vs conversion,
  possession once FBref/API-Football fills it.
- Interaction features (e.g. high-press vs build-up teams) in the GBM;
  Dixon-Coles attack×defence already covers strength asymmetry —
  this is specifically about *how*, not *how good*.
- Note: opponent-adjusted averages (user's point 4) are already solved by
  Elo differentials + Dixon-Coles parameters; add opponent-strength-weighted
  rolling windows to the feature layer as a cheap extra.

### Phase 6 — live path + prediction summaries
- GitHub Actions cron: fetch upcoming fixtures, lineups when announced,
  injuries; recompute features; write predictions to `ml.prediction`.
- Public views in `public` schema for the app to read (never `core` directly).
- Generated match summary per fixture: template/LLM over the feature diffs
  ("top scorer X sold in January — home goals estimate reduced", etc.).

### Phase 7 — the web app
- Next.js on Vercel, reading the public views.
- Match page = the FootyStats H2H layout: form, H2H, our probability table
  per market with the model % next to de-vigged market %, highlighting
  where they disagree most (that disagreement IS the product).

### Phase 8 — monitoring and honesty
- Calibration dashboard per market per season.
- Closing-line-value tracking: did our pre-match probabilities beat the
  closing price movement? This is the only metric that predicts long-term edge.
- Model registry keeps every version's numbers; no silent retraining.

## Expectations, stated plainly

- Beating Pinnacle's closing line on 1X2 consistently is unlikely; the
  realistic edges are corners/cards/fouls markets, which books price lazily,
  and earlier (opening) prices.
- Player data will improve goals markets by low single digits of log-loss;
  its bigger value is the *explanatory* layer (summaries users trust).
- Everything is measured walk-forward against closing odds. Any feature or
  data source that doesn't move that number gets dropped, whatever it cost.
