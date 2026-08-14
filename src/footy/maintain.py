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
    """
    report = Report()
    refresh_results(report, season)
    refresh_calendars(report)
    refresh_api_leagues(report)
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

    return checks
