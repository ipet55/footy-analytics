"""Load parsed football-data.co.uk records into core.*.

Everything goes through unlogged staging tables and a single INSERT ... ON CONFLICT
per target, so a re-run is idempotent: loading the same season twice yields the same
row count, never duplicates. Team names are resolved by joining core.team_alias, and
the load aborts if any name fails to resolve rather than dropping matches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

import psycopg

from footy import db
from footy.sources.fd_parse import STAT_COLUMNS, ParsedSeason
from footy.sources.football_data_uk import SOURCE_CODE
from footy.teams import COMPETITION_COUNTRY, canonical, short

MATCH_COLUMNS = [
    "row_id",
    "competition_code",
    "start_year",
    "kickoff_date",
    "kickoff_utc",
    "home_name",
    "away_name",
    "home_goals_ft",
    "away_goals_ft",
    "home_goals_ht",
    "away_goals_ht",
    "referee_name",
    "source_match_id",
    "stage",
]

ODDS_COLUMNS = ["row_id", "bookmaker", "market", "outcome", "line", "price", "snapshot"]
STAT_STAGE_COLUMNS = ["row_id", "is_home", "period", *STAT_COLUMNS]


@dataclass
class LoadResult:
    matches: int = 0
    team_stats: int = 0
    odds: int = 0

    def __iadd__(self, other: LoadResult) -> Self:
        self.matches += other.matches
        self.team_stats += other.team_stats
        self.odds += other.odds
        return self


def seed_teams(conn: psycopg.Connection, seasons: list[ParsedSeason]) -> tuple[int, int]:
    """Create canonical teams and register this source's spelling for each.

    Country comes from the competition the name appears in, which is unambiguous
    here because no club appears in two of the five domestic leagues.
    """
    seen: dict[str, str] = {}
    for season in seasons:
        country = COMPETITION_COUNTRY[season.competition_code]
        for match in season.matches:
            seen.setdefault(match["home_name"], country)
            seen.setdefault(match["away_name"], country)

    rows = [
        (raw, canonical(raw), short(canonical(raw)), country)
        for raw, country in sorted(seen.items())
    ]

    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_stage_team",
            ["source_name", "canonical_name", "short_name", "country"],
            rows,
            """
            create temporary table _stage_team (
                source_name    text,
                canonical_name text,
                short_name     text,
                country        text
            )
            """,
        )

        cur.execute(
            """
            insert into core.team (canonical_name, short_name, country)
            select distinct on (core.norm_name(canonical_name))
                   canonical_name, short_name, country
              from _stage_team
             order by core.norm_name(canonical_name), canonical_name
            on conflict (core.norm_name(canonical_name)) do update
                set short_name = coalesce(core.team.short_name, excluded.short_name),
                    country    = coalesce(core.team.country, excluded.country),
                    updated_at = now()
            """
        )
        teams = cur.rowcount

        cur.execute(
            """
            insert into core.team_alias (team_id, source_id, alias_name)
            select t.team_id, s.source_id, st.source_name
              from _stage_team st
              join core.team t on core.norm_name(t.canonical_name) = core.norm_name(st.canonical_name)
             cross join core.source s
             where s.code = %s
            on conflict (source_id, norm_name) do nothing
            """,
            (SOURCE_CODE,),
        )
        aliases = cur.rowcount
        cur.execute("drop table _stage_team")
    return teams, aliases


def _stage_season(conn: psycopg.Connection, season: ParsedSeason) -> None:
    db.copy_into_temp(
        conn,
        "_stage_match",
        MATCH_COLUMNS,
        ([m[c] for c in MATCH_COLUMNS] for m in season.matches),
        """
        create temporary table _stage_match (
            row_id           integer,
            competition_code text,
            start_year       integer,
            kickoff_date     date,
            kickoff_utc      timestamptz,
            home_name        text,
            away_name        text,
            home_goals_ft    smallint,
            away_goals_ft    smallint,
            home_goals_ht    smallint,
            away_goals_ht    smallint,
            referee_name     text,
            source_match_id  text,
            stage            text
        )
        """,
    )

    stat_ddl_cols = ",\n            ".join(f"{c} smallint" for c in STAT_COLUMNS)
    db.copy_into_temp(
        conn,
        "_stage_stat",
        STAT_STAGE_COLUMNS,
        ([s.get(c) for c in STAT_STAGE_COLUMNS] for s in season.team_stats),
        f"""
        create temporary table _stage_stat (
            row_id  integer,
            is_home boolean,
            period  text,
            {stat_ddl_cols}
        )
        """,
    )

    db.copy_into_temp(
        conn,
        "_stage_odds",
        ODDS_COLUMNS,
        ([o[c] for c in ODDS_COLUMNS] for o in season.odds),
        """
        create temporary table _stage_odds (
            row_id    integer,
            bookmaker text,
            market    text,
            outcome   text,
            line      numeric(4,2),
            price     numeric(8,3),
            snapshot  text
        )
        """,
    )


def load_season(conn: psycopg.Connection, season: ParsedSeason) -> LoadResult:
    result = LoadResult()
    _stage_season(conn, season)

    with conn.cursor() as cur:
        cur.execute(
            """
            insert into core.referee (canonical_name)
            select distinct on (core.norm_name(referee_name)) referee_name
              from _stage_match
             where referee_name is not null
             order by core.norm_name(referee_name), referee_name
            on conflict (core.norm_name(canonical_name)) do nothing
            """
        )

        # Resolve every staged row to canonical IDs up front. If the row count here
        # differs from the staged count, a team name is unregistered and the load
        # must stop rather than quietly lose matches.
        cur.execute(
            """
            create temporary table _resolved as
            select s.row_id,
                   c.competition_id,
                   se.season_id,
                   hta.team_id as home_team_id,
                   ata.team_id as away_team_id,
                   r.referee_id
              from _stage_match s
              join core.source src on src.code = %s
              join core.competition c on c.code = s.competition_code
              join core.season se on se.competition_id = c.competition_id
                                 and se.start_year = s.start_year
              join core.team_alias hta on hta.source_id = src.source_id
                                      and hta.norm_name = core.norm_name(s.home_name)
              join core.team_alias ata on ata.source_id = src.source_id
                                      and ata.norm_name = core.norm_name(s.away_name)
              left join core.referee r on s.referee_name is not null
                                      and core.norm_name(r.canonical_name)
                                        = core.norm_name(s.referee_name)
            """,
            (SOURCE_CODE,),
        )
        cur.execute("select count(*) from _resolved")
        resolved = cur.fetchone()[0]
        if resolved != len(season.matches):
            cur.execute(
                """
                select s.home_name, s.away_name
                  from _stage_match s
                  left join _resolved r on r.row_id = s.row_id
                 where r.row_id is null
                 limit 20
                """
            )
            unresolved = cur.fetchall()
            raise RuntimeError(
                f"{season.competition_code} {season.start_year}: resolved {resolved} of "
                f"{len(season.matches)} matches. Unregistered names in: {unresolved}"
            )

        cur.execute(
            """
            insert into core.match (
                competition_id, season_id, kickoff_date, kickoff_utc, status,
                home_team_id, away_team_id,
                home_goals_ft, away_goals_ft, home_goals_ht, away_goals_ht, referee_id,
                stage
            )
            select r.competition_id, r.season_id, s.kickoff_date, s.kickoff_utc, 'finished',
                   r.home_team_id, r.away_team_id,
                   s.home_goals_ft, s.away_goals_ft, s.home_goals_ht, s.away_goals_ht,
                   r.referee_id, s.stage
              from _stage_match s
              join _resolved r on r.row_id = s.row_id
            on conflict (season_id, home_team_id, away_team_id, stage) do update
                set kickoff_date  = excluded.kickoff_date,
                    kickoff_utc   = coalesce(excluded.kickoff_utc, core.match.kickoff_utc),
                    status        = excluded.status,
                    home_goals_ft = excluded.home_goals_ft,
                    away_goals_ft = excluded.away_goals_ft,
                    home_goals_ht = excluded.home_goals_ht,
                    away_goals_ht = excluded.away_goals_ht,
                    referee_id    = coalesce(excluded.referee_id, core.match.referee_id)
            """
        )
        result.matches = cur.rowcount

        cur.execute(
            """
            create temporary table _match_map as
            select r.row_id, m.match_id
              from _resolved r
              join _stage_match s on s.row_id = r.row_id
              join core.match m on m.season_id = r.season_id
                               and m.home_team_id = r.home_team_id
                               and m.away_team_id = r.away_team_id
                               and m.stage = s.stage
            """
        )

        cur.execute(
            """
            insert into core.match_source (match_id, source_id, source_match_id, source_url)
            select mm.match_id, src.source_id, s.source_match_id, null
              from _stage_match s
              join _match_map mm on mm.row_id = s.row_id
             cross join core.source src
             where src.code = %s
            on conflict (match_id, source_id) do update
                set source_match_id = excluded.source_match_id,
                    ingested_at = now()
            """,
            (SOURCE_CODE,),
        )

        stat_cols = ", ".join(STAT_COLUMNS)
        stat_select = ", ".join(f"st.{c}" for c in STAT_COLUMNS)
        stat_update = ", ".join(f"{c} = excluded.{c}" for c in STAT_COLUMNS)
        cur.execute(
            f"""
            insert into core.match_team_stat (
                match_id, team_id, period, is_home, opponent_team_id, source_id, {stat_cols}
            )
            select mm.match_id,
                   case when st.is_home then r.home_team_id else r.away_team_id end,
                   st.period,
                   st.is_home,
                   case when st.is_home then r.away_team_id else r.home_team_id end,
                   src.source_id,
                   {stat_select}
              from _stage_stat st
              join _match_map mm on mm.row_id = st.row_id
              join _resolved  r  on r.row_id  = st.row_id
             cross join core.source src
             where src.code = %s
            on conflict (match_id, team_id, period) do update
                set {stat_update}, source_id = excluded.source_id, updated_at = now()
            """,
            (SOURCE_CODE,),
        )
        result.team_stats = cur.rowcount

        cur.execute(
            """
            insert into core.odds (
                match_id, source_id, bookmaker, market, outcome, line, price, snapshot
            )
            select mm.match_id, src.source_id, so.bookmaker, so.market, so.outcome,
                   so.line, so.price, so.snapshot
              from _stage_odds so
              join _match_map mm on mm.row_id = so.row_id
             cross join core.source src
             where src.code = %s
            on conflict (match_id, source_id, bookmaker, market, outcome,
                         coalesce(line, -999), snapshot)
              do update set price = excluded.price
            """,
            (SOURCE_CODE,),
        )
        result.odds = cur.rowcount

        for table in ("_resolved", "_match_map", "_stage_match", "_stage_stat", "_stage_odds"):
            cur.execute(f"drop table if exists {table}")

    return result
