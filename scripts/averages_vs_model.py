#!/usr/bin/env python
"""Does a historical average price a fixture as well as the model does?

The proposal this answers: take every past season, average the statistic, and
read the probability off that. It is the obvious approach and it is exactly what
`rolling_ll` in the backtest already measures, so the comparison costs nothing
but has never been written down in one place.

Prints, per market, the average's single probability against the spread of the
model's, the log-loss of each, and a reliability table showing whether the
model's confidence is borne out by what actually happened.
"""

from __future__ import annotations

import sys
from datetime import date

import numpy as np

from footy.models import counts_backtest as cbt

# (stat, scope, line). The calibrated scope is the one that would be published,
# so it is the only fair thing to hold up against the average.
CASES = [
    ("corners", "home calibrated", 3.5),
    ("shots", "total calibrated", 20.5),
    ("fouls", "total calibrated", 22.5),
]
LEAGUES = ("ENG-PL", "ESP-LL", "ITA-SA", "GER-BL", "FRA-L1")


def reliability(predicted: np.ndarray, actual: np.ndarray, edges: list[float]) -> None:
    print(f"    {'model says':>16}  {'matches':>8}  {'actually happened':>18}")
    for lo, hi in zip(edges, edges[1:]):
        mask = (predicted >= lo) & (predicted < hi)
        if mask.sum() < 25:
            continue
        rate = actual[mask].mean()
        print(
            f"    {lo:>6.0%} - {hi:<6.0%}  {int(mask.sum()):>8}  {rate:>17.1%}"
        )


def main() -> int:
    for stat, scope, line in CASES:
        predicted: list[float] = []
        actual: list[int] = []
        model_ll = 0.0
        rolling_ll = 0.0
        n = 0

        for league in LEAGUES:
            bt = cbt.run(
                stat,
                competition=league,
                test_from=date(2022, 7, 1),
                include_convolution=False,
            )
            result = bt.results.get((scope, line))
            if result is None or not result.n:
                continue
            predicted.extend(result.predicted)
            actual.extend(result.actual)
            model_ll += result.model_ll
            rolling_ll += result.rolling_ll
            n += result.n

        p = np.array(predicted)
        a = np.array(actual, dtype=float)
        label = f"{stat} {scope}, over {line}"
        print(f"\n{'=' * 68}\n{label}  —  {n:,} matches, five leagues, 2022/23 onward\n")
        print(f"  What actually happened:        {a.mean():>7.1%} of matches")
        print(f"  The historical average says:   {a.mean():>7.1%} for every fixture")
        print(
            f"  The model says:                {p.min():>7.1%} to {p.max():.1%} "
            f"depending on the fixture"
        )
        print()
        print(f"  Log-loss, historical average:  {rolling_ll / n:>7.4f}")
        print(f"  Log-loss, model:               {model_ll / n:>7.4f}")
        print(f"  Improvement:                   {(rolling_ll - model_ll) / rolling_ll * 100:>7.2f}%")
        print()
        reliability(p, a, [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01])

    return 0


if __name__ == "__main__":
    sys.exit(main())
