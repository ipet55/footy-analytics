#!/usr/bin/env python
"""Can the published percentage for each count market be acted on?

Two different questions get confused here, so this reports both.

Ranking is whether the model puts the right fixtures above the others, measured
as the percentage of the rolling benchmark's log-loss it removes. Calibration is
whether the number itself is true — whether the fixtures given 80% happen 80% of
the time — measured as the worst reliability bucket's absolute error. A market
can rank well and still print percentages nobody should act on, which is the
state per-team shots is in.

Shipping requires both, in every league. Roughly 8% worst-bucket error is the
line that held cards back at 9.4%, so it is the standard applied here.
"""

from __future__ import annotations

import sys
from datetime import date

from footy.models import counts_backtest as cbt

LEAGUES = ("ENG-PL", "ESP-LL", "ITA-SA", "GER-BL", "FRA-L1")
CALIBRATION_LIMIT = 8.0

# The line reported per market is the middle one, where the sample is largest
# and the decision is least lopsided.
CASES = [
    ("fouls", "total calibrated", 22.5, "Fouls, match total"),
    ("corners", "home calibrated", 4.5, "Corners, home team"),
    ("corners", "away calibrated", 4.5, "Corners, away team"),
    ("shots", "total calibrated", 23.5, "Shots, match total"),
    ("shots", "home calibrated", 12.5, "Shots, home team"),
    ("cards", "total calibrated", 3.5, "Cards, match total"),
    ("corners", "total calibrated", 10.5, "Corners, match total"),
]


def main() -> int:
    # One backtest per (stat, league); every case for that stat reads from it.
    cache: dict[tuple[str, str], cbt.Backtest] = {}
    for stat in dict.fromkeys(stat for stat, _, _, _ in CASES):
        for league in LEAGUES:
            cache[(stat, league)] = cbt.run(
                stat,
                competition=league,
                test_from=date(2022, 7, 1),
                include_convolution=False,
            )

    header = f"{'market':22} {'line':>5} " + " ".join(f"{c[:6]:>13}" for c in LEAGUES)
    print(f"\nRanking — % of the benchmark's log-loss removed (higher is better)\n")
    print(header)
    for stat, scope, line, label in CASES:
        cells = []
        for league in LEAGUES:
            r = cache[(stat, league)].results.get((scope, line))
            cells.append(f"{r.gain_vs_rolling:>12.2f}%" if r and r.n else f"{'--':>13}")
        print(f"{label:22} {line:>5} " + " ".join(cells))

    print(
        f"\nCalibration — worst reliability bucket, absolute error "
        f"(must be under {CALIBRATION_LIMIT:.0f}%)\n"
    )
    print(header)
    for stat, scope, line, label in CASES:
        cells = []
        for league in LEAGUES:
            r = cache[(stat, league)].results.get((scope, line))
            if not r or not r.n:
                cells.append(f"{'--':>13}")
                continue
            worst = r.worst_bucket * 100
            flag = " " if worst <= CALIBRATION_LIMIT else "!"
            cells.append(f"{worst:>11.1f}%{flag}")
        print(f"{label:22} {line:>5} " + " ".join(cells))
    print("\n! marks a league whose percentages are outside the standard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
