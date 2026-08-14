# How accurate is it, per league and per season

12,168 matches scored walk-forward across the nine leagues that have closing odds.
Every earlier figure pooled four seasons into one number; this breaks it apart,
which turns out to matter.

## Pooled: the model closes 81% of the gap and never beats the book

| League | Matches | Model | Market | Gap closed | Worst bucket |
|---|---|---|---|---|---|
| Portugal | 1,233 | 0.92458 | 0.90085 | 85.8% | 5.6% |
| Italy | 1,520 | 0.98598 | 0.96864 | 85.3% | 2.1% |
| Belgium | 1,250 | 1.00136 | 0.98833 | 84.9% | 5.2% |
| Netherlands | 1,233 | 0.95554 | 0.93356 | 83.9% | 4.7% |
| Spain | 1,520 | 0.97750 | 0.95972 | 82.6% | 8.3% |
| France | 1,298 | 0.99797 | 0.97810 | 78.6% | 1.2% |
| Germany | 1,224 | 0.99253 | 0.96986 | 78.2% | 4.2% |
| England | 1,520 | 0.98581 | 0.96031 | 76.1% | 2.0% |
| Turkey | 1,370 | 0.97958 | 0.94841 | 73.4% | 4.1% |

Mean 81.0%, range 73.4% to 85.8%. The market wins in all nine. The narrowness of
that range across nine independent leagues is the reassuring part: it says the
number describes the model rather than any one competition.

## Per season: the pooled calibration is flattering

The pooled worst-bucket column above is the one to distrust. Errors in opposite
directions cancel when four seasons are averaged, so pooling makes calibration
look better than a reader ever experiences it — nobody bets across four seasons at
once.

| League | Pooled | Worst individual season |
|---|---|---|
| Spain | 8.3% | **12.1%** (2023/24) |
| Turkey | 4.1% | **13.5%** (2022/23) |
| Germany | 4.2% | **10.9%** (2023/24) |
| Belgium | 5.2% | **10.2%** (2025/26) |
| Netherlands | 4.7% | 9.6% (2024/25) |
| England | 2.0% | 7.4% (2022/23) |

Turkey pools to 4.1% and had a season at 13.5%. Spain pools to 8.3% with two
seasons near 12%. Six of the nine leagues have at least one season outside the 8%
standard that markets are held to.

Log-loss moves season to season too, by more than the entire gap to the market.
England ran 0.99942, 0.92632, 0.99215, 1.02536 — a spread of 0.10, where the whole
distance to Pinnacle is 0.026. So a single season tells you very little, and a
single season that looks excellent tells you nothing at all.

## What this means for the shipping standard

Markets are currently cleared on pooled calibration. That is the more optimistic of
the two available measurements, and it is not the one a user lives with. Two
options, neither free:

- Require the standard per season. Stricter, honest, and it would unship several
  markets that currently qualify.
- Keep pooling but publish the per-season spread beside it, so the number is
  qualified rather than quietly optimistic.

This is not resolved. It is recorded here because discovering it after publishing
would be worse.

## Reproducing

```bash
python scripts/accuracy_report.py
```
