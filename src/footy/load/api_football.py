"""Load API-Football fixtures and team statistics into core.*.

Team identity is the part worth reading. API-Football numbers its clubs, and that
number is stored in `core.team_alias.source_team_id`, which makes the join stable
against renames and spelling. But a club arriving here is very often one we
already hold under another source — every Champions League tie is between two
clubs already in their domestic leagues — so seeding must find the existing team
rather than create a second one. A duplicate Arsenal would be worse than a
missing one: the ratings would silently split across two identities and every
number computed from them would be wrong while looking fine.

Resolution runs in three steps, most reliable first: an existing alias for this
source's id, then an existing team whose normalised name matches, then a new
team. Only the third creates anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Self

import psycopg

from footy import db
from footy.sources.api_football import (
    FINISHED,
    SCHEDULED,
    SOURCE_CODE,
    Fixture,
    TeamStat,
    matchday_of,
)

# Written to core.match_team_stat. Kept explicit rather than derived from the
# source's mapping so that adding a statistic there cannot silently change the
# shape of a table this writes into.
STAT_COLUMNS = [
    "shots", "shots_on_target", "shots_off_target", "shots_blocked",
    "shots_inside_box", "shots_outside_box", "corners", "fouls_committed",
    "offsides", "yellow_cards", "red_cards", "saves", "passes",
    "passes_accurate", "possession_pct", "xg",
]


@dataclass
class LoadResult:
    teams: int = 0
    aliases: int = 0
    matches: int = 0
    stats: int = 0

    def __iadd__(self, other: LoadResult) -> Self:
        self.teams += other.teams
        self.aliases += other.aliases
        self.matches += other.matches
        self.stats += other.stats
        return self


def seed_teams(
    conn: psycopg.Connection, fixtures: Iterable[Fixture], country: str | None
) -> tuple[int, int]:
    """Register this source's clubs, reusing existing teams wherever they exist.

    `country` is the competition's country, or None for the UEFA competitions
    where the clubs come from everywhere. A new team created without one is left
    with a null country rather than being given a wrong one.
    """
    seen: dict[int, str] = {}
    for fixture in fixtures:
        seen.setdefault(fixture.home_id, fixture.home_name)
        seen.setdefault(fixture.away_id, fixture.away_name)
    if not seen:
        return 0, 0

    rows = [(str(team_id), name) for team_id, name in sorted(seen.items())]
    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_af_team",
            ["source_team_id", "source_name"],
            rows,
            "create temporary table _af_team (source_team_id text, source_name text)",
        )

        # Step two: an existing team whose normalised name matches. Restricted to
        # clubs with no alias for this source yet, so an already-linked club is
        # never re-pointed at a namesake.
        #
        # `distinct on` because the name is not unique in core.team either — two
        # clubs normalising to 'drita' would otherwise produce two alias rows for
        # one provider id and violate the id constraint. Picking the lowest
        # team_id is arbitrary but deterministic, which matters more: a re-run
        # must reach the same answer as the first run.
        cur.execute(
            """
            insert into core.team_alias (team_id, source_id, source_team_id, alias_name)
            select distinct on (a.source_team_id)
                   t.team_id, src.source_id, a.source_team_id, a.source_name
              from _af_team a
              join core.source src on src.code = %s
              join core.team t on core.norm_name(t.canonical_name)
                                = core.norm_name(a.source_name)
             where not exists (
                    select 1 from core.team_alias x
                     where x.source_id = src.source_id
                       and x.source_team_id = a.source_team_id)
             order by a.source_team_id, t.team_id
            """,
            (SOURCE_CODE,),
        )
        linked = cur.rowcount

        # Step three: whatever is still unresolved is genuinely new.
        cur.execute(
            """
            insert into core.team (canonical_name, country)
            select distinct a.source_name, %s
              from _af_team a
              join core.source src on src.code = %s
             where not exists (
                    select 1 from core.team_alias x
                     where x.source_id = src.source_id
                       and x.source_team_id = a.source_team_id)
            """,
            (country, SOURCE_CODE),
        )
        created = cur.rowcount

        cur.execute(
            """
            insert into core.team_alias (team_id, source_id, source_team_id, alias_name)
            select distinct on (a.source_team_id)
                   t.team_id, src.source_id, a.source_team_id, a.source_name
              from _af_team a
              join core.source src on src.code = %s
              join core.team t on core.norm_name(t.canonical_name)
                                = core.norm_name(a.source_name)
             where not exists (
                    select 1 from core.team_alias x
                     where x.source_id = src.source_id
                       and x.source_team_id = a.source_team_id)
             order by a.source_team_id, t.team_id
            """,
            (SOURCE_CODE,),
        )
        linked += cur.rowcount
        cur.execute("drop table _af_team")
    return created, linked


def store_fixtures(
    conn: psycopg.Connection,
    competition_code: str,
    start_year: int,
    fixtures: list[Fixture],
    include_scheduled: bool = False,
) -> tuple[int, dict[int, int]]:
    """Write matches and return a map of API fixture id -> our match id.

    Finished matches always. Scheduled ones only when asked, because for the nine
    leagues that already have results from football-data.co.uk the useful part of
    this source is the forward calendar and nothing else — pulling their history
    through here as well would put two sources in a race to own the same rows,
    and the other one has the closing odds.

    A scheduled row carries no score and status 'scheduled', which is what makes
    it eligible for prediction rather than settlement.
    """
    wanted = set(FINISHED) | (set(SCHEDULED) if include_scheduled else set())
    played = [f for f in fixtures if f.status in wanted]
    if not played:
        return 0, {}

    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_af_fixture",
            ["fixture_id", "kickoff_date", "kickoff_utc", "home_source_id",
             "away_source_id", "home_goals", "away_goals", "home_goals_ht",
             "away_goals_ht", "referee", "venue", "stage", "matchday"],
            (
                [f.fixture_id, f.kickoff_date, f.kickoff, str(f.home_id),
                 str(f.away_id), f.home_goals, f.away_goals, f.home_goals_ht,
                 f.away_goals_ht, f.referee, f.venue, f.stage,
                 matchday_of(f.round_label)]
                for f in played
            ),
            """
            create temporary table _af_fixture (
                fixture_id bigint, kickoff_date date, kickoff_utc timestamptz,
                home_source_id text, away_source_id text,
                home_goals smallint, away_goals smallint,
                home_goals_ht smallint, away_goals_ht smallint,
                referee text, venue text, stage text, matchday smallint
            )
            """,
        )

        cur.execute(
            """
            insert into core.referee (canonical_name)
            select distinct on (core.norm_name(referee)) referee
              from _af_fixture where referee is not null
             order by core.norm_name(referee), referee
            on conflict (core.norm_name(canonical_name)) do nothing
            """
        )

        cur.execute(
            """
            create temporary table _af_resolved as
            select f.*, c.competition_id, se.season_id,
                   h.team_id as home_team_id, a.team_id as away_team_id,
                   r.referee_id
              from _af_fixture f
              join core.source src on src.code = %s
              join core.competition c on c.code = %s
              join core.season se on se.competition_id = c.competition_id
                                 and se.start_year = %s
              join core.team_alias h on h.source_id = src.source_id
                                    and h.source_team_id = f.home_source_id
              join core.team_alias a on a.source_id = src.source_id
                                    and a.source_team_id = f.away_source_id
              left join core.referee r
                     on f.referee is not null
                    and core.norm_name(r.canonical_name) = core.norm_name(f.referee)
            """,
            (SOURCE_CODE, competition_code, start_year),
        )
        cur.execute("select count(*) from _af_resolved")
        resolved = cur.fetchone()[0]
        if resolved != len(played):
            raise RuntimeError(
                f"{competition_code} {start_year}: resolved {resolved} of "
                f"{len(played)} fixtures; a team alias is missing"
            )

        cur.execute(
            """
            insert into core.match (
                competition_id, season_id, kickoff_date, kickoff_utc, status,
                home_team_id, away_team_id, home_goals_ft, away_goals_ft,
                home_goals_ht, away_goals_ht, referee_id, venue_name, stage, matchday
            )
            select competition_id, season_id, kickoff_date, kickoff_utc,
                   case when home_goals is null then 'scheduled' else 'finished' end,
                   home_team_id, away_team_id, home_goals, away_goals,
                   home_goals_ht, away_goals_ht, referee_id, venue, stage, matchday
              from _af_resolved
            on conflict (season_id, home_team_id, away_team_id, stage) do update
                -- coalesce on the scores so a later pass that sees a fixture as
                -- unplayed cannot erase a result another source already stored.
                set home_goals_ft = coalesce(excluded.home_goals_ft,
                                             core.match.home_goals_ft),
                    away_goals_ft = coalesce(excluded.away_goals_ft,
                                             core.match.away_goals_ft),
                    home_goals_ht = coalesce(excluded.home_goals_ht,
                                             core.match.home_goals_ht),
                    away_goals_ht = coalesce(excluded.away_goals_ht,
                                             core.match.away_goals_ht),
                    kickoff_date  = excluded.kickoff_date,
                    kickoff_utc   = coalesce(excluded.kickoff_utc, core.match.kickoff_utc),
                    referee_id    = coalesce(excluded.referee_id, core.match.referee_id),
                    venue_name    = coalesce(excluded.venue_name, core.match.venue_name),
                    matchday      = coalesce(excluded.matchday, core.match.matchday),
                    status        = case
                                      when coalesce(excluded.home_goals_ft,
                                                    core.match.home_goals_ft) is null
                                      then 'scheduled' else 'finished'
                                   end,
                    updated_at    = now()
            """
        )
        written = cur.rowcount

        cur.execute(
            """
            create temporary table _af_map as
            select r.fixture_id, m.match_id
              from _af_resolved r
              join core.match m on m.season_id = r.season_id
                               and m.home_team_id = r.home_team_id
                               and m.away_team_id = r.away_team_id
                               and m.stage = r.stage
            """
        )
        cur.execute(
            """
            insert into core.match_source (match_id, source_id, source_match_id)
            select m.match_id, src.source_id, m.fixture_id::text
              from _af_map m cross join core.source src
             where src.code = %s
            on conflict (match_id, source_id) do update
                set source_match_id = excluded.source_match_id, ingested_at = now()
            """,
            (SOURCE_CODE,),
        )
        # A row per team per match, carrying goals and nothing else, for every
        # match written. Statistics arrive separately and are missing for a
        # fifth of these competitions, and core.team_match is driven by this
        # table — so without this a match with a known score but no statistics
        # would be invisible to the feature layer, and a team's "last five
        # matches" would silently skip it. Goals are known from the fixture, so
        # there is no reason to lose them.
        #
        # Inserted before store_stats and never overwriting it: the statistics
        # upsert coalesces, so real values land on top of these and nulls here
        # never erase anything.
        cur.execute(
            """
            insert into core.match_team_stat (
                match_id, team_id, period, is_home, opponent_team_id,
                goals, goals_conceded, source_id
            )
            select m.match_id, t.team_id, 'FT', t.is_home, t.opponent_id,
                   t.goals, t.conceded, src.source_id
              from _af_map am
              join core.match m on m.match_id = am.match_id
             cross join core.source src
             cross join lateral (values
                    (m.home_team_id, true,  m.away_team_id,
                     m.home_goals_ft, m.away_goals_ft),
                    (m.away_team_id, false, m.home_team_id,
                     m.away_goals_ft, m.home_goals_ft)
                 ) as t(team_id, is_home, opponent_id, goals, conceded)
             where src.code = %s and m.home_goals_ft is not null
            on conflict (match_id, team_id, period) do nothing
            """,
            (SOURCE_CODE,),
        )

        cur.execute("select fixture_id, match_id from _af_map")
        mapping = dict(cur.fetchall())
        for table in ("_af_fixture", "_af_resolved", "_af_map"):
            cur.execute(f"drop table if exists {table}")
    return written, mapping


def store_stats(
    conn: psycopg.Connection, match_ids: dict[int, int], stats: Iterable[TeamStat]
) -> int:
    """Write full-time team statistics.

    Period is always 'FT': API-Football reports one set per match, not per half.
    The halves are left null rather than guessed, which is the same choice the
    football-data.co.uk loader makes for everything except goals.
    """
    rows = []
    for stat in stats:
        match_id = match_ids.get(stat.fixture_id)
        if match_id is None:
            continue
        rows.append(
            [match_id, str(stat.team_id)]
            + [stat.values.get(column) for column in STAT_COLUMNS]
        )
    if not rows:
        return 0

    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_af_stat",
            ["match_id", "source_team_id", *STAT_COLUMNS],
            rows,
            f"""
            create temporary table _af_stat (
                match_id bigint, source_team_id text,
                {", ".join(f"{c} numeric" for c in STAT_COLUMNS)}
            )
            """,
        )
        cur.execute(
            f"""
            insert into core.match_team_stat (
                match_id, team_id, period, is_home, opponent_team_id,
                goals, goals_conceded, source_id, {", ".join(STAT_COLUMNS)}
            )
            select s.match_id, ta.team_id, 'FT',
                   ta.team_id = m.home_team_id,
                   case when ta.team_id = m.home_team_id
                        then m.away_team_id else m.home_team_id end,
                   case when ta.team_id = m.home_team_id
                        then m.home_goals_ft else m.away_goals_ft end,
                   case when ta.team_id = m.home_team_id
                        then m.away_goals_ft else m.home_goals_ft end,
                   src.source_id,
                   {", ".join("s." + c for c in STAT_COLUMNS)}
              from _af_stat s
              join core.source src on src.code = %s
              join core.team_alias ta on ta.source_id = src.source_id
                                     and ta.source_team_id = s.source_team_id
              join core.match m on m.match_id = s.match_id
            on conflict (match_id, team_id, period) do update
                set {", ".join(f"{c} = coalesce(excluded.{c}, core.match_team_stat.{c})"
                               for c in STAT_COLUMNS)},
                    updated_at = now()
            """,
            (SOURCE_CODE,),
        )
        written = cur.rowcount
        cur.execute("drop table _af_stat")
    return written
