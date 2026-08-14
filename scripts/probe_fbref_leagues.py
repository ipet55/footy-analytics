#!/usr/bin/env python
"""What does FBref actually carry for the competitions we do not yet hold?

Two separate questions, and only the first is usually asked. Does FBref list the
competition at all, and does it publish the per-match detail the count models
need — shots, corners, fouls, cards? Plenty of smaller leagues have scores and
nothing else, which supports the goals markets and none of the others.

Writes a custom soccerdata league dict, then reads one recent season's schedule
per competition and reports what came back. Deliberately one season and one
request each: FBref rate-limits hard and this is a probe, not a load.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

CONFIG = Path.home() / "soccerdata" / "config" / "league_dict.json"

# FBref's own competition names. Guesses for the ones we have never touched,
# which is the point of probing rather than assuming.
CANDIDATES = {
    "BUL-First League": {"FBref": "Bulgarian First League", "season_start": "Jul",
                         "season_end": "May"},
    "CZE-First League": {"FBref": "Czech First League", "season_start": "Jul",
                         "season_end": "May"},
    "NOR-Eliteserien": {"FBref": "Eliteserien", "season_start": "Mar",
                        "season_end": "Dec", "season_code": "single-year"},
    "INT-Champions League": {"FBref": "Champions League", "season_start": "Sep",
                             "season_end": "May"},
    "INT-Europa League": {"FBref": "Europa League", "season_start": "Sep",
                          "season_end": "May"},
    "BEL-Pro League": {"FBref": "Belgian Pro League", "season_start": "Jul",
                       "season_end": "May"},
}

DETAIL = ("home_shots", "away_shots", "home_corners", "away_corners")


def main() -> int:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(CONFIG.read_text()) if CONFIG.is_file() else {}
    CONFIG.write_text(json.dumps({**existing, **CANDIDATES}, indent=2))
    print(f"wrote {len(CANDIDATES)} candidate leagues to {CONFIG}\n")

    import soccerdata as sd

    available = set(sd.FBref.available_leagues())
    for name in CANDIDATES:
        print(f"=== {name} ===")
        if name not in available:
            print("  not listed by FBref under this name\n")
            continue
        try:
            fb = sd.FBref(leagues=name, seasons="2024-2025")
            sched = fb.read_schedule().reset_index()
            played = sched["score"].notna().sum() if "score" in sched else 0
            print(f"  schedule: {len(sched)} rows, {played} with a score")
            print(f"  columns: {', '.join(sorted(sched.columns))[:300]}")
        except Exception as exc:
            print(f"  FAILED: {type(exc).__name__}: {str(exc)[:200]}")
            traceback.print_exc(limit=1)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
