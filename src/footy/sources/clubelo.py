"""ClubElo: free Elo ratings for European clubs, full history.

Fetched over plain HTTP rather than through soccerdata, whose TLS client times
out against this host. The API is a CSV endpoint per club returning that club's
entire rating history as validity ranges.

Elo is a compact summary of team strength that already accounts for opponent
quality, which makes it a strong single feature and a natural basis for the
match-difficulty rating.
"""

from __future__ import annotations

import csv
import io
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime

import requests

SOURCE_CODE = "clubelo"
BASE_URL = "http://api.clubelo.com"
USER_AGENT = "footy-analytics/0.1 (research)"

# ClubElo country codes for the five leagues we cover.
COUNTRIES = {"ENG": "England", "ESP": "Spain", "ITA": "Italy", "GER": "Germany", "FRA": "France"}


@dataclass(frozen=True)
class Rating:
    club: str
    country: str
    level: int | None
    rating: float
    valid_from: date
    valid_to: date
    rank: int | None


def _parse_rows(body: str) -> list[Rating]:
    out: list[Rating] = []
    for row in csv.DictReader(io.StringIO(body)):
        try:
            valid_from = datetime.strptime(row["From"], "%Y-%m-%d").date()
            valid_to = datetime.strptime(row["To"], "%Y-%m-%d").date()
            rating = float(row["Elo"])
        except (KeyError, ValueError):
            continue
        rank = row.get("Rank")
        level = row.get("Level")
        out.append(
            Rating(
                club=row["Club"].strip(),
                country=row.get("Country", "").strip(),
                level=int(level) if level and level.isdigit() else None,
                rating=rating,
                valid_from=valid_from,
                valid_to=valid_to,
                rank=int(rank) if rank and rank.isdigit() else None,
            )
        )
    return out


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _get(url: str, session: requests.Session, timeout: int, attempts: int = 4) -> str:
    """GET with backoff. The host sheds load with 502s and timeouts when pushed."""
    delay = 5.0
    last: Exception | None = None
    for _ in range(attempts):
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last = exc
            time.sleep(delay)
            delay *= 2
    raise ConnectionError(f"{url} failed after {attempts} attempts") from last


def clubs_on(day: date, session: requests.Session | None = None) -> list[Rating]:
    """Every club ClubElo tracks on a given date. Used to discover club names."""
    s = session or _session()
    return _parse_rows(_get(f"{BASE_URL}/{day.isoformat()}", s, timeout=90))


# ClubElo's URL name is the display name with spaces removed, but a few clubs are
# published under a different name entirely.
URL_NAME_OVERRIDES: dict[str, str] = {}


def url_names(club: str) -> list[str]:
    """Candidate URL spellings, best first.

    The API answers an unknown club with HTTP 200 and a header-only body rather
    than a 404, so a wrong spelling looks like a club with no history. That makes
    trying the alternatives worthwhile.
    """
    if override := URL_NAME_OVERRIDES.get(club):
        return [override]
    compact = club.replace(" ", "")
    return [compact] if compact == club else [compact, club.replace(" ", "_")]


def team_history(club: str, session: requests.Session | None = None) -> list[Rating]:
    """One club's full rating history."""
    s = session or _session()
    for name in url_names(club):
        rows = _parse_rows(_get(f"{BASE_URL}/{name}", s, timeout=120, attempts=2))
        if rows:
            return rows
    return []


def team_histories(
    clubs: list[str], workers: int = 6, since: date | None = None, attempts: int = 3
) -> dict[str, list[Rating]]:
    """Fetch several clubs concurrently. The API is slow, so serial fetching of
    167 clubs would take the best part of an hour.

    It also times out under load, so failures are retried with progressively
    lower concurrency rather than being reported as clubs without any history.
    """
    session = _session()

    def one(club: str) -> tuple[str, list[Rating]]:
        try:
            rows = team_history(club, session)
        except (requests.RequestException, ConnectionError):
            return club, []
        if since:
            rows = [r for r in rows if r.valid_to >= since]
        return club, rows

    results: dict[str, list[Rating]] = {}
    pending = list(clubs)
    for attempt in range(attempts):
        if not pending:
            break
        # Back off the concurrency each round; timeouts are the server shedding load.
        concurrency = max(1, workers // (2**attempt))
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for club, rows in pool.map(one, pending):
                results[club] = rows
        pending = [c for c in pending if not results[c]]
    return results
