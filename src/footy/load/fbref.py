"""Load FBref match sheets into core.player and core.appearance.

Resumable by design, because a season is seventy minutes of polite scraping and
something will interrupt it. core.lineup_coverage records what has landed, and a
re-run picks up from there; soccerdata's HTML cache means re-reading a match
already scraped costs nothing.

Team names are resolved through core.team_alias, like every other source here,
so an unregistered spelling stops the load and surfaces in core.unresolved_alias
rather than silently dropping matches. FBref is inconsistent with itself — the
schedule says "Manchester Utd" where the team sheet says "Manchester United" —
so both spellings are registered.

Players are matched on normalised name only. That is weaker than the team path
and it is the known soft spot: two players sharing a normalised name inside one
league would collide. core.player_source exists so provider ids can replace this
without a re-scrape.
"""

from __future__ import annotations

from datetime import date

import psycopg

from footy import db
from footy.sources.fbref import SOURCE_CODE, STAT_MAP, Appearance, ScheduledMatch
from footy.teams import COMPETITION_COUNTRY, FBREF_ALIASES

STAT_COLUMNS = list(STAT_MAP.values())

# A full sheet is two squads of 18-20. Below this something was missing from the
# page, and the row is flagged rather than quietly trusted by the feature layer.
MIN_COMPLETE_SHEET = 28


def register_aliases(
    conn: psycopg.Connection, names: set[str], country: str
) -> tuple[int, list[str]]:
    """Map FBref's spellings onto canonical team ids.

    Three rules, in order of confidence: an exact canonical-name match, a
    spelling another source has already registered for a club in the same
    country, and a small hand-written table for the rest.
    """
    with conn.cursor() as cur:
        cur.execute("drop table if exists _fb_name")
        cur.execute(
            "create temporary table _fb_name (name text, country text, hand_target text)"
        )
        cur.executemany(
            "insert into _fb_name values (%s, %s, %s)",
            sorted((n, country, FBREF_ALIASES.get(n)) for n in names),
        )
        cur.execute(
            """
            insert into core.team_alias (team_id, source_id, source_team_id, alias_name)
            select t.team_id, s.source_id, null, u.name
              from _fb_name u
             cross join core.source s
              join lateral (
                    select t1.team_id from core.team t1
                     where t1.country = u.country
                       and core.norm_name(t1.canonical_name) = core.norm_name(u.name)
                    union all
                    select t2.team_id
                      from core.team_alias a
                      join core.team t2 on t2.team_id = a.team_id
                                       and t2.country = u.country
                     where a.norm_name = core.norm_name(u.name)
                    union all
                    select t3.team_id from core.team t3
                     where u.hand_target is not null
                       and t3.country = u.country
                       and core.norm_name(t3.canonical_name) = core.norm_name(u.hand_target)
                    limit 1
              ) t on true
             where s.code = %s
            on conflict (source_id, norm_name) do nothing
            """,
            (SOURCE_CODE,),
        )
        added = cur.rowcount

        cur.execute(
            """
            insert into core.unresolved_alias (source_id, entity_type, raw_value, context)
            select s.source_id, 'team', u.name, jsonb_build_object('country', u.country)
              from _fb_name u cross join core.source s
             where s.code = %s
               and not exists (select 1 from core.team_alias a
                                where a.source_id = s.source_id
                                  and a.norm_name = core.norm_name(u.name))
            on conflict (source_id, entity_type, raw_value) do update
                set occurrences = core.unresolved_alias.occurrences + 1,
                    last_seen_at = now()
            """,
            (SOURCE_CODE,),
        )
        cur.execute(
            """
            select u.name from _fb_name u cross join core.source s
             where s.code = %s
               and not exists (select 1 from core.team_alias a
                                where a.source_id = s.source_id
                                  and a.norm_name = core.norm_name(u.name))
             order by u.name
            """,
            (SOURCE_CODE,),
        )
        unresolved = [r[0] for r in cur.fetchall()]
        cur.execute("drop table _fb_name")

    # Commit before reporting failure, or the rollback discards the review-queue
    # rows that explain what went wrong.
    conn.commit()
    return added, unresolved


def link_matches(
    conn: psycopg.Connection,
    competition_code: str,
    start_year: int,
    scheduled: list[ScheduledMatch],
) -> tuple[dict[str, int], list[ScheduledMatch]]:
    """Map FBref game ids onto our match ids.

    Joined on the two team ids plus a kickoff date within a day, because sources
    disagree about which side of midnight a late kickoff falls on.
    """
    with conn.cursor() as cur:
        cur.execute("drop table if exists _fb_sched")
        cur.execute(
            "create temporary table _fb_sched "
            "(game_id text, kickoff_date date, home_name text, away_name text)"
        )
        cur.executemany(
            "insert into _fb_sched values (%s, %s, %s, %s)",
            [(m.game_id, m.kickoff_date, m.home_name, m.away_name) for m in scheduled],
        )
        cur.execute(
            """
            select f.game_id, m.match_id
              from _fb_sched f
              join core.source s on s.code = %s
              join core.team_alias hta on hta.source_id = s.source_id
                                      and hta.norm_name = core.norm_name(f.home_name)
              join core.team_alias ata on ata.source_id = s.source_id
                                      and ata.norm_name = core.norm_name(f.away_name)
              join core.competition c on c.code = %s
              join core.season se on se.competition_id = c.competition_id
                                 and se.start_year = %s
              join core.match m on m.season_id = se.season_id
                               and m.home_team_id = hta.team_id
                               and m.away_team_id = ata.team_id
                               and abs(m.kickoff_date - f.kickoff_date) <= 1
            """,
            (SOURCE_CODE, competition_code, start_year),
        )
        linked = {gid: mid for gid, mid in cur.fetchall()}
        cur.execute("drop table _fb_sched")
    return linked, [m for m in scheduled if m.game_id not in linked]


def pending(
    conn: psycopg.Connection, linked: dict[str, int]
) -> dict[str, int]:
    """Drop the matches already scraped, so a re-run resumes."""
    if not linked:
        return {}
    done = {
        r[0]
        for r in db.fetch_all(
            conn,
            "select match_id from core.lineup_coverage where match_id = any(%s)",
            (list(linked.values()),),
        )
    }
    return {gid: mid for gid, mid in linked.items() if mid not in done}


def store(
    conn: psycopg.Connection,
    match_id: int,
    appearances: list[Appearance],
    country: str,
    seen_on: date,
) -> int:
    """Write one match's sheet. Returns the number of appearances stored."""
    if not appearances:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into core.player (canonical_name, first_seen_on, last_seen_on)
            values (%s, %s, %s)
            on conflict (norm_name) do update
                set first_seen_on = least(core.player.first_seen_on, excluded.first_seen_on),
                    last_seen_on  = greatest(core.player.last_seen_on, excluded.last_seen_on)
            """,
            [(a.player_name, seen_on, seen_on) for a in appearances],
        )

        cur.execute("drop table if exists _fb_app")
        cur.execute(
            f"""
            create temporary table _fb_app (
              player_name text, team_name text, is_starter boolean,
              position text, shirt_number smallint, minutes smallint,
              {', '.join(f'{c} smallint' for c in STAT_COLUMNS)}
            )
            """
        )
        cur.executemany(
            f"insert into _fb_app values ({', '.join(['%s'] * (6 + len(STAT_COLUMNS)))})",
            [
                (
                    a.player_name, a.team_name, a.is_starter, a.position,
                    a.shirt_number, min(a.minutes, 130),
                    *[a.stats.get(c) for c in STAT_COLUMNS],
                )
                for a in appearances
            ],
        )
        cur.execute(
            f"""
            insert into core.appearance (
              match_id, player_id, team_id, is_starter, position, shirt_number,
              minutes, {', '.join(STAT_COLUMNS)}
            )
            select %s, p.player_id, ta.team_id, a.is_starter, a.position,
                   a.shirt_number, a.minutes, {', '.join('a.' + c for c in STAT_COLUMNS)}
              from _fb_app a
              join core.player p on p.norm_name = core.norm_name(a.player_name)
              join core.source s on s.code = %s
              join core.team_alias ta on ta.source_id = s.source_id
                                     and ta.norm_name = core.norm_name(a.team_name)
              join core.team t on t.team_id = ta.team_id and t.country = %s
            on conflict (match_id, player_id) do nothing
            """,
            (match_id, SOURCE_CODE, country),
        )
        stored = cur.rowcount
        cur.execute("drop table _fb_app")

        cur.execute(
            """
            insert into core.lineup_coverage (match_id, source_id, n_players, is_complete)
            select %s, s.source_id, %s, %s from core.source s where s.code = %s
            on conflict (match_id) do update
                set n_players = excluded.n_players,
                    is_complete = excluded.is_complete,
                    scraped_at = now()
            """,
            (match_id, stored, stored >= MIN_COMPLETE_SHEET, SOURCE_CODE),
        )
    return stored


def country_for(competition_code: str) -> str:
    return COMPETITION_COUNTRY[competition_code]
