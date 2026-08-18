"""The daily cycle, and the checks that say whether it ran.

Everything in this project has so far been run by hand. That was fine while it
was being built and stops being fine the day a season starts, because a page
showing last week's fixtures discredits the accurate numbers next to it.

Two things live here. `refresh` does a day's work in the order the data requires
it. `freshness` asserts the result, and is the more important of the two.

The failures worth designing for are not crashes. Every real incident in this
project has been silent: a materialized view nobody refreshed, a cached CSV that
was never re-downloaded, a truncated API read that emptied a page while the rest
of it rendered, a team arriving under a new name and quietly becoming a second
club. All of those looked like working software. So the checks assert what should
be true — how recent the newest result is, whether every published fixture has a
prediction — rather than watching for exceptions that will not be raised.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from footy import config, db
from footy.load import api_football as af_load
from footy.load import football_data as fd_load
from footy.sources import api_football as af
from footy.sources import football_data_uk as fd
from footy.sources.fd_parse import parse_season, restrict_bookmakers

# Leagues whose results and odds come from football-data.co.uk. Their calendars do
# not: that file is a rolling one-week window, so the forward fixtures come from
# API-Football and only the calendar is taken from it.
CSV_LEAGUES = tuple(config.FOOTBALL_DATA_DIVISIONS)
# Leagues where API-Football is the only source, results and statistics included.
API_LEAGUES = ("BUL-1L", "CZE-1L", "NOR-EL", "INT-UCL", "INT-UEL")


@dataclass
class Step:
    name: str
    detail: str = ""
    ok: bool = True


@dataclass
class Report:
    steps: list[Step] = field(default_factory=list)

    def add(self, name: str, detail: str = "", ok: bool = True) -> Step:
        step = Step(name, detail, ok)
        self.steps.append(step)
        return step

    @property
    def failed(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]


def current_season(conn, competition_code: str) -> int:
    """The season a competition is playing now, from the database rather than the
    calendar: a league that runs March to December is in a different season in
    August than one that runs August to May."""
    row = db.fetch_one(
        conn,
        """
        select max(s.start_year)
          from core.season s
          join core.competition c using (competition_id)
         where c.code = %s
           and exists (select 1 from core.match m where m.season_id = s.season_id)
        """,
        (competition_code,),
    )
    return int(row[0]) if row and row[0] is not None else date.today().year


def refresh_results(report: Report, season: int | None = None) -> None:
    """Re-download and re-load the in-progress season's CSVs.

    `force` is not optional. `download` skips a file that already exists, which is
    right for a finished season and wrong for the one being played — without it a
    daily job would run cleanly for months and never see a new result.
    """
    with db.connect() as conn:
        year = season or max(current_season(conn, c) for c in CSV_LEAGUES)

    files = [f for f in fd.target_files() if f.start_year == year]
    if not files:
        report.add("results", f"no CSV for {year}; nothing published yet", ok=True)
        return

    results = fd.download(files, force=True)
    errors = [(f, s) for f, s in results if s.startswith("error")]
    unpublished = [f for f, s in results if s == "not published"]
    changed = [f for f, s in results if s == "downloaded"]
    if errors:
        report.add(
            "download",
            f"{len(errors)} of {len(files)} failed: {errors[0][1][:60]}",
            ok=False,
        )
    if unpublished:
        report.add(
            "download",
            f"{len(unpublished)} leagues have not published {year} yet: "
            + ", ".join(f.competition_code for f in unpublished),
        )
    # Every file for the season, not only the ones whose bytes changed. "Unchanged"
    # means identical to the copy on disk, which says nothing about whether the
    # database has it — and the first run after a bad cached file is exactly when
    # the two disagree. The loads are idempotent upserts over one season, so
    # re-reading nine files costs seconds and removes a whole class of gap.
    present = [f for f in files if f.path.exists()]
    if not present:
        report.add("results", f"{year}: nothing published yet")
        return

    # One malformed file must not cost the whole run. Every other league's results
    # are independent of it, and a season that parses today may not tomorrow —
    # this source has published a stray column mid-season before.
    parsed = []
    for f in present:
        try:
            parsed.append(
                restrict_bookmakers(parse_season(f), config.CORE_BOOKMAKERS)
            )
        except Exception as exc:
            report.add(
                "parse", f"{f.competition_code} {year}: {str(exc)[:70]}", ok=False
            )
    if not parsed:
        return
    with db.connect() as conn:
        fd_load.seed_teams(conn, parsed)
        conn.commit()
        total = fd_load.LoadResult()
        for p in parsed:
            total += fd_load.load_season(conn, p)
            conn.commit()
    report.add(
        "results",
        f"{year}: {len(present)} files read ({len(changed)} changed), "
        f"{total.matches} matches, {total.odds:,} odds rows",
    )


def refresh_calendars(report: Report) -> None:
    """Upcoming fixtures for the CSV leagues, whose source has none."""
    client = af.Client()
    with db.connect() as conn:
        countries = dict(db.fetch_all(conn, "select code, country from core.competition"))
        seasons = {c: current_season(conn, c) for c in CSV_LEAGUES if c in af.LEAGUE_IDS}

    written = scheduled = 0
    for code, year in seasons.items():
        try:
            fixtures = af.fixtures(client, code, year)
        except Exception as exc:
            report.add("calendar", f"{code}: {str(exc)[:70]}", ok=False)
            continue
        scheduled += sum(1 for f in fixtures if f.status in af.SCHEDULED)
        with db.connect() as conn:
            af_load.seed_teams(conn, fixtures, countries.get(code))
            conn.commit()
            n, _ = af_load.store_fixtures(conn, code, year, fixtures,
                                          include_scheduled=True)
            conn.commit()
        written += n
    report.add("calendars", f"{written} rows touched, {scheduled} fixtures still to play")


def refresh_api_leagues(report: Report) -> None:
    """Results and statistics for the leagues with no other source."""
    client = af.Client()
    with db.connect() as conn:
        countries = dict(db.fetch_all(conn, "select code, country from core.competition"))
        seasons = {c: current_season(conn, c) for c in API_LEAGUES}

    matches = stats = 0
    for code, year in seasons.items():
        try:
            fixtures = af.fixtures(client, code, year)
        except Exception as exc:
            report.add("api results", f"{code}: {str(exc)[:70]}", ok=False)
            continue
        with db.connect() as conn:
            af_load.seed_teams(conn, fixtures, countries.get(code))
            conn.commit()
            n, mapping = af_load.store_fixtures(conn, code, year, fixtures)
            conn.commit()
        matches += n
        # Statistics only for matches that still lack them, which after the first
        # run is a handful a day rather than a season.
        if mapping:
            with db.connect() as conn:
                pending = {
                    fid: mid for fid, mid in mapping.items()
                    if not db.fetch_one(
                        conn,
                        "select 1 from core.match_team_stat "
                        "where match_id = %s and period = 'FT' and corners is not null",
                        (mid,),
                    )
                }
            if pending:
                rows = list(af.statistics(client, list(pending)))
                with db.connect() as conn:
                    stats += af_load.store_stats(conn, pending, rows)
                    conn.commit()
    report.add("api results", f"{matches} matches, {stats} stat rows")


def link_provider_ids(report: Report) -> None:
    """Attach provider fixture ids to results another source owns.

    Needed before events, because a match with no provider id cannot have its
    minutes or team sheet fetched — which is why the five leagues with closing odds
    were the only ones with no timeline. Cheap: one request per competition, and the
    insert skips what is already linked.
    """
    from footy.load import api_football as af_load

    client = af.Client()
    linked = unresolved = 0
    with db.connect() as conn:
        seasons = {c: current_season(conn, c) for c in af.LEAGUE_IDS}

    for code, year in seasons.items():
        try:
            fixtures = af.fixtures(client, code, year)
        except Exception as exc:
            report.add("link ids", f"{code}: {str(exc)[:70]}", ok=False)
            continue
        with db.connect() as conn:
            _, unmatched_clubs = af_load.alias_teams(conn, code, year, fixtures)
            conn.commit()
            n, _ = af_load.link_fixtures(conn, code, year, fixtures)
            conn.commit()
        linked += n
        unresolved += len(unmatched_clubs)
    detail = f"{linked} fixtures linked"
    if unresolved:
        detail += f", {unresolved} clubs unresolved"
    report.add("link ids", detail)


def refresh_absences(report: Report, days: int = 5) -> None:
    """Who is missing the coming fixtures, across every competition.

    One request per date rather than per league, which is the only reason this is
    affordable for fourteen competitions. The provider populates it about three
    days out, so `days` is small on purpose: asking a fortnight ahead returns
    nothing and spends a request finding that out.

    Replaced per match rather than merged, inside the loader, because a recovered
    player has to stop being listed.
    """
    from footy.load import api_football as af_load

    client = af.Client()
    with db.connect() as conn:
        mapping = dict(
            db.fetch_all(
                conn,
                """
                select ms.source_match_id::bigint, ms.match_id
                  from core.match_source ms
                  join core.source s on s.source_id = ms.source_id
                                    and s.code = 'api_football'
                  join core.match m on m.match_id = ms.match_id
                 where m.kickoff_date between current_date and current_date + %s
                """,
                (days,),
            )
        )

    stored = 0
    for offset in range(days + 1):
        day = date.today() + timedelta(days=offset)
        try:
            rows = [a for a in af.absences(client, day) if a.fixture_id in mapping]
        except Exception as exc:
            report.add("absences", f"{day}: {str(exc)[:70]}", ok=False)
            continue
        if not rows:
            continue
        with db.connect() as conn:
            stored += af_load.store_absences(conn, mapping, rows)
            conn.commit()
    report.add("absences", f"{stored} reported over the next {days} days")


def refresh_squads(report: Report, weekday: int = 1) -> None:
    """Rosters, once a week rather than twice a day.

    A squad changes on transfer deadline day and almost never otherwise, while
    costing one request per club — roughly 280 across the fourteen competitions.
    Spending that twice daily to learn nothing would be the single largest waste
    of the quota here.

    Tuesday because the window shuts on a weekday and a Monday run would miss the
    same day's business.
    """
    from footy.load import api_football as af_load

    if date.today().weekday() != weekday:
        report.add("squads", "skipped — refreshed weekly")
        return

    client = af.Client()
    with db.connect() as conn:
        provider_ids = [
            int(r[0])
            for r in db.fetch_all(
                conn,
                """
                select distinct ta.source_team_id
                  from core.match m
                  join core.season se on se.season_id = m.season_id
                  join core.team t on t.team_id in (m.home_team_id, m.away_team_id)
                  join core.team_alias ta on ta.team_id = t.team_id
                  join core.source s on s.source_id = ta.source_id
                                    and s.code = 'api_football'
                 where se.is_current and ta.source_team_id is not null
                """,
            )
        ]
    if not provider_ids:
        report.add("squads", "no clubs with a provider id", ok=False)
        return

    try:
        players = list(af.squads(client, provider_ids))
    except Exception as exc:
        report.add("squads", str(exc)[:80], ok=False)
        return
    with db.connect() as conn:
        written, created = af_load.store_squads(conn, players)
        conn.commit()
    report.add(
        "squads", f"{written:,} places across {len(provider_ids)} clubs"
        + (f", {created} new players" if created else "")
    )


def refresh_events(report: Report, limit: int = 400) -> None:
    """Minutes and team sheets for matches that do not have them yet.

    Two requests per match and no bulk endpoint, which is why it is capped. A day's
    fixtures across every competition is well inside the cap; the cap exists so
    that a first run, or a run after an outage, spends a bounded slice of the daily
    quota instead of the whole of it and starving the loaders that come after.

    Ordered newest first, because a stale recent match is what a reader notices.
    """
    client = af.Client()
    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            """
            select ms.source_match_id::bigint, ms.match_id
              from core.match_source ms
              join core.source s on s.source_id = ms.source_id
                                and s.code = 'api_football'
              join core.match m on m.match_id = ms.match_id
             where m.home_goals_ft is not null
               and m.kickoff_date > current_date - interval '400 days'
               and not exists (select 1 from core.match_event e
                                where e.match_id = m.match_id)
             order by m.kickoff_date desc
             limit %s
            """,
            (limit,),
        )
    mapping = dict(rows)
    if not mapping:
        report.add("events", "nothing new to fetch")
        return

    ids = list(mapping)
    try:
        events = list(af.events(client, ids))
        lineups = list(af.lineups(client, ids))
    except Exception as exc:
        report.add("events", str(exc)[:80], ok=False)
        return
    with db.connect() as conn:
        n_ev = af_load.store_events(conn, mapping, events)
        n_lu = af_load.store_lineups(conn, mapping, lineups)
        conn.commit()
    report.add("events", f"{len(mapping)} matches, {n_ev:,} events, {n_lu} lineups")


def rebuild_features(report: Report) -> None:
    """Feature layer and every materialized view.

    Incremental is correct here and only here: a daily run appends matches later
    than everything already stored, so no existing feature row becomes stale.
    Backfilling *history* does invalidate them, which is why the loaders that do
    that call for a full rebuild instead.
    """
    from footy.features import build as feature_build

    with db.connect() as conn:
        team_rows, match_rows = feature_build.build(conn)
        conn.commit()
    report.add("features", f"{team_rows:,} team rows, {match_rows:,} match rows added")


def repredict(report: Report, days: int = 21) -> None:
    """Predict the coming fixtures for every competition that publishes anything."""
    from footy.models import predict as pr

    with db.connect() as conn:
        codes = [
            r[0]
            for r in db.fetch_all(
                conn,
                """
                select distinct c.code
                  from ml.market_competition mc
                  join core.competition c using (competition_id)
                 where mc.status = 'shipping'
                 order by 1
                """,
            )
        ]

    total = 0
    for code in codes:
        try:
            written = pr.run(competition=code, as_of=date.today(), days=days)
            total += written.predictions
        except Exception as exc:
            report.add("predict", f"{code}: {str(exc)[:80]}", ok=False)
    report.add("predictions", f"{total:,} probabilities stored across {len(codes)} leagues")


def refresh(days: int = 21, season: int | None = None) -> Report:
    """A day's work, in the order the data requires.

    Results before features, because a feature is computed from a result.
    Features before predictions, because the recalibration is derived by replaying
    the model over settled history. Settlement itself needs no step: ml.observation
    is a view over core, so a result becomes a settled outcome the moment it lands.

    Provider ids before events, because a match with no id cannot have its minutes
    fetched, and events before features, because the timing views are refreshed as
    part of the feature build.
    """
    report = Report()
    refresh_results(report, season)
    refresh_calendars(report)
    refresh_api_leagues(report)
    link_provider_ids(report)
    refresh_events(report)
    refresh_squads(report)
    refresh_absences(report)
    rebuild_features(report)
    repredict(report, days)
    return report


# ---------------------------------------------------------------- freshness ----

@dataclass
class Check:
    name: str
    value: str
    ok: bool
    note: str = ""


def freshness(max_result_age: int = 4, min_upcoming: int = 5) -> list[Check]:
    """Assert the things that are true when the pipeline is working.

    Written as assertions about the data rather than about the job, because a job
    that has stopped running raises nothing at all. If the newest result is a week
    old during a season, something is broken whatever the logs say.
    """
    checks: list[Check] = []
    today = date.today()

    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            """
            select c.code,
                   max(m.kickoff_date) filter (where m.home_goals_ft is not null),
                   count(*) filter (where m.status = 'scheduled'
                                      and m.kickoff_date >= current_date),
                   count(*) filter (where m.home_goals_ft is null
                                      and m.kickoff_date < current_date - 1)
              from core.match m
              join core.competition c using (competition_id)
             where exists (
                    select 1 from ml.market_competition mc
                     where mc.competition_id = c.competition_id
                       and mc.status = 'shipping')
             group by c.code order by c.code
            """,
        )
        for code, newest, upcoming, overdue in rows:
            # Not "how old is the newest result" — that fails every August, when a
            # league correctly has nothing since May because its season has not
            # started. What matters is whether a match that has already kicked off
            # is still missing its score. That has no false positives: it is only
            # true when a result should have been loaded and was not.
            #
            # A day of grace, because a match kicking off tonight has not finished
            # and the source publishes in batches.
            checks.append(Check(
                f"{code} results loaded",
                "up to date" if overdue == 0 else f"{overdue} missing",
                overdue == 0,
                "a fixture has kicked off and its result was never loaded",
            ))
            checks.append(Check(
                f"{code} fixtures ahead", str(upcoming), upcoming >= min_upcoming,
                "the calendar is running out",
            ))
            if newest:
                checks.append(Check(
                    f"{code} newest result", f"{newest} ({(today - newest).days}d ago)",
                    True, "",
                ))

        published, missing = db.fetch_one(
            conn,
            """
            select count(*), count(*) filter (where not has_predictions)
              from public.fixture
             where home_goals_ft is null
               and kickoff_date between current_date and current_date + 14
               and exists (
                    select 1 from ml.market_competition mc
                      join core.competition c using (competition_id)
                     where c.code = public.fixture.competition_code
                       and mc.status = 'shipping')
            """,
        )
        checks.append(Check(
            "fixtures priced (next 14 days)",
            f"{published - missing} of {published}",
            missing == 0,
            "a published fixture with no probabilities renders as an empty page",
        ))

        stale = db.fetch_one(
            conn,
            """
            select count(*) from core.match m
             where m.home_goals_ft is not null
               and not exists (select 1 from features.team_match f
                                where f.match_id = m.match_id)
            """,
        )[0]
        checks.append(Check(
            "results with features", "all" if stale == 0 else f"{stale} missing",
            stale == 0, "the feature layer is behind the results",
        ))

        # The materialized views carry no timestamp, so compare their newest
        # season against the matches themselves. This is the check that would
        # have caught two of the incidents this project has already had.
        drift = db.fetch_one(
            conn,
            """
            select count(*) from (
              select t.team_id
                from core.match m
                join core.team t on t.team_id in (m.home_team_id, m.away_team_id)
               where m.home_goals_ft is not null
              except
              select team_id from public.team
            ) x
            """,
        )[0]
        checks.append(Check(
            "team views current", "yes" if drift == 0 else f"{drift} teams missing",
            drift == 0, "public.team has not been refreshed since a load",
        ))

        # Events are the one feed with no bulk endpoint, so they are the one most
        # likely to fall quietly behind: the pages still render, just without a
        # timeline, and nothing complains. Compare against matches recent enough
        # to be worth fetching rather than against all of history, which will
        # never be complete and should not read as a failure.
        with_events, recent = db.fetch_one(
            conn,
            """
            select count(*) filter (
                     where exists (select 1 from core.match_event e
                                    where e.match_id = m.match_id)),
                   count(*)
              from core.match m
              join core.match_source ms on ms.match_id = m.match_id
              join core.source s on s.source_id = ms.source_id
                                and s.code = 'api_football'
             where m.home_goals_ft is not null
               and m.kickoff_date between current_date - 30 and current_date
            """,
        )
        checks.append(Check(
            "recent matches with a timeline",
            f"{with_events} of {recent}" if recent else "no recent matches",
            recent == 0 or with_events >= recent * 0.9,
            "the event loader is behind; match pages will render without a timeline",
        ))

        # The check that found two migrations' worth of split club identities, and
        # would have found them without anyone thinking to look. A fixture fails to
        # link when the alias points at a club that has no matches in the league —
        # which is what a duplicate identity is. Similarity scoring missed both
        # 'Lyon' against 'Olympique Lyonnais' and 'Stade Brestois 29' against
        # 'Brest', because as text they have almost nothing in common. Coverage does
        # not care why two records disagree, only that one found no partner.
        gaps = db.fetch_all(
            conn,
            """
            select c.code, count(*) as played,
                   count(*) filter (where exists (
                       select 1 from core.match_source ms
                         join core.source s on s.source_id = ms.source_id
                                           and s.code = 'api_football'
                        where ms.match_id = m.match_id)) as mapped
              from core.match m
              join core.competition c using (competition_id)
              join core.season se on se.season_id = m.season_id
             where m.home_goals_ft is not null
               and se.start_year = (select max(start_year) - 1 from core.season)
             group by 1 having count(*) > 50
             order by 1
            """,
        )
        poor = [
            f"{code} {mapped}/{played}"
            for code, played, mapped in gaps
            if mapped < played * 0.95
        ]
        checks.append(Check(
            "fixtures linked to the provider",
            f"{len(gaps) - len(poor)} of {len(gaps)} leagues above 95%",
            not poor,
            f"a league below 95% usually means a duplicate club: {', '.join(poor)}",
        ))

        banded = db.fetch_one(
            conn, "select count(*) from public.team_season_timing"
        )[0]
        checks.append(Check(
            "goal timing view", f"{banded:,} rows", banded > 0,
            "team_season_timing is empty, so no page can draw the timing chart",
        ))

    return checks
