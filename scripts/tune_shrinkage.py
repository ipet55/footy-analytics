#!/usr/bin/env python
"""How hard should attack and defence be pulled toward the league average?

The problem it fixes is real and visible: a promoted club with one played match
gets a stronger attack than Benfica, because time decay gives that match a weight
of 1.0 against 0.0004 for one from 2014, and nothing pulls it back.

The problem it could cause is that shrinking every team hurts the leagues where
there is plenty of data and the ratings are earned. Which of the two dominates is
not a matter of judgement, so this measures it: the same walk-forward the shipping
decisions use, at several strengths, across all nine leagues with odds.

Reported against the market rather than the base rate. A change that improves
log-loss but widens the gap to the closing line has not helped.
"""

from __future__ import annotations

import sys
from datetime import date

from footy.models import backtest as bt

LEAGUES = ("ENG-PL", "ESP-LL", "ITA-SA", "GER-BL", "FRA-L1",
           "NED-ED", "POR-PL", "TUR-SL", "BEL-PL")
# Extended past the first run's best, which sat at the edge of the range. A
# maximum on the boundary is a sign the range was too narrow, not an optimum.
STRENGTHS = (0.0, 0.02, 0.05, 0.10, 0.20, 0.40)

# Chosen on the first two seasons, reported on the last two. Picking a setting on
# the same matches it is then judged on gives a number that cannot be trusted,
# however careful the walk-forward itself is: the choice has seen the answer.
SPLIT = date(2024, 7, 1)


def sweep(test_from: date, test_to: date | None) -> dict[str, dict[float, float]]:
    out: dict[str, dict[float, float]] = {}
    for league in LEAGUES:
        out[league] = {}
        for strength in STRENGTHS:
            scores = bt.run(
                competition=league,
                test_from=test_from,
                test_to=test_to,
                shrinkage=strength,
            )
            out[league][strength] = scores.model_ll / scores.n
    return out


def report(title: str, table: dict[str, dict[float, float]]) -> None:
    print(f"\n{title}")
    print(f"{'league':8}" + "".join(f"{s:>9.2f}" for s in STRENGTHS) + "     best")
    for league in LEAGUES:
        row = table[league]
        best = min(row, key=row.get)
        print(
            f"{league:8}" + "".join(f"{row[s]:>9.5f}" for s in STRENGTHS)
            + f"{best:>9.2f}"
        )
    print(f"{'mean':8}", end="")
    means = {s: sum(table[lg][s] for lg in LEAGUES) / len(LEAGUES) for s in STRENGTHS}
    print("".join(f"{means[s]:>9.5f}" for s in STRENGTHS)
          + f"{min(means, key=means.get):>9.2f}")


def main() -> int:
    tune = sweep(date(2022, 7, 1), SPLIT)
    report(f"Choosing window: 2022-07-01 to {SPLIT}", tune)

    means = {s: sum(tune[lg][s] for lg in LEAGUES) / len(LEAGUES) for s in STRENGTHS}
    chosen = min(means, key=means.get)
    print(f"\nChosen on the first window: {chosen:.2f}")

    held = sweep(SPLIT, None)
    report(f"Reporting window: {SPLIT} onward (not used for the choice)", held)

    held_means = {
        s: sum(held[lg][s] for lg in LEAGUES) / len(LEAGUES) for s in STRENGTHS
    }
    print(
        f"\nOn the held-out window: no shrinkage {held_means[0.0]:.5f}, "
        f"chosen {chosen:.2f} gives {held_means[chosen]:.5f}, "
        f"best available {min(held_means.values()):.5f} "
        f"at {min(held_means, key=held_means.get):.2f}"
    )
    better = sum(1 for lg in LEAGUES if held[lg][chosen] < held[lg][0.0])
    print(f"Leagues improved by the chosen setting: {better} of {len(LEAGUES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
