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
from footy.sources.fbref import (
    SOURCE_CODE,
    STAT_MAP,
    Appearance,
    Fixture,
    ScheduledMatch,
)
from footy.teams import (
    COMPETITION_COUNTRY,
    FBREF_ALIASES,
    FBREF_NOT_IN_LEAGUE,
    FBREF_PROMOTED,
)

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

    Clubs declared as not belonging to the league are dropped first. They are
    play-off opponents from the division below, so they have no team of ours to
    resolve to and no match of ours to appear in.
    """
    names = names - FBREF_NOT_IN_LEAGUE
    if not names:
        return 0, []
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


def seed_promoted(
    conn: psycopg.Connection, names: set[str], country: str
) -> list[str]:
    """Create the declared promoted clubs among these names, and alias them.

    Returns the canonical names created. Only names in `FBREF_PROMOTED` are
    touched, so an unrecognised spelling still stops the load instead of becoming
    a new club.
    """
    wanted = {n: FBREF_PROMOTED[n] for n in names if n in FBREF_PROMOTED}
    if not wanted:
        return []
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into core.team (canonical_name, country) values (%s, %s)
            on conflict (core.norm_name(canonical_name)) do nothing
            """,
            sorted((canonical_name, country) for canonical_name in wanted.values()),
        )
        cur.executemany(
            """
            insert into core.team_alias (team_id, source_id, alias_name)
            select t.team_id, s.source_id, %s
              from core.team t cross join core.source s
             where core.norm_name(t.canonical_name) = core.norm_name(%s)
               and t.country = %s and s.code = %s
            on conflict (source_id, norm_name) do nothing
            """,
            sorted(
                (raw, canonical_name, country, SOURCE_CODE)
                for raw, canonical_name in wanted.items()
            ),
        )
    conn.commit()
    return sorted(set(wanted.values()))


def ensure_season(
    conn: psycopg.Connection, competition_code: str, start_year: int
) -> int:
    """The season row for a competition, created if this is its first sighting.

    Seasons up to 2025-26 arrived with their results, because a completed season
    is loaded all at once. A fixture list arrives before anything has been played,
    so it has to make its own.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into core.season (competition_id, start_year, end_year, label)
            select c.competition_id, %s, %s, %s
              from core.competition c where c.code = %s
            on conflict (competition_id, start_year) do nothing
            """,
            (start_year, start_year + 1,
             f"{start_year}/{(start_year + 1) % 100:02d}", competition_code),
        )
        # Only one season of a competition is the current one, and it is the
        # latest we hold fixtures for.
        cur.execute(
            """
            update core.season s
               set is_current = (s.start_year = %s)
              from core.competition c
             where c.competition_id = s.competition_id
               and c.code = %s
               and s.is_current <> (s.start_year = %s)
            """,
            (start_year, competition_code, start_year),
        )
        cur.execute(
            """
            select s.season_id from core.season s
              join core.competition c using (competition_id)
             where c.code = %s and s.start_year = %s
            """,
            (competition_code, start_year),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"unknown competition {competition_code}")
    conn.commit()
    return row[0]


def store_fixtures(
    conn: psycopg.Connection,
    competition_code: str,
    start_year: int,
    fixtures: list[Fixture],
) -> tuple[int, int, list[str]]:
    """Write a season's calendar as scheduled matches.

    Returns (inserted, rescheduled, unresolved names). A fixture already in the
    table is updated rather than duplicated, so this is safe to re-run when the
    calendar moves — which it does constantly, for television.

    Results are never touched. A match that has since been played keeps its score
    and its finished status even though the fixture list still lists it, because
    the calendar is authoritative about *when* and nothing else.
    """
    if not fixtures:
        return 0, 0, []
    ensure_season(conn, competition_code, start_year)

    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_fb_fixture",
            ["kickoff_date", "home_name", "away_name", "matchday", "venue"],
            (
                [f.kickoff_date, f.home_name, f.away_name, f.matchday, f.venue]
                for f in fixtures
            ),
            """
            create temporary table _fb_fixture (
                kickoff_date date, home_name text, away_name text,
                matchday smallint, venue text
            )
            """,
        )
        cur.execute(
            """
            create temporary table _fb_resolved as
            select f.*, c.competition_id, se.season_id,
                   hta.team_id as home_team_id, ata.team_id as away_team_id
              from _fb_fixture f
              join core.source src on src.code = %s
              join core.competition c on c.code = %s
              join core.season se on se.competition_id = c.competition_id
                                 and se.start_year = %s
              join core.team_alias hta on hta.source_id = src.source_id
                                      and hta.norm_name = core.norm_name(f.home_name)
              join core.team_alias ata on ata.source_id = src.source_id
                                      and ata.norm_name = core.norm_name(f.away_name)
            """,
            (SOURCE_CODE, competition_code, start_year),
        )
        cur.execute("select count(*) from _fb_resolved")
        resolved = cur.fetchone()[0]
        if resolved != len(fixtures):
            cur.execute(
                """
                select distinct name from (
                    select home_name as name from _fb_fixture
                    union all select away_name from _fb_fixture
                ) n
                 cross join core.source src
                 where src.code = %s
                   and not exists (
                        select 1 from core.team_alias a
                         where a.source_id = src.source_id
                           and a.norm_name = core.norm_name(n.name))
                 order by name
                """,
                (SOURCE_CODE,),
            )
            unresolved = [r[0] for r in cur.fetchall()]
            for table in ("_fb_fixture", "_fb_resolved"):
                cur.execute(f"drop table if exists {table}")
            conn.rollback()
            return 0, 0, unresolved

        cur.execute(
            """
            insert into core.match (
                competition_id, season_id, kickoff_date, status,
                home_team_id, away_team_id, matchday, venue_name
            )
            select competition_id, season_id, kickoff_date, 'scheduled',
                   home_team_id, away_team_id, matchday, venue
              from _fb_resolved
            on conflict (season_id, home_team_id, away_team_id) do update
                set kickoff_date = excluded.kickoff_date,
                    matchday     = coalesce(excluded.matchday, core.match.matchday),
                    venue_name   = coalesce(excluded.venue_name, core.match.venue_name),
                    updated_at   = now()
              where core.match.kickoff_date <> excluded.kickoff_date
                 or core.match.matchday is distinct from excluded.matchday
            returning (core.match.created_at = core.match.updated_at) as is_new
            """
        )
        touched = cur.fetchall()
        for table in ("_fb_fixture", "_fb_resolved"):
            cur.execute(f"drop table if exists {table}")
    conn.commit()
    inserted = sum(1 for (is_new,) in touched if is_new)
    return inserted, len(touched) - inserted, []


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


def store_referees(
    conn: psycopg.Connection,
    linked: dict[str, int],
    scheduled: list[ScheduledMatch],
    country: str,
) -> tuple[int, int]:
    """Fill core.match.referee_id from the FBref schedule.

    Only matches with no referee yet are touched. England already has referees
    from football-data.co.uk under a different convention — "A Taylor" there,
    "Anthony Taylor" here — and overwriting them would orphan the ids the count
    models already use while creating a duplicate for every official.

    Returns (referees inserted, matches updated).
    """
    named = [
        (linked[m.game_id], m.referee)
        for m in scheduled
        if m.referee and m.game_id in linked
    ]
    if not named:
        return 0, 0

    with conn.cursor() as cur:
        cur.execute("drop table if exists _fb_ref")
        cur.execute("create temporary table _fb_ref (match_id bigint, name text)")
        cur.executemany("insert into _fb_ref values (%s, %s)", named)

        cur.execute(
            """
            insert into core.referee (canonical_name, country)
            select distinct on (core.norm_name(r.name)) r.name, %s
              from _fb_ref r
             where not exists (
                   select 1 from core.referee x
                    where core.norm_name(x.canonical_name) = core.norm_name(r.name))
             order by core.norm_name(r.name), r.name
            on conflict do nothing
            """,
            (country,),
        )
        inserted = cur.rowcount

        cur.execute(
            """
            update core.match m
               set referee_id = ref.referee_id
              from _fb_ref r
              join core.referee ref
                on core.norm_name(ref.canonical_name) = core.norm_name(r.name)
             where m.match_id = r.match_id
               and m.referee_id is null
            """
        )
        updated = cur.rowcount
        cur.execute("drop table _fb_ref")
    return inserted, updated


def close_run(
    run_id: int, status: str, read: int, written: int, error: str | None = None
) -> None:
    """Close out an ingest run on its own connection, swallowing any failure.

    Bookkeeping must never be what surfaces instead of the real problem. The
    first full run died of a dropped connection and then reported the exception
    raised while trying to record that it had died.
    """
    try:
        with db.connect() as conn:
            db.finish_run(conn, run_id, status, read, written, error)
            conn.commit()
    except Exception:
        pass


def write_batch(
    country: str,
    assignments: dict[str, int],
    sheets: dict[str, list[Appearance]],
    dates: dict[str, date],
    attempts: int = 4,
) -> tuple[int, list[str]]:
    """Store a batch of sheets on a connection opened just for this write.

    A season is an hour of scraping, and a connection held open across it will
    be closed under us by the pooler — which is how the first full run died,
    two thirds of the way through. Scraping now happens with no connection held
    and each batch reconnects, so a dropped connection costs one retry instead
    of the rest of the season.

    Returns the appearances stored and any team names that would not resolve.
    """
    import time

    for attempt in range(attempts):
        try:
            with db.connect() as conn:
                names = {a.team_name for apps in sheets.values() for a in apps}
                _, unresolved = register_aliases(conn, names, country)
                if unresolved:
                    return 0, unresolved
                stored = 0
                for game_id, appearances in sheets.items():
                    match_id = assignments.get(game_id)
                    if match_id is None:
                        continue
                    stored += store(
                        conn, match_id, appearances, country, dates[game_id]
                    )
                conn.commit()
                return stored, []
        except psycopg.OperationalError:
            if attempt == attempts - 1:
                raise
            # The scrape is the expensive part and it is already done and cached,
            # so waiting here is cheap next to losing the batch.
            time.sleep(5 * (attempt + 1))
    return 0, []
