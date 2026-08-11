# Referees: the missing driver of cards, found for free

Written 2026-08-11. The cards markets were held because their percentages were
not accurate enough to publish. Part of the reason turned out to be a data gap
rather than a modelling one: **the single biggest driver of a booking was missing
in four leagues out of five.**

## The gap

`core.match.referee_id` was 100% populated for England and 0% for Spain, Italy,
Germany and France. Not a parsing bug — football-data.co.uk publishes the
`Referee` column only in `E0`, verified against the raw 2024-25 files for all
five leagues.

The cards model has supported a per-referee term with L2 shrinkage since Phase 1
(`counts.SPECS["cards"].use_referee`). It had simply never had anything to fit
outside England.

FBref names the referee on its **schedule** page, at 100% coverage for every
season from 2014-15 to 2025-26. That is one request per league-season rather than
per match, so the entire backfill is minutes rather than hours, and we were
already scraping those pages.

13,145 matches and 201 new officials later, coverage is 100% in all five leagues.
England was deliberately left alone: its referees are stored under
football-data's initial-and-surname convention ("A Taylor") where FBref writes
full names ("Anthony Taylor"), so loading both would have created a duplicate for
every official rather than matching them.

Ten seasons initially failed on missing team aliases from the pre-2020 era, which
is the same class of problem `footy check-lineup-names` was built for. Four were
genuine clubs (`Dep. La Coruña`, `Paderborn 07`, `Evian`, `Gazélec Ajaccio`) and
two were relegation play-off opponents from the division below
(`Karlsruher`, `BTSV`), now declared in `FBREF_NOT_IN_LEAGUE` alongside
Elversberg.

## Referees really do differ

Cards per match, among officials with 100+ matches:

| League | Referees | Range | Spread |
|---|---|---|---|
| ESP-LL | 19 | 3.75 - 5.94 | **2.19** |
| ITA-SA | 17 | 3.91 - 5.62 | **1.71** |
| GER-BL | 16 | 2.97 - 4.34 | 1.37 |
| ENG-PL | 18 | 2.85 - 4.06 | 1.21 |
| FRA-L1 | 19 | 3.27 - 4.44 | 1.17 |

Some of that spread is era rather than person — Manuel Gräfe's 2.97 is partly the
Bundesliga of the 2010s — but the ordering is what matters below.

One cosmetic oddity: La Liga has an official FBref renders as "Hsu Jason". He
officiated about 20 matches a season for six consecutive seasons, which is one
referee's normal workload, so it is a mangled label rather than two people merged
into one. Harmless for a categorical term.

## Does it improve cards? Partly, and honestly

A controlled A/B — same data, same harness, referee term on and off — on the four
recalibrated total lines, clustered by season:

| League | 2023-24 | 2024-25 | 2025-26 | Mean | t (2 df) | p |
|---|---|---|---|---|---|---|
| ESP-LL | +0.0067 | +0.0125 | +0.0040 | **+0.0077** | 3.08 | 0.091 |
| ITA-SA | +0.0036 | +0.0128 | +0.0187 | **+0.0118** | 2.68 | 0.116 |
| GER-BL | +0.0013 | -0.0002 | +0.0049 | +0.0021 | 1.32 | 0.318 |
| ENG-PL | -0.0025 | -0.0008 | +0.0008 | -0.0008 | -0.85 | 0.486 |
| FRA-L1 | -0.0045 | -0.0027 | +0.0028 | -0.0014 | -0.67 | 0.570 |

Pooled over 15 league-seasons: **+0.0038, t = 2.28, p = 0.039**, improved in 10
of 15. Clustered by *league* instead — five observations, the most conservative
reading and arguably the right one since referees recur within a league across
seasons — it is **p ≈ 0.20**.

So: suggestive, not established. Stated plainly because the squad-strength
retraction (`docs/06`) came from exactly this kind of number being oversold.

What raises confidence above the p-value alone is that **the gain tracks the
spread in referee strictness, across independent leagues**:

| League | Referee spread | Gain |
|---|---|---|
| ESP-LL | 2.19 | +0.0077 |
| ITA-SA | 1.71 | +0.0118 |
| GER-BL | 1.37 | +0.0021 |
| ENG-PL | 1.21 | -0.0008 |
| FRA-L1 | 1.17 | -0.0014 |

Both leagues where referees vary by more than 1.5 cards a match gain clearly;
all three where they vary by less than 1.4 gain nothing. That correlation is
r = 0.79, itself only p ≈ 0.11 on five points — but a dose-response across
*independent leagues* is much better evidence than the same pattern within one
league, which is precisely the trap `docs/06` fell into.

## Cards still do not ship

Recalibrated match totals, referee term on:

| League | Mean gain vs rolling | Worst reliability bucket | Bias range |
|---|---|---|---|
| ITA-SA | **4.96%** | 6.3% | +0.006 to +0.025 |
| ESP-LL | 2.16% | 7.3% | +0.007 to +0.032 |
| FRA-L1 | 1.12% | 11.5% | -0.055 to +0.001 |
| ENG-PL | 0.94% | 8.5% | -0.002 to +0.020 |
| GER-BL | 0.57% | 9.4% | +0.030 to +0.066 |

For scale, fouls totals ship on 5.4-6.5% gains. Italy now sits just under that
and would qualify on its own; Germany and France do not come close, with
reliability-bucket errors of 9.4% and 11.5% and biases up to 0.066.

The project's rule is that a market ships only when it is validated in all five
leagues, and `ml.market.status` is per market rather than per league, so there is
no honest way to ship Italy alone today. **Cards stay held.** The gap narrowed;
it did not close.

## Reproducing

```bash
footy load-referees                      # four leagues, twelve seasons
footy backtest-counts --stat cards --competition ITA-SA
```
