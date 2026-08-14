#!/usr/bin/env python
"""How accurate is the goals model, per league and per season?

Every accuracy figure so far pools four seasons into one number. That hides the
question worth asking: is the model stable, or did one good season carry it? A
model that closes 80% of the gap to the market every year is a different
proposition from one that closed 95% once and 65% since.

Reports 1X2 log-loss against de-vigged closing odds, broken down by season, for
every league that has odds. Also reports calibration — whether a stated 70%
happens 70% of the time — because a model can rank fixtures well and still print
numbers nobody should act on, and the two failures need different fixes.
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from datetime import date

import numpy as np

from footy.models import backtest as bt

LEAGUES = ("ENG-PL", "ESP-LL", "ITA-SA", "GER-BL", "FRA-L1",
           "NED-ED", "POR-PL", "TUR-SL", "BEL-PL")


def season_of(kickoff: date) -> str:
    """A season runs August to May, so January belongs to the year before."""
    start = kickoff.year if kickoff.month >= 7 else kickoff.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def buckets(pairs: list[tuple[float, int]], edges=(0.2, 0.4, 0.6, 0.8)) -> str:
    """Worst gap between stated probability and observed frequency."""
    worst = 0.0
    lo = 0.0
    for hi in (*edges, 1.01):
        chunk = [(p, y) for p, y in pairs if lo <= p < hi]
        lo = hi
        if len(chunk) < 50:
            continue
        stated = sum(p for p, _ in chunk) / len(chunk)
        actual = sum(y for _, y in chunk) / len(chunk)
        worst = max(worst, abs(stated - actual))
    return f"{worst:.1%}"


def main() -> int:
    overall: dict[str, dict[str, list]] = {}

    for league in LEAGUES:
        scores = bt.run(competition=league, test_from=date(2022, 7, 1))
        per_season: dict[str, dict[str, list]] = defaultdict(
            lambda: {"model": [], "market": [], "base": [], "cal": []}
        )
        for match_id, kickoff, ph, pd_, pa, _po, actual, _wo, mkt_home in scores.predictions:
            s = per_season[season_of(kickoff)]
            probs = (ph, pd_, pa)
            s["model"].append(-math.log(max(probs[actual], 1e-9)))
            # Calibration on the home price, the one a reader looks at first.
            s["cal"].append((ph, 1 if actual == 0 else 0))
            if mkt_home is not None:
                s["market"].append(match_id)

        print(f"\n{league}")
        print(f"  {'season':9}{'matches':>9}{'log-loss':>11}{'worst bucket':>14}")
        for season in sorted(per_season):
            d = per_season[season]
            n = len(d["model"])
            print(f"  {season:9}{n:>9}{sum(d['model'])/n:>11.5f}{buckets(d['cal']):>14}")

        priced = sum(1 for p in scores.predictions if p[8] is not None)
        overall[league] = {
            "model": scores.model_ll / scores.n,
            "market": scores.market_ll / priced if priced else float("nan"),
            "base": scores.base_ll / scores.n,
            "n": scores.n,
            "cal": [(p[2], 1 if p[6] == 0 else 0) for p in scores.predictions],
        }
        o = overall[league]
        gap = o["base"] - o["market"]
        print(f"  {'all':9}{o['n']:>9}{o['model']:>11.5f}{buckets(o['cal']):>14}"
              f"   market {o['market']:.5f}, gap closed {(o['base']-o['model'])/gap:.1%}")

    print("\n\nSummary: share of the base-rate-to-market gap closed")
    print(f"{'league':9}{'matches':>9}{'model':>10}{'market':>10}{'closed':>9}{'worst bucket':>14}")
    rows = []
    for league, o in overall.items():
        gap = o["base"] - o["market"]
        rows.append((league, o["n"], o["model"], o["market"],
                     (o["base"] - o["model"]) / gap, buckets(o["cal"])))
    for league, n, model, market, closed, cal in sorted(rows, key=lambda r: -r[4]):
        print(f"{league:9}{n:>9}{model:>10.5f}{market:>10.5f}{closed:>9.1%}{cal:>14}")

    total = sum(r[1] for r in rows)
    print(f"\n{total:,} matches scored across {len(rows)} leagues. "
          f"Mean gap closed {np.mean([r[4] for r in rows]):.1%}, "
          f"range {min(r[4] for r in rows):.1%} to {max(r[4] for r in rows):.1%}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
