"""API-Football: fixtures, per-match team statistics, lineups.

The third ingestion source, and the first paid one. It exists because the other
two each lack something that cannot be worked around. football-data.co.uk does
not publish Bulgaria, the Czech league or the UEFA competitions at all. FBref
publishes them but exposes no corner count per match, and corners per team is a
shipped market.

What it gives that neither of the others does, per match and per team: corners
alongside possession, passes, shots split inside and outside the box, and
expected goals. That is a richer row than the original five leagues get.

What it does not give, at any price, is historical odds. Pre-match prices live
for seven days and there is no archive, so competitions loaded through here can
never be scored against a closing line. Everything about their accuracy is
measured against a rolling frequency instead, and the honest consequence is that
"does this beat a bookmaker" is unanswerable for them.

Rate limits are per minute as well as per day, and the per-minute one bites
first: Ultra allows 450 a minute against 75,000 a day, so a backfill is paced by
the minute limit. The client below reads both from the response headers rather
than assuming a plan.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

import requests

SOURCE_CODE = "api_football"
BASE_URL = "https://v3.football.api-sports.io"

# core.competition.code -> API-Football league id.
LEAGUE_IDS: dict[str, int] = {
    "BUL-1L": 172,
    "CZE-1L": 345,
    "NOR-EL": 103,
    "INT-UCL": 2,
    "INT-UEL": 3,
    # Already held from football-data.co.uk, which publishes results and odds but
    # no forward calendar. These are here for upcoming fixtures only: the history
    # stays with the source that has the closing prices.
    "NED-ED": 88,
    "POR-PL": 94,
    "TUR-SL": 203,
    "BEL-PL": 144,
    # The five leagues with closing odds. Same restriction, and one addition: they
    # are also linked to their provider fixture ids so that event minutes and team
    # sheets can be fetched for them. Without a link the leagues a reader cares
    # most about were the only ones with no timeline and no lineups, which is an
    # odd way to build a football site.
    "ENG-PL": 39,
    "ESP-LL": 140,
    "ITA-SA": 135,
    "GER-BL": 78,
    "FRA-L1": 61,
}

# Provider status codes for a match that has finished, whatever the route to it.
FINISHED = frozenset({"FT", "AET", "PEN"})
# Codes meaning "has not been played and is still expected to be".
SCHEDULED = frozenset({"TBD", "NS"})
# Called off. Worth naming rather than lumping in with scheduled, because a
# postponed match keeps its original date and so looks, to anything checking that
# results arrive on time, exactly like a result that failed to load. That is not a
# hypothetical: Braga against Gil Vicente was called off on 16 August 2026 and the
# freshness check reported a missing result every run until this existed.
POSTPONED = frozenset({"PST", "CANC", "ABD", "SUSP", "INT", "WO", "AWD"})

# Competitions whose season label is the calendar year it was played in. Every
# other one here is labelled by the year it started, which is also what
# API-Football uses, so the two agree without translation.
SINGLE_YEAR_SEASONS = frozenset({"NOR-EL"})

# API-Football statistic name -> core.match_team_stat column.
STAT_MAP: dict[str, str] = {
    "Shots on Goal": "shots_on_target",
    "Shots off Goal": "shots_off_target",
    "Total Shots": "shots",
    "Blocked Shots": "shots_blocked",
    "Shots insidebox": "shots_inside_box",
    "Shots outsidebox": "shots_outside_box",
    "Fouls": "fouls_committed",
    "Corner Kicks": "corners",
    "Offsides": "offsides",
    "Yellow Cards": "yellow_cards",
    "Red Cards": "red_cards",
    "Goalkeeper Saves": "saves",
    "Total passes": "passes",
    "Passes accurate": "passes_accurate",
}
# Handled separately because they are not plain integers.
PERCENT_STATS = {"Ball Possession": "possession_pct"}
FLOAT_STATS = {"expected_goals": "xg"}


class ApiFootballError(RuntimeError):
    pass


def api_key() -> str:
    """The key from the environment, falling back to .env.

    Read at call time rather than import time so a missing key fails where it
    can be reported rather than at the top of an unrelated command.
    """
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if key:
        return key
    env = Path(".env")
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("API_FOOTBALL_KEY="):
                return line.split("=", 1)[1].strip()
    raise ApiFootballError(
        "API_FOOTBALL_KEY is not set. Put it in .env, which is gitignored."
    )


def season_for(competition_code: str, start_year: int) -> int:
    """API-Football labels a season by the year it began, which is what we store.

    Eliteserien runs inside one calendar year and is labelled by it, so the two
    conventions coincide there too. The distinction is kept explicit because it
    does not for every provider.
    """
    return start_year


@dataclass
class Client:
    """A thin session that respects the per-minute limit.

    The limit is read from response headers, so the pacing is right whatever plan
    the key is on rather than hard-coded to one. When the remaining allowance for
    the minute runs out the client waits for the window rather than collecting
    429s, because a 429 still costs a request against the daily quota.
    """

    session: requests.Session = field(default_factory=requests.Session)
    minute_limit: int = 450
    minute_remaining: int = 450
    day_remaining: int | None = None
    # Minimum gap between requests. The headers advertise 450 a minute, but
    # firing twenty inside one second is refused anyway, so the limit is not
    # purely a per-minute count and a steady pace is what actually works. 0.2s
    # is 300 an hour under the advertised ceiling and has not been refused.
    min_interval: float = 0.2
    max_retries: int = 5
    _last_request: float = 0.0
    _window_started: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.session.headers.update({"x-apisports-key": api_key()})

    def get(self, path: str, **params: Any) -> list[dict]:
        for attempt in range(self.max_retries):
            self._pace()
            response = self.session.get(f"{BASE_URL}{path}", params=params, timeout=60)
            self._absorb_headers(response)
            if response.status_code == 429 or self._is_rate_limited(response):
                # Only the per-minute window recovers on its own; back off into
                # the next one rather than retrying immediately.
                time.sleep(61 * (attempt + 1))
                continue
            response.raise_for_status()
            body = response.json()
            errors = body.get("errors")
            # An empty list is the success case; anything else is not.
            if errors and not isinstance(errors, list):
                raise ApiFootballError(f"{path} {params}: {errors}")
            return body.get("response", [])
        raise ApiFootballError(
            f"{path} {params}: still rate limited after {self.max_retries} attempts"
        )

    @staticmethod
    def _is_rate_limited(response: requests.Response) -> bool:
        """A refused request comes back as HTTP 200 with the complaint in the body.

        Worth stating because it is the opposite of what the status code implies:
        without this check the error surfaces as a parse failure somewhere later,
        long after the request that caused it.
        """
        try:
            errors = response.json().get("errors")
        except ValueError:
            return False
        if isinstance(errors, dict):
            return "rateLimit" in errors
        return False

    def _pace(self) -> None:
        gap = time.monotonic() - self._last_request
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        elapsed = time.monotonic() - self._window_started
        if elapsed >= 60:
            self._window_started = time.monotonic()
            self.minute_remaining = self.minute_limit
        elif self.minute_remaining <= 2:
            time.sleep(max(0.0, 60 - elapsed) + 1)
            self._window_started = time.monotonic()
            self.minute_remaining = self.minute_limit
        self._last_request = time.monotonic()

    def _absorb_headers(self, response: requests.Response) -> None:
        limit = response.headers.get("x-ratelimit-limit")
        remaining = response.headers.get("x-ratelimit-remaining")
        day = response.headers.get("x-ratelimit-requests-remaining")
        if limit and limit.isdigit():
            self.minute_limit = int(limit)
        if remaining and remaining.isdigit():
            self.minute_remaining = int(remaining)
        if day and day.isdigit():
            self.day_remaining = int(day)


@dataclass(frozen=True)
class Fixture:
    """One match as API-Football reports it."""

    fixture_id: int
    kickoff: datetime
    kickoff_date: date
    status: str
    stage: str
    # The provider's raw round label, kept because `stage` deliberately discards
    # the number in 'Regular Season - 17' and the matchday is worth having.
    round_label: str
    home_id: int
    away_id: int
    home_name: str
    away_name: str
    home_goals: int | None
    away_goals: int | None
    home_goals_ht: int | None
    away_goals_ht: int | None
    referee: str | None
    venue: str | None


@dataclass(frozen=True)
class TeamStat:
    """One side's statistics for one match, already mapped to our columns."""

    fixture_id: int
    team_id: int
    values: dict[str, float | int]


# Round labels that mean the round-robin phase. Anything else is a phase that can
# repeat a pairing, which is what core.match.stage exists to separate.
_REGULAR_PREFIXES = ("Regular Season", "Regular season")


def stage_of(round_label: str | None) -> str:
    """Map a round label onto our stage vocabulary.

    'Regular Season - 17' is matchday 17 of the round robin and carries no phase
    information worth keeping. Everything else — 'Group A - 3', 'Round of 16',
    'Championship Round' — names a phase in which two clubs may meet again.
    """
    label = (round_label or "").strip()
    if not label or label.startswith(_REGULAR_PREFIXES):
        return "regular"
    return label


def matchday_of(round_label: str | None) -> int | None:
    """The number in 'Regular Season - 17', when there is one."""
    label = (round_label or "").strip()
    if not label.startswith(_REGULAR_PREFIXES) or "-" not in label:
        return None
    tail = label.rsplit("-", 1)[1].strip()
    return int(tail) if tail.isdigit() else None


def fixtures(client: Client, competition_code: str, start_year: int) -> list[Fixture]:
    """Every fixture of one competition-season, in one request."""
    rows = client.get(
        "/fixtures",
        league=LEAGUE_IDS[competition_code],
        season=season_for(competition_code, start_year),
    )
    out: list[Fixture] = []
    for row in rows:
        fx, teams, goals = row["fixture"], row["teams"], row["goals"]
        kickoff = datetime.fromisoformat(fx["date"])
        half = row.get("score", {}).get("halftime", {}) or {}
        out.append(
            Fixture(
                fixture_id=fx["id"],
                kickoff=kickoff,
                kickoff_date=kickoff.date(),
                status=fx["status"]["short"],
                stage=stage_of(row["league"].get("round")),
                round_label=str(row["league"].get("round") or "").strip(),
                home_id=teams["home"]["id"],
                away_id=teams["away"]["id"],
                home_name=str(teams["home"]["name"]).strip(),
                away_name=str(teams["away"]["name"]).strip(),
                home_goals=goals.get("home"),
                away_goals=goals.get("away"),
                home_goals_ht=half.get("home"),
                away_goals_ht=half.get("away"),
                referee=(str(fx["referee"]).strip() or None) if fx.get("referee") else None,
                venue=((fx.get("venue") or {}).get("name") or None),
            )
        )
    return out


@dataclass(frozen=True)
class Event:
    """Something that happened at a known minute."""

    fixture_id: int
    team_id: int
    minute: int
    extra_minute: int | None
    kind: str
    detail: str | None
    player_name: str | None
    assist_name: str | None
    # The provider's own player id. Carried so events resolve to a player the same
    # way squads do, by id, rather than by a name that is no longer unique.
    player_id: int | None


@dataclass(frozen=True)
class Lineup:
    """One team's sheet: formation, coach, and who was named."""

    fixture_id: int
    team_id: int
    formation: str | None
    coach_name: str | None
    # (player name, shirt number, position, started, provider player id)
    players: tuple[tuple[str, int | None, str | None, bool, int | None], ...]


# API-Football's event vocabulary, mapped onto ours. Anything unrecognised becomes
# 'other' rather than being dropped: an unknown event still happened, and a
# timeline that silently omits things is worse than one with a vague entry.
EVENT_KINDS = {
    "goal": "goal",
    "card": "card",
    "subst": "substitution",
    "var": "var",
}


def events(client: Client, fixture_ids: list[int]) -> Iterator[Event]:
    """Goals, cards and substitutions with their minutes, one request per fixture."""
    for fixture_id in fixture_ids:
        for row in client.get("/fixtures/events", fixture=fixture_id):
            time = row.get("time") or {}
            minute = time.get("elapsed")
            if minute is None:
                continue
            team = (row.get("team") or {}).get("id")
            if team is None:
                continue
            yield Event(
                fixture_id=fixture_id,
                team_id=int(team),
                minute=int(minute),
                extra_minute=(
                    int(time["extra"]) if time.get("extra") is not None else None
                ),
                kind=EVENT_KINDS.get(str(row.get("type", "")).lower(), "other"),
                detail=(str(row.get("detail")).strip() or None) if row.get("detail") else None,
                player_name=((row.get("player") or {}).get("name") or None),
                assist_name=((row.get("assist") or {}).get("name") or None),
                player_id=(
                    int((row.get("player") or {})["id"])
                    if (row.get("player") or {}).get("id") is not None
                    else None
                ),
            )


def lineups(client: Client, fixture_ids: list[int]) -> Iterator[Lineup]:
    """Team sheets, one request per fixture.

    Confirmed lineups appear roughly an hour before kickoff, so this is useful
    both as history and, run close to kickoff, as the live team news.
    """
    for fixture_id in fixture_ids:
        for row in client.get("/fixtures/lineups", fixture=fixture_id):
            team = (row.get("team") or {}).get("id")
            if team is None:
                continue
            named: list[tuple[str, int | None, str | None, bool, int | None]] = []
            for group, started in (("startXI", True), ("substitutes", False)):
                for entry in row.get(group) or []:
                    p = entry.get("player") or {}
                    if not p.get("name"):
                        continue
                    named.append((
                        str(p["name"]).strip(),
                        int(p["number"]) if p.get("number") is not None else None,
                        (str(p.get("pos")).strip() or None) if p.get("pos") else None,
                        started,
                        int(p["id"]) if p.get("id") is not None else None,
                    ))
            yield Lineup(
                fixture_id=fixture_id,
                team_id=int(team),
                formation=(str(row.get("formation")).strip() or None)
                if row.get("formation") else None,
                coach_name=((row.get("coach") or {}).get("name") or None),
                players=tuple(named),
            )


@dataclass(frozen=True)
class SquadPlayer:
    """One player on a club's current roster."""

    team_id: int
    player_id: int
    name: str
    age: int | None
    shirt_number: int | None
    position: str | None
    photo_url: str | None


@dataclass(frozen=True)
class Absence:
    """A player the provider says will miss, or may miss, one specific fixture."""

    fixture_id: int
    team_id: int
    player_id: int
    player_name: str
    # 'out' or 'doubtful'.
    status: str
    reason: str | None


# The provider's two words for availability. 'Missing Fixture' is definite and
# 'Questionable' is not; anything else it invents is treated as doubtful, because
# overstating a certainty is the worse of the two errors on a team sheet.
ABSENCE_STATUS = {"missing fixture": "out", "questionable": "doubtful"}


def squads(client: Client, team_ids: Iterable[int]) -> Iterator[SquadPlayer]:
    """Current rosters, one request per club.

    There is no season parameter: the endpoint describes the squad today. A player
    sold in January is simply gone, so this is refreshed rather than accumulated.
    """
    for team_id in team_ids:
        for row in client.get("/players/squads", team=team_id):
            reported = (row.get("team") or {}).get("id")
            for player in row.get("players") or []:
                if not player.get("id") or not player.get("name"):
                    continue
                yield SquadPlayer(
                    team_id=int(reported or team_id),
                    player_id=int(player["id"]),
                    name=str(player["name"]).strip(),
                    age=int(player["age"]) if player.get("age") is not None else None,
                    shirt_number=(
                        int(player["number"]) if player.get("number") is not None else None
                    ),
                    position=(
                        str(player["position"]).strip() if player.get("position") else None
                    ),
                    photo_url=player.get("photo") or None,
                )


def absences(client: Client, day: date) -> Iterator[Absence]:
    """Everyone missing a fixture on one date, across every competition.

    One request covers the whole day in every league the plan includes, which is
    the reason this is affordable for fourteen competitions rather than five. The
    data appears roughly three days before kickoff and not before, so asking about
    next month returns nothing and costs a request to find out.
    """
    for row in client.get("/injuries", date=day.isoformat()):
        player = row.get("player") or {}
        fixture = (row.get("fixture") or {}).get("id")
        team = (row.get("team") or {}).get("id")
        if not player.get("id") or fixture is None or team is None:
            continue
        yield Absence(
            fixture_id=int(fixture),
            team_id=int(team),
            player_id=int(player["id"]),
            player_name=str(player.get("name") or "").strip(),
            status=ABSENCE_STATUS.get(
                str(player.get("type") or "").strip().lower(), "doubtful"
            ),
            reason=(str(player["reason"]).strip() or None) if player.get("reason") else None,
        )


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().rstrip("%")
    if not text:
        return None
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return None


def statistics(client: Client, fixture_ids: list[int]) -> Iterator[TeamStat]:
    """Team statistics for a batch of fixtures, one request each.

    This is the expensive call — everything else is one request per season — so
    it is a generator, letting a caller commit as it goes rather than holding a
    season in memory and losing it all to one failure near the end.
    """
    for fixture_id in fixture_ids:
        for block in client.get("/fixtures/statistics", fixture=fixture_id):
            values: dict[str, float | int] = {}
            for item in block.get("statistics", []):
                name, raw = item.get("type"), item.get("value")
                target = (
                    STAT_MAP.get(name)
                    or PERCENT_STATS.get(name)
                    or FLOAT_STATS.get(name)
                )
                if target is None:
                    continue
                number = _number(raw)
                if number is not None:
                    values[target] = number
            if values:
                yield TeamStat(
                    fixture_id=fixture_id,
                    team_id=block["team"]["id"],
                    values=values,
                )
