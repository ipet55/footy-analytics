"""Load Understat xG into the match rows that already exist.

This adds no rows to core.match_team_stat — it fills the xg, npxg, ppda,
deep_completions and expected_points columns on rows created from
football-data.co.uk, matched on the same natural key.

Because both sources are linked through core.team_alias rather than by string
comparison, a spelling Understat uses that we have not registered surfaces in
core.unresolved_alias instead of silently skipping a match.
"""

from __future__ import annotations

import psycopg

from footy import db
from footy.sources.understat import SOURCE_CODE, STAT_MAP, UnderstatSeason
from footy.teams import COMPETITION_COUNTRY, UNDERSTAT_ALIASES

STAT_COLUMNS = list(STAT_MAP.values())

# Occasional genuine disagreements (results overturned after the fact) are recorded
# in core.result_dispute and tolerated. Anything beyond a couple per 380-match season
# is a mis-linked join, not a data difference, so the load stops.
MAX_DISPUTES_PER_SEASON = 3


def register_aliases(
    conn: psycopg.Connection, seasons: list[UnderstatSeason]
) -> tuple[int, list[tuple[str, str]]]:
    """Map every Understat spelling onto a canonical team_id.

    Three rules, in order of confidence: an exact canonical-name match, a spelling
    football-data.co.uk already registered for a club in the same country, and
    finally a small hand-written table for names neither rule catches.
    """
    names: dict[str, str] = {}
    for season in seasons:
        country = COMPETITION_COUNTRY[season.competition_code]
        for match in season.matches:
            names.setdefault(match["home_name"], country)
            names.setdefault(match["away_name"], country)

    with conn.cursor() as cur:
        cur.execute("drop table if exists _un_name")
        cur.execute("create temporary table _un_name (name text, country text, hand_target text)")
        cur.executemany(
            "insert into _un_name values (%s, %s, %s)",
            [(n, c, UNDERSTAT_ALIASES.get(n)) for n, c in sorted(names.items())],
        )

        cur.execute(
            """
            insert into core.team_alias (team_id, source_id, source_team_id, alias_name)
            select t.team_id, s.source_id, null, u.name
              from _un_name u
             cross join core.source s
              join lateral (
                    select t1.team_id from core.team t1
                     where core.norm_name(t1.canonical_name) = core.norm_name(u.name)
                    union all
                    select t2.team_id
                      from core.team_alias a
                      join core.source fs on fs.source_id = a.source_id
                                         and fs.code = 'football_data_uk'
                      join core.team t2 on t2.team_id = a.team_id and t2.country = u.country
                     where a.norm_name = core.norm_name(u.name)
                    union all
                    select t3.team_id from core.team t3
                     where u.hand_target is not null
                       and core.norm_name(t3.canonical_name) = core.norm_name(u.hand_target)
                    limit 1
              ) t on true
             where s.code = %s
            -- The name-uniqueness index is partial, covering only sources with no
            -- id of their own, so the predicate has to be repeated for Postgres to
            -- match it. This source resolves by name, so its rows are inside it.
            on conflict (source_id, norm_name) where source_team_id is null
                do nothing
            """,
            (SOURCE_CODE,),
        )
        added = cur.rowcount

        # Anything still unmapped goes to the review queue rather than being dropped.
        cur.execute(
            """
            insert into core.unresolved_alias (source_id, entity_type, raw_value, context)
            select s.source_id, 'team', u.name, jsonb_build_object('country', u.country)
              from _un_name u cross join core.source s
             where s.code = %s
               and not exists (select 1 from core.team_alias a
                                where a.source_id = s.source_id
                                  and a.norm_name = core.norm_name(u.name))
            on conflict (source_id, entity_type, raw_value) do update
                set occurrences = core.unresolved_alias.occurrences + 1, last_seen_at = now()
            """,
            (SOURCE_CODE,),
        )
        cur.execute(
            """
            select u.name, u.country from _un_name u
             cross join core.source s
             where s.code = %s
               and not exists (select 1 from core.team_alias a
                                where a.source_id = s.source_id
                                  and a.norm_name = core.norm_name(u.name))
             order by u.country, u.name
            """,
            (SOURCE_CODE,),
        )
        unresolved = cur.fetchall()
        cur.execute("drop table _un_name")

    # Commit before reporting failure, otherwise the rollback would discard the
    # very review-queue rows that explain what went wrong.
    conn.commit()
    return added, unresolved


def load_season(conn: psycopg.Connection, season: UnderstatSeason) -> tuple[int, int, int]:
    """Returns (stat rows updated, date-drift count, score-dispute count)."""
    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_us_match",
            ["row_id", "competition_code", "start_year", "kickoff_date",
             "home_name", "away_name", "home_goals", "away_goals",
             "source_match_id", "source_url"],
            (
                [m[k] for k in ("row_id", "competition_code", "start_year", "kickoff_date",
                                "home_name", "away_name", "home_goals", "away_goals",
                                "source_match_id", "source_url")]
                for m in season.matches
            ),
            """
            create temporary table _us_match (
                row_id integer, competition_code text, start_year integer,
                kickoff_date date, home_name text, away_name text,
                home_goals smallint, away_goals smallint,
                source_match_id text, source_url text
            )
            """,
        )
        stat_ddl = ", ".join(f"{c} numeric" for c in STAT_COLUMNS)
        db.copy_into_temp(
            conn,
            "_us_stat",
            ["row_id", "is_home", "period", *STAT_COLUMNS],
            (
                [s.get(k) for k in ("row_id", "is_home", "period", *STAT_COLUMNS)]
                for s in season.team_stats
            ),
            f"create temporary table _us_stat (row_id integer, is_home boolean, period text, {stat_ddl})",
        )

        cur.execute(
            """
            create temporary table _us_map as
            select u.row_id, m.match_id, m.kickoff_date as our_date, u.kickoff_date as their_date,
                   hta.team_id as home_team_id, ata.team_id as away_team_id,
                   m.home_goals_ft, m.away_goals_ft, u.home_goals, u.away_goals
              from _us_match u
              join core.source src on src.code = %s
              join core.competition c on c.code = u.competition_code
              join core.season se on se.competition_id = c.competition_id
                                 and se.start_year = u.start_year
              join core.team_alias hta on hta.source_id = src.source_id
                                      and hta.norm_name = core.norm_name(u.home_name)
              join core.team_alias ata on ata.source_id = src.source_id
                                      and ata.norm_name = core.norm_name(u.away_name)
              join core.match m on m.season_id = se.season_id
                               and m.home_team_id = hta.team_id
                               and m.away_team_id = ata.team_id
            """,
            (SOURCE_CODE,),
        )
        cur.execute("select count(*) from _us_map")
        mapped = cur.fetchone()[0]
        if mapped != len(season.matches):
            raise RuntimeError(
                f"{season.competition_code} {season.start_year}: matched {mapped} of "
                f"{len(season.matches)} Understat fixtures to core.match"
            )

        # Scores should agree. A handful of genuine disagreements exist (a result
        # overturned after the match is recorded as awarded by one source and as
        # played by the other), but a systematic mismatch means fixtures got linked
        # to the wrong rows, which would attach one match's xG to another's result.
        cur.execute(
            """
            insert into core.result_dispute
                (match_id, source_id, source_home_goals, source_away_goals, note)
            select mm.match_id, src.source_id, mm.home_goals, mm.away_goals,
                   'Understat reports the match as played; core.match holds the other source''s score.'
              from _us_map mm
             cross join core.source src
             where src.code = %s
               and (mm.home_goals_ft <> mm.home_goals or mm.away_goals_ft <> mm.away_goals)
            on conflict (match_id, source_id) do update
                set source_home_goals = excluded.source_home_goals,
                    source_away_goals = excluded.source_away_goals
            """,
            (SOURCE_CODE,),
        )
        disputes = cur.rowcount
        if disputes > MAX_DISPUTES_PER_SEASON:
            raise RuntimeError(
                f"{season.competition_code} {season.start_year}: {disputes} fixtures linked "
                f"but scores disagree, above the tolerance of {MAX_DISPUTES_PER_SEASON}. "
                "This indicates a bad join rather than genuine source disagreement."
            )

        cur.execute("select count(*) from _us_map where abs(our_date - their_date) > 2")
        date_drift = cur.fetchone()[0]

        assignments = ", ".join(f"{c} = s.{c}" for c in STAT_COLUMNS)
        cur.execute(
            f"""
            update core.match_team_stat mts
               set {assignments}, updated_at = now()
              from _us_stat s
              join _us_map mm on mm.row_id = s.row_id
             where mts.match_id = mm.match_id
               and mts.period = s.period
               and mts.team_id = case when s.is_home then mm.home_team_id else mm.away_team_id end
            """
        )
        updated = cur.rowcount

        cur.execute(
            """
            insert into core.match_source (match_id, source_id, source_match_id, source_url)
            select mm.match_id, src.source_id, u.source_match_id, u.source_url
              from _us_match u
              join _us_map mm on mm.row_id = u.row_id
             cross join core.source src where src.code = %s
            on conflict (match_id, source_id) do update
                set source_match_id = excluded.source_match_id,
                    source_url = excluded.source_url, ingested_at = now()
            """,
            (SOURCE_CODE,),
        )

        for table in ("_us_map", "_us_match", "_us_stat"):
            cur.execute(f"drop table if exists {table}")
    return updated, date_drift, disputes
