#!/usr/bin/env python
"""How hard should count-model team parameters be shrunk?

Added after concluding they did not need it. That conclusion came from checking
Portugal, where the promoted club had no statistics and so was absent from the fit
entirely; the Eredivisie has a promoted club with two matches of statistics, and it
was fitted to a card rate of 0.009 against a league mean of 1.6 — a probability of
zero, rejected by the database.

Chosen on one window and reported on a later one, as with the goals model. Judged
on the calibrated scopes, which are what gets published, and reported as the mean
gain over the rolling benchmark across leagues and lines.
"""

from __future__ import annotations

import sys
from datetime import date

from footy.models import counts as cm
from footy.models import counts_backtest as cbt

LEAGUES = ("ENG-PL", "ESP-LL", "ITA-SA", "GER-BL", "FRA-L1", "NED-ED", "POR-PL")
STATS = ("corners", "cards", "fouls", "shots")
STRENGTHS = (0.0, 0.02, 0.05, 0.10, 0.25)
SPLIT = date(2024, 7, 1)


def sweep(test_from: date, test_to: date | None) -> dict[float, dict[str, float]]:
    out: dict[float, dict[str, float]] = {}
    for strength in STRENGTHS:
        gains: list[float] = []
        worst: list[float] = []
        for league in LEAGUES:
            for stat in STATS:
                try:
                    bt = cbt.run(
                        stat, competition=league, test_from=test_from, test_to=test_to,
                        include_convolution=False, shrinkage=strength,
                    )
                except Exception:
                    continue
                for (scope, _line), r in bt.results.items():
                    if "calibrated" in scope and r.n:
                        gains.append(r.gain_vs_rolling)
                        worst.append(r.worst_bucket * 100)
        out[strength] = {
            "gain": sum(gains) / len(gains),
            "worst": sum(worst) / len(worst),
            "n": len(gains),
        }
        print(f"  {strength:.2f}  mean gain {out[strength]['gain']:6.3f}%  "
              f"mean worst bucket {out[strength]['worst']:5.2f}%  "
              f"({out[strength]['n']} market-lines)", flush=True)
    return out


def main() -> int:
    print(f"Choosing window: 2022-07-01 to {SPLIT}")
    tune = sweep(date(2022, 7, 1), SPLIT)
    chosen = max(tune, key=lambda s: tune[s]["gain"])
    print(f"\nBest mean gain on the choosing window: {chosen:.2f}")

    print(f"\nReporting window: {SPLIT} onward")
    held = sweep(SPLIT, None)
    best_held = max(held, key=lambda s: held[s]["gain"])
    print(
        f"\nOn the held-out window: none gives {held[0.0]['gain']:.3f}%, "
        f"chosen {chosen:.2f} gives {held[chosen]['gain']:.3f}%, "
        f"best available {held[best_held]['gain']:.3f}% at {best_held:.2f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
