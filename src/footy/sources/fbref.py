"""FBref match sheets: who started, who came on, and what each of them did.

FBref publishes one page per match containing both the team sheet and per-player
match statistics. soccerdata fetches that page through a real browser and caches
the HTML, so the two readers we use cost one request between them, and a re-run
costs none.

Rate limiting is not negotiable here. Sports Reference asks for no more than ten
requests a minute and soccerdata defaults to one every seven seconds, which is
already at that limit. It is not raised. A full Premier League season is 380
pages, so roughly seventy minutes, and the loader is written to resume rather
than to be run in one sitting.

Season labels are FBref's own: "2425" means 2024-25, which we store as
start_year 2024. Note that FBref currently serves the 2026-27 page for the
2025-2026 URL, so that season is unavailable through this path and the mapping
below stops at 2024.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import date

import pandas as pd

SOURCE_CODE = "fbref"

# soccerdata's league keys, mapped to ours.
LEAGUE_KEYS = {
    "ENG-PL": "ENG-Premier League",
    "ESP-LL": "ESP-La Liga",
    "GER-BL": "GER-Bundesliga",
    "ITA-SA": "ITA-Serie A",
    "FRA-L1": "FRA-Ligue 1",
    # Not in soccerdata's built-in list. These resolve through the custom league
    # dict this project writes, and the FBref names in it are exact matches
    # against FBref's own table of 158 competitions — "Champions League" and
    # "Bulgarian First League" both return nothing, the latter because it does
    # not exist.
    "CZE-1L": "CZE-First League",
    "NOR-EL": "NOR-Eliteserien",
}

# Competitions whose season is one calendar year rather than two.
SINGLE_YEAR_SEASONS = frozenset({"NOR-EL"})


def season_label(start_year: int, competition_code: str | None = None) -> str:
    """2024 -> '2425', the label FBref uses for the 2024-25 season.

    Eliteserien runs March to December, so FBref labels it by the single year it
    was played in. Passing the competition is optional only so the existing
    callers, all of which are two-year leagues, keep working unchanged.
    """
    if competition_code in SINGLE_YEAR_SEASONS:
        return str(start_year)
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


# Per-player counting stats on the match page, mapped to our column names. The
# keys are the flattened two-level headers soccerdata produces.
STAT_MAP = {
    ("Performance", "Gls"): "goals",
    ("Performance", "Ast"): "assists",
    ("Performance", "Sh"): "shots",
    ("Performance", "SoT"): "shots_on_target",
    ("Performance", "PK"): "penalties_scored",
    ("Performance", "PKatt"): "penalties_attempted",
    ("Performance", "CrdY"): "yellows",
    ("Performance", "CrdR"): "reds",
    ("Performance", "Fls"): "fouls_committed",
    ("Performance", "Fld"): "fouls_drawn",
    ("Performance", "TklW"): "tackles_won",
    ("Performance", "Int"): "interceptions",
    ("Performance", "Crs"): "crosses",
    ("Performance", "Off"): "offsides",
    ("Performance", "OG"): "own_goals",
}


@dataclass(frozen=True)
class ScheduledMatch:
    """A fixture as FBref lists it, before it is linked to one of ours."""

    game_id: str
    kickoff_date: date
    home_name: str
    away_name: str
    referee: str | None = None


@dataclass(frozen=True)
class Appearance:
    """One player in one match. Counting stats are None for an unused
    substitute, which is not the same as zero and must not be stored as it."""

    team_name: str
    player_name: str
    is_starter: bool
    position: str | None
    shirt_number: int | None
    minutes: int
    stats: dict[str, int | None]


def reader(competition_code: str, start_year: int):
    """A soccerdata FBref reader for one competition-season.

    One season per reader, deliberately. Asking for several at once made the
    schedule for one of them come back holding another's fixtures.
    """
    import soccerdata as sd

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return sd.FBref(
            leagues=LEAGUE_KEYS[competition_code],
            seasons=[season_label(start_year, competition_code)],
        )


def schedule(fb) -> list[ScheduledMatch]:
    """Every match of the season that has been played.

    A missing game_id means the fixture has no match page yet, which is how
    unplayed fixtures appear.

    The schedule also names the referee, at full coverage back to 2014-15. That
    is one request per season for something football-data.co.uk publishes only
    for England.
    """
    df = fb.read_schedule().reset_index()
    has_referee = "referee" in df.columns
    out = []
    for row in df.itertuples():
        if not isinstance(row.game_id, str) or pd.isna(row.date):
            continue
        referee = getattr(row, "referee", None) if has_referee else None
        out.append(
            ScheduledMatch(
                game_id=row.game_id,
                kickoff_date=row.date.date(),
                home_name=str(row.home_team),
                away_name=str(row.away_team),
                referee=(
                    str(referee).strip()
                    if referee is not None and not pd.isna(referee) and str(referee).strip()
                    else None
                ),
            )
        )
    return out


@dataclass(frozen=True)
class Result:
    """A played match, as FBref's schedule reports it.

    `stage` comes from FBref's own round label rather than being inferred. That
    is a real improvement on the football-data.co.uk path, where the phase has to
    be deduced from repeated pairings: the Czech league runs six named rounds and
    FBref names all of them.
    """

    kickoff_date: date
    home_name: str
    away_name: str
    home_goals: int
    away_goals: int
    stage: str
    referee: str | None = None
    venue: str | None = None


@dataclass(frozen=True)
class TeamMatchStat:
    """One side's counting stats for one match.

    Identified by date, opponent and whether it was at home, because the team
    name itself is unusable: soccerdata leaves the `team` and `league` index
    levels empty for leagues outside its built-in list, which is every league
    read through this path. Date plus opponent plus venue picks out the same
    fixture and is populated.

    No corners. FBref's per-match team endpoint exposes schedule, shooting,
    keeper and misc, and corner kicks are in none of them.
    """

    kickoff_date: date
    opponent_name: str
    is_home: bool
    goals: int | None = None
    shots: int | None = None
    shots_on_target: int | None = None
    fouls_committed: int | None = None
    fouls_drawn: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None
    offsides: int | None = None
    crosses: int | None = None
    interceptions: int | None = None


# Stat endpoint and flattened column -> our column name.
TEAM_STAT_MAP = {
    ("shooting", "Standard/Sh"): "shots",
    ("shooting", "Standard/SoT"): "shots_on_target",
    ("misc", "Performance/Fls"): "fouls_committed",
    ("misc", "Performance/Fld"): "fouls_drawn",
    ("misc", "Performance/CrdY"): "yellow_cards",
    ("misc", "Performance/CrdR"): "red_cards",
    ("misc", "Performance/Off"): "offsides",
    ("misc", "Performance/Crs"): "crosses",
    ("misc", "Performance/Int"): "interceptions",
}

# FBref round labels that mean "the round-robin part of the season". Everything
# else in a domestic competition is a phase that follows it, and is stored as
# such so a pairing can occur twice.
REGULAR_ROUNDS = frozenset({"Regular season", "Regular Season", ""})


def _score(value) -> tuple[int, int] | None:
    """FBref writes a score as '2–1', with an en dash, and leaves it blank for
    anything unplayed."""
    text = _text(value)
    if not text:
        return None
    for dash in ("\u2013", "-"):
        if dash in text:
            home, _, away = text.partition(dash)
            try:
                return int(home.strip()), int(away.strip())
            except ValueError:
                return None
    return None


def _count(value) -> int | None:
    """An integer from a match-log cell.

    Goals in a knockout tie are written '1 (3)', the bracket being the shootout.
    The shootout is not a goal and the bracket is dropped. Plain `_as_int` raises
    on these, which is how they were found: they only appear in the European
    fixtures that arrive mixed in with the league ones.
    """
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, str):
        value = value.split("(")[0].strip()
        if not value:
            return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def results(fb) -> list[Result]:
    """Every played match of the season, with its score and phase."""
    df = fb.read_schedule().reset_index()
    has_referee = "referee" in df.columns
    out = []
    for row in df.itertuples():
        goals = _score(getattr(row, "score", None))
        if goals is None or pd.isna(row.date):
            continue
        home, away = str(row.home_team).strip(), str(row.away_team).strip()
        if not home or not away or "nan" in (home, away):
            continue
        rnd = _text(getattr(row, "round", None)) or ""
        referee = getattr(row, "referee", None) if has_referee else None
        out.append(
            Result(
                kickoff_date=row.date.date(),
                home_name=home,
                away_name=away,
                home_goals=goals[0],
                away_goals=goals[1],
                stage="regular" if rnd in REGULAR_ROUNDS else rnd,
                referee=_text(referee),
                venue=_text(getattr(row, "venue", None)),
            )
        )
    return out


def team_stats(fb) -> list[TeamMatchStat]:
    """Per-team counting stats for the season, from the bulk match-log endpoint.

    Two requests per team-season rather than one per match, which is the only
    reason a twelve-season backfill is hours rather than days.

    The rows returned cover every competition a club played in, so European
    fixtures arrive alongside league ones. They are not filtered here — the
    loader drops whatever does not match a league fixture, and the discards are
    worth keeping in mind, being exactly the continental matches the congestion
    features have never had.
    """
    frames = {}
    for stat_type in ("shooting", "misc"):
        df = fb.read_team_match_stats(stat_type=stat_type).reset_index()
        df.columns = [
            "/".join(str(x) for x in c if x and not str(x).startswith("Unnamed"))
            if isinstance(c, tuple)
            else str(c)
            for c in df.columns
        ]
        frames[stat_type] = df

    # to_dict keeps the flattened column names exactly; itertuples would mangle
    # the slash in 'Standard/Sh' and silently read nothing.
    merged: dict[tuple, dict] = {}
    for stat_type, df in frames.items():
        for values in df.to_dict("records"):
            day, opponent = values.get("date"), _text(values.get("opponent"))
            venue = _text(values.get("venue"))
            if day is None or pd.isna(day) or not opponent or venue not in ("Home", "Away"):
                continue
            key = (day.date(), opponent, venue == "Home")
            entry = merged.setdefault(
                key,
                {"kickoff_date": key[0], "opponent_name": opponent, "is_home": key[2],
                 "goals": _count(values.get("GF"))},
            )
            for (source, column), target in TEAM_STAT_MAP.items():
                if source == stat_type and column in values:
                    entry[target] = _count(values[column])
    return [TeamMatchStat(**v) for v in merged.values()]


@dataclass(frozen=True)
class Fixture:
    """A match that has not been played yet."""

    kickoff_date: date
    home_name: str
    away_name: str
    matchday: int | None = None
    venue: str | None = None


def fixtures(fb) -> list[Fixture]:
    """The season's calendar, whether or not the matches have been played.

    The counterpart to `schedule`, which drops anything without a game_id
    because it is only interested in matches with a page to scrape. Here that
    same absence is the point: a fixture list is published months before any of
    it has a result.

    Rows with no date are dropped, which is how FBref renders a fixture whose
    date is still to be confirmed.
    """
    df = fb.read_schedule().reset_index()
    out = []
    for row in df.itertuples():
        if pd.isna(row.date):
            continue
        home, away = str(row.home_team).strip(), str(row.away_team).strip()
        if not home or not away or home == "nan" or away == "nan":
            continue
        out.append(
            Fixture(
                kickoff_date=row.date.date(),
                home_name=home,
                away_name=away,
                matchday=_as_int(getattr(row, "week", None)),
                venue=_text(getattr(row, "venue", None)),
            )
        )
    return out


def _flatten(columns) -> list:
    return [
        tuple(str(x) for x in c if x and not str(x).startswith("Unnamed"))
        if isinstance(c, tuple)
        else (str(c),)
        for c in columns
    ]


def _as_int(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _text(value) -> str | None:
    """A trimmed string, or None for anything pandas considers missing."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def sheets(fb, game_ids: list[str]) -> dict[str, list[Appearance]]:
    """Team sheets for a batch of matches, keyed by FBref game id.

    The lineup is the source of truth for who was in the squad, because it
    includes unused substitutes that the statistics table omits. Statistics are
    joined onto it where they exist.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lineups = fb.read_lineup(match_id=game_ids).reset_index()
        stats = fb.read_player_match_stats(
            stat_type="summary", match_id=game_ids
        ).reset_index()

    stats.columns = ["/".join(c) for c in _flatten(stats.columns)]
    stats = stats.rename(
        columns={"/".join(k): v for k, v in STAT_MAP.items()}
    )

    by_player: dict[tuple[str, str, str], dict] = {}
    # The statistics table carries both the match label and the match id; the
    # lineup table carries only the label, so this is also the bridge between them.
    label_to_id: dict[str, str] = {}
    for row in stats.to_dict("records"):
        gid = row.get("game_id")
        if not isinstance(gid, str):
            continue
        label_to_id[str(row.get("game"))] = gid
        by_player[(gid, str(row.get("team")), str(row.get("player")))] = row

    out: dict[str, list[Appearance]] = {gid: [] for gid in game_ids}
    for row in lineups.to_dict("records"):
        gid = label_to_id.get(str(row.get("game")))
        if gid is None:
            continue
        team, player = str(row["team"]), str(row["player"])
        s = by_player.get((gid, team, player), {})
        out[gid].append(
            Appearance(
                team_name=team,
                player_name=player,
                is_starter=bool(row["is_starter"]),
                position=(str(row["position"]) if row.get("position") else None),
                shirt_number=_as_int(row.get("jersey_number")),
                minutes=_as_int(row.get("minutes_played")) or 0,
                stats={col: _as_int(s.get(col)) for col in STAT_MAP.values()}
                if s
                else dict.fromkeys(STAT_MAP.values()),
            )
        )
    return out


def sheets_where_possible(
    fb, game_ids: list[str], cool_off: int = 120
) -> tuple[dict[str, list[Appearance]], list[str]]:
    """Fetch a batch, giving up on individual matches rather than on the league.

    soccerdata already retries a page five times before raising, so a failure
    here means a CAPTCHA or a block rather than a blip. The batch is then retried
    one match at a time, because the usual cause is a single bad page and the
    other nine are fine — and one unreadable page previously cost the remaining
    1,770 matches of a league.

    Skipped matches are simply not stored, so `core.lineup_coverage` still
    describes exactly what landed and a later re-run picks them up.
    """
    import time

    try:
        return sheets(fb, game_ids), []
    except Exception:
        pass

    # Whatever blocked the batch is unlikely to clear instantly.
    time.sleep(cool_off)

    out: dict[str, list[Appearance]] = {}
    failed: list[str] = []
    for game_id in game_ids:
        try:
            out.update(sheets(fb, [game_id]))
        except Exception:
            failed.append(game_id)
    return out, failed
