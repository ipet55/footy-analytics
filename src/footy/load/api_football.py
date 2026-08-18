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
    POSTPONED,
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


def mark_postponed(conn: psycopg.Connection, fixtures: list[Fixture]) -> int:
    """Record that a called-off match was called off.

    Nothing wrote 'postponed' before, so a postponed fixture kept its original
    date and the status 'scheduled' — indistinguishable, to any check asking
    whether results arrive on time, from a result that failed to load. Braga
    against Gil Vicente was called off on 16 August 2026 and the freshness check
    reported a missing Portuguese result on every run until this existed.

    Only ever moves a match away from 'scheduled'. A rearranged fixture that has
    since been played arrives through the normal path with a score, and this must
    not undo that.
    """
    called_off = [f.fixture_id for f in fixtures if f.status in POSTPONED]
    if not called_off:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            update core.match m
               set status = 'postponed'
              from core.match_source ms
              join core.source s on s.source_id = ms.source_id and s.code = %s
             where ms.match_id = m.match_id
               and ms.source_match_id = any(%s)
               and m.status = 'scheduled'
               and m.home_goals_ft is null
            """,
            (SOURCE_CODE, [str(fid) for fid in called_off]),
        )
        return cur.rowcount


def alias_teams(
    conn: psycopg.Connection,
    competition_code: str,
    start_year: int,
    fixtures: list[Fixture],
    threshold: float = 0.72,
) -> tuple[list[tuple[str, str, float]], list[str]]:
    """Match this source's club names to clubs already in the competition.

    Fuzzy, and deliberately so. The provider says Bournemouth where we say AFC
    Bournemouth, Alaves where we say Deportivo Alavés, Le Havre where we say Le
    Havre AC. Exact normalised matching linked 56 of 380 Spanish fixtures and
    invented six clubs to hold the rest.

    Fuzziness is safe here only because of the constraint: candidates are the clubs
    that already played in this competition and season, about twenty of them, not
    every club in the database. Matching 'Bournemouth' against twenty English
    clubs is a different problem from matching it against four thousand.

    Returns (matched, unresolved) for reporting. Nothing is created — a club this
    cannot place is left for a human, because inventing one is what produced two
    merge migrations already.
    """
    names: dict[int, str] = {}
    for fixture in fixtures:
        names.setdefault(fixture.home_id, fixture.home_name)
        names.setdefault(fixture.away_id, fixture.away_name)
    if not names:
        return [], []

    existing = db.fetch_all(
        conn,
        """
        select distinct t.team_id, t.canonical_name
          from core.match m
          join core.competition c on c.competition_id = m.competition_id
          join core.season se on se.season_id = m.season_id
          join core.team t on t.team_id in (m.home_team_id, m.away_team_id)
         where c.code = %s and se.start_year = %s
        """,
        (competition_code, start_year),
    )
    already = {
        r[0] for r in db.fetch_all(
            conn,
            """
            select ta.source_team_id from core.team_alias ta
              join core.source s on s.source_id = ta.source_id
                                and s.code = %s
             where ta.source_team_id is not null
            """,
            (SOURCE_CODE,),
        )
    }

    matched: list[tuple[str, str, float]] = []
    unresolved: list[str] = []
    rows: list[list] = []
    for source_id, source_name in sorted(names.items()):
        if str(source_id) in already:
            continue
        best, score = None, 0.0
        for team_id, canonical in existing:
            ratio = _similarity(source_name, canonical)
            if ratio > score:
                best, score = (team_id, canonical), ratio
        if best and score >= threshold:
            matched.append((source_name, best[1], score))
            rows.append([best[0], str(source_id), source_name])
        else:
            unresolved.append(
                f"{source_name}"
                + (f" (closest {best[1]}, {score:.2f})" if best else "")
            )

    if rows:
        with conn.cursor() as cur:
            db.copy_into_temp(
                conn,
                "_af_alias",
                ["team_id", "source_team_id", "alias_name"],
                rows,
                "create temporary table _af_alias "
                "(team_id integer, source_team_id text, alias_name text)",
            )
            cur.execute(
                """
                insert into core.team_alias (team_id, source_id, source_team_id, alias_name)
                select a.team_id, src.source_id, a.source_team_id, a.alias_name
                  from _af_alias a
                  join core.source src on src.code = %s
                 where not exists (
                        select 1 from core.team_alias x
                         where x.source_id = src.source_id
                           and x.source_team_id = a.source_team_id)
                """,
                (SOURCE_CODE,),
            )
            cur.execute("drop table _af_alias")
    return matched, unresolved


def _similarity(a: str, b: str) -> float:
    """How alike two club names are, ignoring the decoration.

    Both the character ratio and the token overlap, taking whichever is higher.
    Character ratio alone rates 'Bournemouth' against 'AFC Bournemouth' at 0.85 but
    'Inter' against 'Internazionale' at 0.53; token overlap catches the second.
    Corporate noise — FC, AFC, CF, SC, the numbers German clubs carry — is dropped
    first, because it is the part that differs between sources and carries no
    information about which club is meant.
    """
    import difflib
    import re
    import unicodedata

    noise = {"fc", "afc", "cf", "sc", "ac", "as", "cd", "rc", "rcd", "ss", "us",
             "sv", "vfl", "vfb", "tsg", "bsc", "1", "04", "05", "07", "96", "1899",
             "de", "the", "club", "calcio", "united", "city"}

    def tokens(name: str) -> tuple[str, set[str]]:
        flat = "".join(
            ch for ch in unicodedata.normalize("NFKD", name.lower())
            if not unicodedata.combining(ch)
        )
        parts = [p for p in re.split(r"[^a-z0-9]+", flat) if p]
        return "".join(parts), {p for p in parts if p not in noise}

    a_flat, a_tokens = tokens(a)
    b_flat, b_tokens = tokens(b)
    ratio = difflib.SequenceMatcher(None, a_flat, b_flat).ratio()
    if a_tokens and b_tokens:
        overlap = len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))
        ratio = max(ratio, overlap)
    return ratio


def link_fixtures(
    conn: psycopg.Connection,
    competition_code: str,
    start_year: int,
    fixtures: list[Fixture],
) -> tuple[int, int]:
    """Attach this source's fixture ids to matches another source already owns.

    The nine leagues with closing odds get their results from football-data.co.uk,
    so their matches exist with no API-Football id and therefore cannot have events
    or team sheets fetched for them — the leagues a reader cares most about had the
    least of this data. This links the two without touching a score.

    Matched on season, both teams and a kickoff date within a day. The day of
    latitude is for timezone disagreement between sources on late kickoffs, and it
    is safe because two league matches between the same pair on consecutive days
    does not happen. `stage` is deliberately not part of the match: the sources
    label rounds differently and the pairing plus the date is already unique.

    Returns (linked, unmatched), where unmatched excludes fixtures that were already
    linked by an earlier run. Counting those as failures made a second run of a
    fully linked league report '0 linked, 307 unmatched', which reads like a total
    failure of the thing that had just worked.

    Unmatched is worth reporting rather than swallowing: a league where rows fail to
    match means the team aliases are wrong, not that the fixtures are missing. That
    is how the split club identities in 0044 and 0045 were found.
    """
    # Scheduled fixtures are linked too, not only played ones. Everything about a
    # match before it kicks off — who is missing it, the confirmed team sheet an
    # hour beforehand — is fetched by provider fixture id, so a match that gets its
    # id only after the final whistle can never carry any of it.
    rows = [
        [f.fixture_id, f.kickoff_date, str(f.home_id), str(f.away_id)]
        for f in fixtures
        if f.status in FINISHED or f.status in SCHEDULED
    ]
    if not rows:
        return 0, 0

    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_af_link",
            ["fixture_id", "kickoff_date", "home_source_id", "away_source_id"],
            rows,
            """
            create temporary table _af_link (
                fixture_id bigint, kickoff_date date,
                home_source_id text, away_source_id text
            )
            """,
        )
        cur.execute(
            """
            insert into core.match_source (match_id, source_id, source_match_id)
            select distinct on (l.fixture_id) m.match_id, src.source_id,
                   l.fixture_id::text
              from _af_link l
              join core.source src on src.code = %s
              join core.team_alias th on th.source_id = src.source_id
                                     and th.source_team_id = l.home_source_id
              join core.team_alias ta on ta.source_id = src.source_id
                                     and ta.source_team_id = l.away_source_id
              join core.competition c on c.code = %s
              join core.season se on se.start_year = %s
              join core.match m on m.competition_id = c.competition_id
                               and m.season_id = se.season_id
                               and m.home_team_id = th.team_id
                               and m.away_team_id = ta.team_id
                               and m.kickoff_date between l.kickoff_date - 1
                                                      and l.kickoff_date + 1
             where not exists (
                    select 1 from core.match_source ms
                     where ms.match_id = m.match_id
                       and ms.source_id = src.source_id)
             order by l.fixture_id, abs(m.kickoff_date - l.kickoff_date)
            on conflict do nothing
            """,
            (SOURCE_CODE, competition_code, start_year),
        )
        linked = cur.rowcount
        cur.execute(
            """
            select count(*) from _af_link l
             where not exists (
                    select 1 from core.match_source ms
                      join core.source s on s.source_id = ms.source_id
                                        and s.code = %s
                     where ms.source_match_id = l.fixture_id::text)
            """,
            (SOURCE_CODE,),
        )
        unmatched = cur.fetchone()[0]
        cur.execute("drop table _af_link")
    return linked, unmatched


def _register_players(
    conn: psycopg.Connection, players: list[tuple[int, str, str | None]]
) -> int:
    """Give this source's players rows of their own, keyed by provider id.

    Not by name. FBref's population already occupies the name space with full
    names and this source writes abbreviations, so matching the two is a separate
    piece of work — `origin` keeps them apart and honest until it is done.

    Idempotent through core.player_source: a provider id already registered is
    left alone rather than creating a second row for the same footballer.
    """
    if not players:
        return 0
    rows = [[str(pid), name, photo] for pid, name, photo in players]
    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_af_player",
            ["source_player_key", "player_name", "photo_url"],
            rows,
            "create temporary table _af_player "
            "(source_player_key text, player_name text, photo_url text)",
        )
        cur.execute(
            """
            insert into core.player (canonical_name, photo_url, origin)
            select distinct on (p.source_player_key)
                   p.player_name, p.photo_url, %s
              from _af_player p
              join core.source s on s.code = %s
             where not exists (
                    select 1 from core.player_source ps
                     where ps.source_id = s.source_id
                       and ps.source_player_key = p.source_player_key)
             order by p.source_player_key
            """,
            (SOURCE_CODE, SOURCE_CODE),
        )
        created = cur.rowcount

        # Link every unlinked id to the row just made for it. Matching on name
        # within this source's own population is safe in a way that matching
        # across sources is not: the names came from here in the first place.
        cur.execute(
            """
            insert into core.player_source (player_id, source_id, source_player_key)
            select distinct on (p.source_player_key)
                   pl.player_id, s.source_id, p.source_player_key
              from _af_player p
              join core.source s on s.code = %s
              join core.player pl on pl.origin = %s
                                 and pl.norm_name = core.norm_name(p.player_name)
             where not exists (
                    select 1 from core.player_source ps
                     where ps.source_id = s.source_id
                       and ps.source_player_key = p.source_player_key)
             order by p.source_player_key, pl.player_id
            """,
            (SOURCE_CODE, SOURCE_CODE),
        )
        cur.execute("drop table _af_player")
    return created


def store_squads(conn: psycopg.Connection, players: Iterable) -> tuple[int, int]:
    """Replace each club's roster with what the provider now reports.

    Delete-then-insert per club, because the endpoint describes today rather than
    accumulating: a player who has left should disappear, and an upsert would keep
    him forever. Only clubs actually returned are cleared, so a failed request
    leaves the previous roster standing rather than emptying it.
    """
    players = list(players)
    if not players:
        return 0, 0

    created = _register_players(
        conn, [(p.player_id, p.name, p.photo_url) for p in players]
    )
    rows = [
        [str(p.team_id), str(p.player_id), p.shirt_number, p.position, p.age]
        for p in players
    ]
    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_af_squad",
            ["source_team_id", "source_player_key", "shirt_number", "position", "age"],
            rows,
            """
            create temporary table _af_squad (
                source_team_id text, source_player_key text,
                shirt_number smallint, position text, age smallint
            )
            """,
        )
        cur.execute(
            """
            delete from core.squad_member sm
             where sm.team_id in (
                select ta.team_id from _af_squad q
                  join core.source s on s.code = %s
                  join core.team_alias ta on ta.source_id = s.source_id
                                         and ta.source_team_id = q.source_team_id)
            """,
            (SOURCE_CODE,),
        )
        cur.execute(
            """
            insert into core.squad_member (
                team_id, player_id, shirt_number, position, age, source_id
            )
            select distinct on (ta.team_id, ps.player_id)
                   ta.team_id, ps.player_id, q.shirt_number, q.position, q.age, s.source_id
              from _af_squad q
              join core.source s on s.code = %s
              join core.team_alias ta on ta.source_id = s.source_id
                                     and ta.source_team_id = q.source_team_id
              join core.player_source ps on ps.source_id = s.source_id
                                        and ps.source_player_key = q.source_player_key
             order by ta.team_id, ps.player_id
            """,
            (SOURCE_CODE,),
        )
        written = cur.rowcount
        cur.execute("drop table _af_squad")
    return written, created


def store_absences(
    conn: psycopg.Connection, match_ids: dict[int, int], absences: Iterable
) -> int:
    """Who misses each fixture, replacing whatever was previously believed.

    Replaced per match rather than merged, because availability changes right up
    to kickoff and a player who has recovered must stop being listed. Merging
    would leave him injured forever, which is the failure mode that makes this
    kind of page untrustworthy.
    """
    absences = list(absences)
    rows = [
        [match_ids[a.fixture_id], str(a.team_id), str(a.player_id),
         a.player_name, a.status, a.reason]
        for a in absences
        if a.fixture_id in match_ids
    ]
    if not rows:
        return 0

    _register_players(conn, [(a.player_id, a.player_name, None) for a in absences])
    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_af_absence",
            ["match_id", "source_team_id", "source_player_key", "player_name",
             "status", "reason"],
            rows,
            """
            create temporary table _af_absence (
                match_id bigint, source_team_id text, source_player_key text,
                player_name text, status text, reason text
            )
            """,
        )
        cur.execute(
            "delete from core.match_absence where match_id in "
            "(select distinct match_id from _af_absence)"
        )
        cur.execute(
            """
            insert into core.match_absence (
                match_id, team_id, player_name, player_id, status, reason, source_id
            )
            select distinct on (a.match_id, ta.team_id, a.player_name)
                   a.match_id, ta.team_id, a.player_name, ps.player_id,
                   a.status, a.reason, s.source_id
              from _af_absence a
              join core.source s on s.code = %s
              join core.team_alias ta on ta.source_id = s.source_id
                                     and ta.source_team_id = a.source_team_id
              left join core.player_source ps on ps.source_id = s.source_id
                                             and ps.source_player_key = a.source_player_key
             order by a.match_id, ta.team_id, a.player_name
            """,
            (SOURCE_CODE,),
        )
        written = cur.rowcount
        cur.execute("drop table _af_absence")
    return written


def store_events(
    conn: psycopg.Connection, match_ids: dict[int, int], events: Iterable
) -> int:
    """Replace a match's events with what the source now reports.

    Delete-then-insert rather than upsert, because there is no natural key: a
    player can be booked twice, score twice inside added time, and come on and off.
    Replacing per match is both idempotent and correct when a feed corrects itself,
    which it does — a goal reassigned after a VAR review changes the scorer, not
    the minute.
    """
    events = list(events)
    rows = []
    for event in events:
        match_id = match_ids.get(event.fixture_id)
        if match_id is None:
            continue
        rows.append([
            match_id, str(event.team_id), event.minute, event.extra_minute,
            event.kind, event.detail, event.player_name, event.assist_name,
            str(event.player_id) if event.player_id is not None else None,
        ])
    if not rows:
        return 0

    _register_players(
        conn,
        [(e.player_id, e.player_name, None)
         for e in events if e.player_id is not None and e.player_name],
    )
    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_af_event",
            ["match_id", "source_team_id", "minute", "extra_minute", "kind",
             "detail", "player_name", "assist_name", "source_player_key"],
            rows,
            """
            create temporary table _af_event (
                match_id bigint, source_team_id text, minute smallint,
                extra_minute smallint, kind text, detail text,
                player_name text, assist_name text, source_player_key text
            )
            """,
        )
        cur.execute(
            "delete from core.match_event where match_id in "
            "(select distinct match_id from _af_event)"
        )
        cur.execute(
            """
            insert into core.match_event (
                match_id, team_id, minute, extra_minute, kind, detail,
                player_name, assist_name, player_id, source_id
            )
            select e.match_id, ta.team_id, e.minute, e.extra_minute, e.kind,
                   e.detail, e.player_name, e.assist_name,
                   -- By provider id, not by name. Names stopped being unique the
                   -- moment a second source started writing abbreviations of them,
                   -- and a name lookup that matches two people attaches a goal to
                   -- the wrong career — or, as it did here, fails the whole load.
                   ps.player_id,
                   src.source_id
              from _af_event e
              join core.source src on src.code = %s
              join core.team_alias ta on ta.source_id = src.source_id
                                     and ta.source_team_id = e.source_team_id
              left join core.player_source ps on ps.source_id = src.source_id
                                             and ps.source_player_key = e.source_player_key
            """,
            (SOURCE_CODE,),
        )
        written = cur.rowcount
        cur.execute("drop table _af_event")
    return written


def store_lineups(
    conn: psycopg.Connection, match_ids: dict[int, int], lineups: Iterable
) -> int:
    """Team sheets: formation and coach, plus the eleven and the bench.

    Written to core.match_lineup and core.match_lineup_player rather than
    core.appearance, because core.player.norm_name is unique and squads from newly
    covered leagues cannot all be resolved to existing players. core.appearance
    remains what it was — who played and what they did, for the leagues whose
    players are loaded as entities.
    """
    lineups = list(lineups)
    rows = [
        [match_ids[lu.fixture_id], str(lu.team_id), lu.formation, lu.coach_name]
        for lu in lineups
        if lu.fixture_id in match_ids
    ]
    if not rows:
        return 0

    with conn.cursor() as cur:
        db.copy_into_temp(
            conn,
            "_af_lineup",
            ["match_id", "source_team_id", "formation", "coach_name"],
            rows,
            """
            create temporary table _af_lineup (
                match_id bigint, source_team_id text, formation text, coach_name text
            )
            """,
        )
        cur.execute(
            """
            insert into core.match_lineup (
                match_id, team_id, formation, coach_name, source_id
            )
            select l.match_id, ta.team_id, l.formation, l.coach_name, src.source_id
              from _af_lineup l
              join core.source src on src.code = %s
              join core.team_alias ta on ta.source_id = src.source_id
                                     and ta.source_team_id = l.source_team_id
            on conflict (match_id, team_id) do update
                set formation  = coalesce(excluded.formation, core.match_lineup.formation),
                    coach_name = coalesce(excluded.coach_name, core.match_lineup.coach_name),
                    updated_at = now()
            """,
            (SOURCE_CODE,),
        )
        written = cur.rowcount
        cur.execute("drop table _af_lineup")

        named = [
            [match_ids[lu.fixture_id], str(lu.team_id), name, number, position,
             started, str(pid) if pid is not None else None]
            for lu in lineups
            if lu.fixture_id in match_ids
            for name, number, position, started, pid in lu.players
        ]
        if named:
            _register_players(
                conn,
                [(pid, name, None)
                 for lu in lineups
                 for name, _, _, _, pid in lu.players
                 if pid is not None],
            )
            db.copy_into_temp(
                conn,
                "_af_named",
                ["match_id", "source_team_id", "player_name", "shirt_number",
                 "position", "is_starter", "source_player_key"],
                named,
                """
                create temporary table _af_named (
                    match_id bigint, source_team_id text, player_name text,
                    shirt_number smallint, position text, is_starter boolean,
                    source_player_key text
                )
                """,
            )
            cur.execute(
                """
                insert into core.match_lineup_player (
                    match_id, team_id, player_name, shirt_number, position,
                    is_starter, player_id
                )
                select distinct on (p.match_id, ta.team_id, p.player_name)
                       p.match_id, ta.team_id, p.player_name, p.shirt_number,
                       p.position, p.is_starter,
                       ps.player_id
                  from _af_named p
                  join core.source src on src.code = %s
                  join core.team_alias ta on ta.source_id = src.source_id
                                         and ta.source_team_id = p.source_team_id
                  left join core.player_source ps
                         on ps.source_id = src.source_id
                        and ps.source_player_key = p.source_player_key
                  -- Only for sheets that were stored above; a player without a
                  -- lineup row would violate the composite foreign key.
                  join core.match_lineup ml on ml.match_id = p.match_id
                                           and ml.team_id = ta.team_id
                 order by p.match_id, ta.team_id, p.player_name, p.is_starter desc
                on conflict (match_id, team_id, player_name) do update
                    set shirt_number = excluded.shirt_number,
                        position     = excluded.position,
                        is_starter   = excluded.is_starter,
                        updated_at   = now()
                """,
                (SOURCE_CODE,),
            )
            cur.execute("drop table _af_named")
    return written


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
