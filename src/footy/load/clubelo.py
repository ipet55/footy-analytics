"""Load ClubElo rating histories into core.team_rating."""

from __future__ import annotations

from datetime import date

import psycopg

from footy import db
from footy.sources import clubelo as ce
from footy.teams import CLUBELO_ALIASES


def register_aliases(
    conn: psycopg.Connection, clubs: dict[str, str]
) -> tuple[int, list[tuple[str, str]]]:
    """Map ClubElo club names onto canonical team_ids.

    Same three rules as the other sources: canonical name, a spelling another
    source already registered for a club in the same country, then a hand table.
    """
    with conn.cursor() as cur:
        cur.execute("drop table if exists _ce_name")
        cur.execute("create temporary table _ce_name (name text, country text, hand_target text)")
        cur.executemany(
            "insert into _ce_name values (%s, %s, %s)",
            [(n, c, CLUBELO_ALIASES.get(n)) for n, c in sorted(clubs.items())],
        )

        cur.execute(
            """
            insert into core.team_alias (team_id, source_id, alias_name)
            select t.team_id, s.source_id, u.name
              from _ce_name u
             cross join core.source s
              join lateral (
                    select t1.team_id from core.team t1
                     where t1.country = u.country
                       and core.norm_name(t1.canonical_name) = core.norm_name(u.name)
                    union all
                    select t2.team_id
                      from core.team_alias a
                      join core.team t2 on t2.team_id = a.team_id and t2.country = u.country
                     where a.norm_name = core.norm_name(u.name)
                    union all
                    select t3.team_id from core.team t3
                     where u.hand_target is not null
                       and core.norm_name(t3.canonical_name) = core.norm_name(u.hand_target)
                    limit 1
              ) t on true
             where s.code = %s
            on conflict (source_id, norm_name) do nothing
            """,
            (ce.SOURCE_CODE,),
        )
        added = cur.rowcount

        cur.execute(
            """
            insert into core.unresolved_alias (source_id, entity_type, raw_value, context)
            select s.source_id, 'team', u.name, jsonb_build_object('country', u.country)
              from _ce_name u cross join core.source s
             where s.code = %s
               and not exists (select 1 from core.team_alias a
                                where a.source_id = s.source_id
                                  and a.norm_name = core.norm_name(u.name))
            on conflict (source_id, entity_type, raw_value) do update
                set occurrences = core.unresolved_alias.occurrences + 1, last_seen_at = now()
            """,
            (ce.SOURCE_CODE,),
        )
        cur.execute(
            """
            select u.name, u.country from _ce_name u cross join core.source s
             where s.code = %s
               and not exists (select 1 from core.team_alias a
                                where a.source_id = s.source_id
                                  and a.norm_name = core.norm_name(u.name))
             order by u.country, u.name
            """,
            (ce.SOURCE_CODE,),
        )
        unresolved = cur.fetchall()
        cur.execute("drop table _ce_name")
    conn.commit()
    return added, unresolved


def load_ratings(conn: psycopg.Connection, histories: dict[str, list[ce.Rating]]) -> int:
    rows = [
        (club, r.valid_from, r.valid_to, r.rating, r.rank, r.level)
        for club, ratings in histories.items()
        for r in ratings
    ]
    if not rows:
        return 0

    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_ce_rating",
            ["club", "valid_from", "valid_to", "rating", "rank", "level"],
            rows,
            """
            create temporary table _ce_rating (
                club text, valid_from date, valid_to date,
                rating numeric(8,3), rank integer, level smallint
            )
            """,
        )
        cur.execute(
            """
            insert into core.team_rating (team_id, source_id, valid_from, valid_to, rating, rank, level)
            select a.team_id, s.source_id, r.valid_from, max(r.valid_to),
                   max(r.rating), max(r.rank), max(r.level)
              from _ce_rating r
              join core.source s on s.code = %s
              join core.team_alias a on a.source_id = s.source_id
                                    and a.norm_name = core.norm_name(r.club)
             group by a.team_id, s.source_id, r.valid_from
            on conflict (team_id, source_id, valid_from) do update
                set valid_to = excluded.valid_to,
                    rating   = excluded.rating,
                    rank     = excluded.rank,
                    level    = excluded.level
            """,
            (ce.SOURCE_CODE,),
        )
        written = cur.rowcount
        cur.execute("drop table _ce_rating")
    return written


def discover_clubs(sample_years: range) -> dict[str, str]:
    """Club names as at November of each season, so relegated sides also appear."""
    import concurrent.futures as cf

    session = ce._session()
    clubs: dict[str, str] = {}
    dates = [date(y, 11, 1) for y in sample_years]
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for rows in pool.map(lambda d: ce.clubs_on(d, session), dates):
            for r in rows:
                if r.country in ce.COUNTRIES and (r.level or 9) <= 1:
                    clubs[r.club] = ce.COUNTRIES[r.country]
    return clubs
