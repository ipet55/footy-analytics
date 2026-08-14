#!/usr/bin/env python
"""How much history does API-Football actually have for the leagues we want?

"1,226 leagues covered" is a count of competitions, not a promise of twelve
seasons of corner counts for each. Every season of every league carries its own
`coverage` flags, and `statistics_fixtures` is the one that decides whether a
league can support the count markets or only the goals ones.

Reads the leagues endpoint, which costs one request per country, and prints the
seasons available per competition together with what each season carries. Then
pulls the statistics for a single finished fixture to confirm corners are really
there rather than merely flagged.

Free tier is 100 requests a day, and this uses well under ten.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

BASE = "https://v3.football.api-sports.io"
WANTED = {
    "Bulgaria": ("First League",),
    "Czech-Republic": ("Czech Liga",),
    "Norway": ("Eliteserien",),
    "Portugal": ("Primeira Liga", "Liga Portugal 2", "Taça de Portugal"),
    "World": ("UEFA Champions League", "UEFA Europa League"),
}


def load_key() -> str:
    for line in Path(".env").read_text().splitlines():
        if line.startswith("API_FOOTBALL_KEY="):
            return line.split("=", 1)[1].strip()
    return os.environ.get("API_FOOTBALL_KEY", "")


def get(session: requests.Session, path: str, **params):
    r = session.get(f"{BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        print(f"  API errors: {body['errors']}")
    return body


def main() -> int:
    key = load_key()
    if not key:
        print("No API_FOOTBALL_KEY in .env")
        return 1
    session = requests.Session()
    session.headers.update({"x-apisports-key": key})

    status = get(session, "/status").get("response", {})
    sub = status.get("subscription", {})
    req = status.get("requests", {})
    print(f"plan: {sub.get('plan')}  active until {sub.get('end')}")
    print(f"requests today: {req.get('current')} of {req.get('limit_day')}\n")

    sample_fixture = None
    for country, names in WANTED.items():
        body = get(session, "/leagues", country=country)
        for entry in body.get("response", []):
            league = entry["league"]
            if league["name"] not in names:
                continue
            seasons = entry.get("seasons", [])
            with_stats = [
                s["year"] for s in seasons
                if s.get("coverage", {}).get("fixtures", {}).get("statistics_fixtures")
            ]
            with_lineups = [
                s["year"] for s in seasons
                if s.get("coverage", {}).get("fixtures", {}).get("lineups")
            ]
            odds = [s["year"] for s in seasons if s.get("coverage", {}).get("odds")]
            years = [s["year"] for s in seasons]
            print(f"{country} / {league['name']}  (id {league['id']})")
            print(f"  seasons:            {min(years)}-{max(years)} ({len(years)})")
            print(f"  fixture statistics: {len(with_stats)} seasons"
                  + (f", {min(with_stats)}-{max(with_stats)}" if with_stats else ""))
            print(f"  lineups:            {len(with_lineups)} seasons"
                  + (f", {min(with_lineups)}-{max(with_lineups)}" if with_lineups else ""))
            print(f"  odds flagged:       {len(odds)} seasons")
            if with_stats and sample_fixture is None:
                sample_fixture = (league["id"], max(with_stats), league["name"])
            print()

    if sample_fixture:
        league_id, season, name = sample_fixture
        print(f"=== Are corners really present? {name} {season} ===")
        fx = get(session, "/fixtures", league=league_id, season=season, status="FT")
        games = fx.get("response", [])
        print(f"  finished fixtures returned: {len(games)}")
        if games:
            fid = games[0]["fixture"]["id"]
            st = get(session, "/fixtures/statistics", fixture=fid).get("response", [])
            if st:
                types = [s["type"] for s in st[0].get("statistics", [])]
                print(f"  statistic types on one fixture ({len(types)}):")
                print("   ", ", ".join(types))
            else:
                print("  no statistics returned for that fixture")
    return 0


if __name__ == "__main__":
    sys.exit(main())
