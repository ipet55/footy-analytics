"""Compute Elo ratings from stored results and write them to core.team_rating."""

from __future__ import annotations

from datetime import date, timedelta

import psycopg

from footy import db
from footy.ratings import EloParams, MatchInput, RatingPeriod, compute, with_start

# The value that drives each variant, as an expression over the joined stat rows.
VARIANTS: dict[str, tuple[str, str]] = {
    "elo_goals": ("hs.goals::numeric", "aws.goals::numeric"),
    "elo_xg": ("hs.xg", "aws.xg"),
}


def read_matches(conn: psycopg.Connection, variant: str) -> list[MatchInput]:
    home_expr, away_expr = VARIANTS[variant]
    rows = db.fetch_all(
        conn,
        f"""
        select m.match_id, m.kickoff_date, se.start_year,
               m.home_team_id, m.away_team_id,
               {home_expr} as home_value, {away_expr} as away_value
          from core.match m
          join core.season se on se.season_id = m.season_id
          join core.match_team_stat hs on hs.match_id = m.match_id
                                      and hs.period = 'FT' and hs.is_home
          join core.match_team_stat aws on aws.match_id = m.match_id
                                       and aws.period = 'FT' and not aws.is_home
         where {home_expr} is not null and {away_expr} is not null
         order by m.kickoff_date, m.match_id
        """,
    )
    return [
        MatchInput(
            match_id=r[0],
            kickoff_date=r[1],
            season_start_year=r[2],
            home_team_id=r[3],
            away_team_id=r[4],
            home_value=float(r[5]),
            away_value=float(r[6]),
        )
        for r in rows
    ]


def write_periods(
    conn: psycopg.Connection, variant: str, periods: list[RatingPeriod]
) -> int:
    with conn.cursor() as cur:
        cur.execute("select source_id from core.source where code = %s", (variant,))
        source_id = cur.fetchone()[0]
        cur.execute(
            "delete from core.team_rating where source_id = %s", (source_id,)
        )
        db.copy_into_temp(
            conn,
            "_elo",
            ["team_id", "valid_from", "valid_to", "rating"],
            (
                [p.team_id, p.valid_from, p.valid_to, round(p.rating, 3)]
                for p in periods
            ),
            """
            create temporary table _elo (
                team_id integer, valid_from date, valid_to date, rating numeric(8,3)
            )
            """,
        )
        # Overlapping ranges would make an as-of lookup ambiguous, so collapse any
        # same-day duplicates and keep the last rating for the day.
        cur.execute(
            """
            insert into core.team_rating (team_id, source_id, valid_from, valid_to, rating)
            select team_id, %s, valid_from, max(valid_to), max(rating)
              from _elo
             where valid_to >= valid_from
             group by team_id, valid_from
            on conflict (team_id, source_id, valid_from) do update
                set valid_to = excluded.valid_to, rating = excluded.rating
            """,
            (source_id,),
        )
        written = cur.rowcount
        cur.execute("drop table _elo")
    return written


def build(conn: psycopg.Connection, variant: str, params: EloParams | None = None) -> int:
    matches = read_matches(conn, variant)
    if not matches:
        return 0
    earliest = min(m.kickoff_date for m in matches) - timedelta(days=1)
    periods = [
        with_start(p, earliest)
        for p in compute(matches, params)
        if p.valid_to >= earliest
    ]
    return write_periods(conn, variant, periods)


def check_no_overlaps(conn: psycopg.Connection, variant: str) -> int:
    """Count ranges that overlap another for the same team. Must be zero, or an
    as-of lookup would return more than one rating and silently duplicate rows."""
    return db.fetch_all(
        conn,
        """
        select count(*)
          from core.team_rating a
          join core.team_rating b
            on b.team_id = a.team_id and b.source_id = a.source_id
           and b.valid_from > a.valid_from and b.valid_from <= a.valid_to
          join core.source s on s.source_id = a.source_id and s.code = %s
        """,
        (variant,),
    )[0][0]


def latest(conn: psycopg.Connection, variant: str, limit: int = 10) -> list[tuple]:
    return db.fetch_all(
        conn,
        """
        select t.canonical_name, t.country, tr.rating
          from core.team_rating tr
          join core.source s on s.source_id = tr.source_id and s.code = %s
          join core.team t on t.team_id = tr.team_id
         where tr.valid_to = %s
         order by tr.rating desc
         limit %s
        """,
        (variant, date(9999, 12, 31), limit),
    )
