#!/usr/bin/env python
"""Assess every count market in the leagues added recently, and print verdicts.

The four leagues cleared for publication ship goals and fouls totals, and show
six to eight markets against England's eleven. That is not because the rest were
rejected: only four count markets per league were ever measured, so corners away,
shots and per-team fouls are absent rather than judged. This runs the same
walk-forward the original five were held to, on every scope and line.

The standard is the one already applied: a market ships in a competition when it
beats the rolling benchmark at every line and its worst reliability bucket stays
inside 8% at every line. Both conditions, every line — a market is published whole
or not at all, because status has no line dimension.
"""

from __future__ import annotations

import sys
from datetime import date

from footy.models import counts as cm
from footy.models import counts_backtest as cbt

LEAGUES = ("NED-ED", "POR-PL", "TUR-SL", "BEL-PL")
STATS = ("corners", "shots", "fouls", "cards")
SCOPES = (("total calibrated", "total"), ("home calibrated", "home"),
          ("away calibrated", "away"))
CALIBRATION_LIMIT = 8.0


def main() -> int:
    verdicts: list[tuple[str, str, str, str, str]] = []

    for league in LEAGUES:
        for stat in STATS:
            try:
                bt = cbt.run(stat, competition=league, test_from=date(2022, 7, 1),
                             include_convolution=False)
            except Exception as exc:
                print(f"{league} {stat}: failed — {str(exc)[:90]}")
                continue

            for scope, suffix in SCOPES:
                rows = [r for (s, _), r in bt.results.items() if s == scope and r.n]
                if not rows:
                    verdicts.append((league, f"{stat}_{suffix}", "-", "-", "no data"))
                    continue
                gains = [r.gain_vs_rolling for r in rows]
                buckets = [r.worst_bucket * 100 for r in rows]
                ships = min(gains) > 0 and max(buckets) <= CALIBRATION_LIMIT
                reason = (
                    "shipping" if ships
                    else "negative at a line" if min(gains) <= 0
                    else f"calibration {max(buckets):.1f}%"
                )
                verdicts.append((
                    league, f"{stat}_{suffix}",
                    f"{min(gains):.1f} to {max(gains):.1f}%",
                    f"{max(buckets):.1f}%",
                    reason,
                ))
            print(f"  {league} {stat} done", flush=True)

    print(f"\n{'league':8}{'market':16}{'gain range':>18}{'worst bucket':>14}  verdict")
    for league, market, gain, bucket, reason in verdicts:
        mark = "SHIP" if reason == "shipping" else "hold"
        print(f"{league:8}{market:16}{gain:>18}{bucket:>14}  {mark}  {reason}")

    print("\nSQL for the ones that qualify:")
    shipping = [(lg, mk) for lg, mk, _, _, r in verdicts if r == "shipping"]
    if not shipping:
        print("  none")
    for lg, mk in shipping:
        print(f"  ('{mk}', '{lg}'),")
    return 0


if __name__ == "__main__":
    sys.exit(main())
