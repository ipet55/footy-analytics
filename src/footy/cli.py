from __future__ import annotations

from collections import Counter

import typer
from rich.console import Console
from rich.table import Table

from footy import config, db
from footy.load import football_data as fd_load
from footy.sources import football_data_uk as fd
from footy.sources.fd_parse import parse_season, restrict_bookmakers

app = typer.Typer(add_completion=False, help="Football data ingestion pipeline.")
console = Console()


@app.command()
def fetch(force: bool = typer.Option(False, help="Re-download even if cached.")):
    """Download football-data.co.uk CSVs for all configured leagues and seasons."""
    files = fd.target_files()
    console.print(f"Fetching {len(files)} season files...")
    results = fd.download(files, force=force)
    counts = Counter(status.split(":")[0] for _, status in results)
    for status, n in counts.items():
        console.print(f"  {status}: {n}")
    for f, status in results:
        if status.startswith("error"):
            console.print(f"[red]{f.url} -> {status}[/red]")


@app.command()
def parse():
    """Parse the downloaded CSVs and report what would be loaded, without touching the DB."""
    totals = Counter()
    skipped = []
    for f in fd.target_files():
        season = parse_season(f)
        totals["matches"] += len(season.matches)
        totals["team_stats"] += len(season.team_stats)
        totals["odds"] += len(season.odds)
        skipped.extend(season.skipped)

    table = Table(title="Parsed from football-data.co.uk")
    table.add_column("Records")
    table.add_column("Count", justify="right")
    for key in ("matches", "team_stats", "odds"):
        table.add_row(key, f"{totals[key]:,}")
    console.print(table)
    if skipped:
        console.print(f"[yellow]{len(skipped)} rows skipped[/yellow]")
        for s in skipped[:10]:
            console.print(f"  {s}")


@app.command("load")
def load_cmd(
    season: int | None = typer.Option(None, help="Load only this starting year, e.g. 2024."),
    competition: str | None = typer.Option(None, help="Load only this code, e.g. ENG-PL."),
    all_books: bool = typer.Option(
        False, "--all-books", help="Load all 16 bookmakers instead of the 5 core ones."
    ),
):
    """Parse and load results, team stats and odds into Supabase."""
    files = [
        f
        for f in fd.target_files()
        if (season is None or f.start_year == season)
        and (competition is None or f.competition_code == competition)
    ]
    console.print(f"Parsing {len(files)} season files...")
    parsed = [parse_season(f) for f in files]
    if not all_books:
        parsed = [restrict_bookmakers(p, config.CORE_BOOKMAKERS) for p in parsed]
        console.print(f"Odds limited to: {', '.join(sorted(config.CORE_BOOKMAKERS))}")

    with db.connect() as conn:
        teams, aliases = fd_load.seed_teams(conn, parsed)
        conn.commit()
        console.print(f"Identity layer: {teams} teams upserted, {aliases} new aliases")

        run_id = db.start_run(
            conn,
            fd.SOURCE_CODE,
            "match",
            {"seasons": sorted({p.start_year for p in parsed}),
             "competitions": sorted({p.competition_code for p in parsed})},
        )
        conn.commit()

        total = fd_load.LoadResult()
        try:
            for p in parsed:
                result = fd_load.load_season(conn, p)
                conn.commit()
                total += result
                console.print(
                    f"  {p.competition_code} {p.start_year}/{str(p.start_year + 1)[-2:]}: "
                    f"{result.matches} matches, {result.team_stats} stats, {result.odds} odds"
                )
        except Exception as exc:
            conn.rollback()
            db.finish_run(conn, run_id, "failed", error=str(exc)[:2000])
            conn.commit()
            raise

        rows_read = sum(len(p.matches) + len(p.team_stats) + len(p.odds) for p in parsed)
        db.finish_run(
            conn,
            run_id,
            "success",
            rows_read=rows_read,
            rows_written=total.matches + total.team_stats + total.odds,
        )
        conn.commit()

    console.print(
        f"\n[green]Loaded {total.matches:,} matches, {total.team_stats:,} stat rows, "
        f"{total.odds:,} odds rows[/green]"
    )


@app.command("load-xg")
def load_xg(
    season: int | None = typer.Option(None, help="Load only this starting year."),
    competition: str | None = typer.Option(None, help="Load only this code, e.g. ENG-PL."),
):
    """Fetch Understat xG and write it onto the match rows that already exist."""
    from footy.load import understat as us_load
    from footy.sources import understat as us

    comps = [competition] if competition else list(us.LEAGUES)
    years = [season] if season else config.SEASON_START_YEARS

    console.print(f"Fetching {len(comps) * len(years)} league-seasons from Understat...")
    seasons = []
    for comp in comps:
        for year in years:
            seasons.append(us.fetch_season(comp, year))
    console.print(f"  {sum(len(s.matches) for s in seasons):,} matches fetched")

    with db.connect() as conn:
        added, unresolved = us_load.register_aliases(conn, seasons)
        console.print(f"Identity layer: {added} Understat aliases registered")
        if unresolved:
            console.print(f"[red]{len(unresolved)} names could not be resolved:[/red]")
            for name, country in unresolved:
                console.print(f"    {name}  ({country})")
            console.print(
                "Add them to UNDERSTAT_ALIASES in src/footy/teams.py, then re-run. "
                "They are also queued in core.unresolved_alias."
            )
            raise typer.Exit(1)

        run_id = db.start_run(conn, us.SOURCE_CODE, "match_xg",
                              {"seasons": years, "competitions": comps})
        conn.commit()

        total = drift = disputes = 0
        try:
            for s in seasons:
                updated, dd, disp = us_load.load_season(conn, s)
                conn.commit()
                total += updated
                drift += dd
                disputes += disp
                note = f"  [yellow]{disp} score dispute(s)[/yellow]" if disp else ""
                console.print(
                    f"  {s.competition_code} {s.start_year}: {updated} stat rows enriched{note}"
                )
        except Exception as exc:
            conn.rollback()
            db.finish_run(conn, run_id, "failed", error=str(exc)[:2000])
            conn.commit()
            raise

        db.finish_run(conn, run_id, "success", rows_written=total)
        conn.commit()

    console.print(f"\n[green]Enriched {total:,} stat rows with xG[/green]")
    if drift:
        console.print(f"[yellow]{drift} fixtures differ by >2 days between sources[/yellow]")
    if disputes:
        console.print(
            f"[yellow]{disputes} score disagreement(s) recorded in core.result_dispute[/yellow]"
        )


@app.command("load-elo")
def load_elo():
    """Fetch ClubElo rating histories and load them into core.team_rating."""
    from datetime import date

    from footy.load import clubelo as ce_load
    from footy.sources import clubelo as ce

    with db.connect() as conn:
        # Club names are only discovered once. On a resume they come back out of
        # the identity layer, which avoids 12 more requests to a host that is
        # already shedding load.
        known = {
            r[0]: r[1]
            for r in db.fetch_all(
                conn,
                """
                select a.alias_name, t.country
                  from core.team_alias a
                  join core.source s on s.source_id = a.source_id and s.code = %s
                  join core.team t on t.team_id = a.team_id
                """,
                (ce.SOURCE_CODE,),
            )
        }
        if known:
            clubs = known
            console.print(f"Using {len(clubs)} ClubElo clubs already in the identity layer")
        else:
            console.print("Discovering ClubElo clubs...")
            clubs = ce_load.discover_clubs(range(config.SEASON_START_YEARS[0], 2026))
            console.print(f"  {len(clubs)} top-flight clubs across the 5 countries")
            added, unresolved = ce_load.register_aliases(conn, clubs)
            console.print(f"Identity layer: {added} ClubElo aliases registered")
            if unresolved:
                console.print(f"[red]{len(unresolved)} names could not be resolved:[/red]")
                for name, country in unresolved:
                    console.print(f"    {name}  ({country})")
                console.print("Add them to CLUBELO_ALIASES in src/footy/teams.py, then re-run.")
                raise typer.Exit(1)

        # Resume rather than refetch: a club with no rating rows is one that
        # previously timed out, and the API is slow enough that this matters.
        already = {
            r[0]
            for r in db.fetch_all(
                conn,
                """
                select a.alias_name
                  from core.team_alias a
                  join core.source s on s.source_id = a.source_id and s.code = %s
                 where exists (select 1 from core.team_rating tr
                                where tr.team_id = a.team_id
                                  and tr.source_id = a.source_id)
                """,
                (ce.SOURCE_CODE,),
            )
        }
        todo = sorted(set(clubs) - already)
        if already:
            console.print(f"  {len(already)} clubs already loaded, fetching {len(todo)}")
        if not todo:
            console.print("[green]All clubs already have ratings.[/green]")
            raise typer.Exit(0)

        console.print(f"Fetching {len(todo)} rating histories (the API is slow)...")
        since = date(config.SEASON_START_YEARS[0], 7, 1)
        histories = ce.team_histories(todo, since=since)
        failed = [c for c, rows in histories.items() if not rows]
        fetched = sum(len(v) for v in histories.values())
        console.print(f"  {fetched:,} rating periods fetched, {len(failed)} clubs failed")
        if failed:
            console.print(f"  [yellow]failed: {', '.join(failed[:10])}[/yellow]")

        run_id = db.start_run(conn, ce.SOURCE_CODE, "team_rating", {"clubs": len(clubs)})
        conn.commit()
        written = ce_load.load_ratings(conn, histories)
        db.finish_run(conn, run_id, "success", rows_read=fetched, rows_written=written)
        conn.commit()

    console.print(f"\n[green]Loaded {written:,} rating periods into core.team_rating[/green]")


@app.command("build-elo")
def build_elo(
    variant: str | None = typer.Option(None, help="elo_goals or elo_xg. Both if omitted."),
    k: float = typer.Option(20.0, help="Elo K factor."),
    home_advantage: float = typer.Option(65.0, help="Home advantage in Elo points."),
    season_regression: float = typer.Option(0.25, help="Regression to the mean between seasons."),
):
    """Compute Elo ratings from stored results. No external API involved."""
    from footy.load import elo as elo_load
    from footy.ratings import EloParams

    params = EloParams(k=k, home_advantage=home_advantage, season_regression=season_regression)
    variants = [variant] if variant else list(elo_load.VARIANTS)

    with db.connect() as conn:
        for name in variants:
            console.print(f"Computing {name} (K={k}, HA={home_advantage}, "
                          f"regression={season_regression})...")
            written = elo_load.build(conn, name, params)
            conn.commit()
            overlaps = elo_load.check_no_overlaps(conn, name)
            console.print(f"  {written:,} rating periods written")
            if overlaps:
                console.print(f"  [red]{overlaps} overlapping ranges — as-of lookups "
                              f"would return more than one rating[/red]")
                raise typer.Exit(1)
            console.print("  [green]no overlapping ranges[/green]")
            console.print(f"  strongest teams now on {name}:")
            for team, country, rating in elo_load.latest(conn, name, limit=5):
                console.print(f"    {float(rating):7.1f}  {team} ({country})")


@app.command("build-features")
def build_features(
    rebuild: bool = typer.Option(False, "--rebuild", help="Truncate and rebuild from scratch."),
):
    """Populate the feature layer from stored matches, ratings and odds."""
    from footy.features import build as fb

    with db.connect() as conn:
        console.print("Building features (rolling windows stop at the previous fixture)...")
        team_rows, match_rows = fb.build(conn, rebuild=rebuild)
        conn.commit()
    console.print(f"  features.team_match: {team_rows:,} rows")
    console.print(f"  features.match:      {match_rows:,} rows")


@app.command()
def backtest(
    competition: str = typer.Option("ENG-PL", help="Competition code, e.g. ENG-PL."),
    test_from: str = typer.Option("2022-07-01", help="First kickoff date to score."),
    test_to: str | None = typer.Option(
        None, help="Stop before this date. Use to tune on one window and report on another."
    ),
    xi: float = typer.Option(0.0018, help="Time-decay rate for match weights."),
    refit_every_days: int = typer.Option(14, help="Days between refits."),
):
    """Walk-forward backtest of the Dixon-Coles goals model against closing odds."""
    from datetime import date as _date

    from footy.models import backtest as bt

    scores = bt.run(
        competition=competition,
        test_from=_date.fromisoformat(test_from),
        test_to=_date.fromisoformat(test_to) if test_to else None,
        xi=xi,
        refit_every_days=refit_every_days,
    )
    window = f"from {test_from}" + (f" to {test_to}" if test_to else "")
    bt.report(scores, label=f"{competition} {window}")


@app.command("backtest-counts")
def backtest_counts(
    stat: str | None = typer.Option(
        None, help="corners, cards, fouls or shots. All four if omitted."
    ),
    competition: str = typer.Option("ENG-PL", help="Competition code, e.g. ENG-PL."),
    test_from: str = typer.Option("2022-07-01", help="First kickoff date to score."),
    xi: float | None = typer.Option(
        None, help="Time-decay rate. Defaults to the per-statistic value in SPECS."
    ),
    refit_every_days: int = typer.Option(30, help="Days between refits."),
    no_convolution: bool = typer.Option(
        False, "--no-convolution", help="Skip the convolution control to halve the output."
    ),
    warmup_matches: int = typer.Option(
        400, help="Predictions to accumulate before the recalibration switches on."
    ),
    reliability: bool = typer.Option(
        True, help="Also print reliability tables for the middle total line."
    ),
):
    """Walk-forward backtest of the corner, card, foul and shot count markets."""
    from datetime import date as _date

    from footy.models import counts as cm
    from footy.models import counts_backtest as cb

    stats = [stat] if stat else list(cm.SPECS)
    for name in stats:
        if name not in cm.SPECS:
            console.print(f"[red]unknown stat {name}; expected one of "
                          f"{', '.join(cm.SPECS)}[/red]")
            raise typer.Exit(1)

    for name in stats:
        console.print(f"\nFitting {name} for {competition} (walk-forward, this takes a while)...")
        result = cb.run(
            name,
            competition=competition,
            test_from=_date.fromisoformat(test_from),
            xi=xi,
            refit_every_days=refit_every_days,
            include_convolution=not no_convolution,
            warmup_matches=warmup_matches,
        )
        cb.report(result)
        if reliability:
            lines = sorted(cm.SPECS[name].total_lines)
            middle = lines[len(lines) // 2]
            cb.calibration_table(result, "total", middle)
            cb.calibration_table(result, "total calibrated", middle)


@app.command("blend-check")
def blend_check(
    stat: str | None = typer.Option(
        None, help="corners, cards, fouls or shots. All four if omitted."
    ),
    competition: str | None = typer.Option(
        None, help="Competition code. All five if omitted."
    ),
    scope: str = typer.Option("total", help="total, home or away."),
    in_sample_offset: bool = typer.Option(
        False,
        "--in-sample-offset",
        help="Train the correction on the base model's own fitted rates, which "
             "measures its overfitting rather than the features.",
    ),
):
    """Ask whether the feature layer improves the count models. It currently does not.

    Regenerates the comparison behind docs/04-phase2-feature-blend.md, which
    rejected the blend. Kept runnable because that document makes a claim, and
    because it is the harness for the next attempt: once congestion and squad
    availability are real features rather than league-only rest days, this
    command is what says whether they were worth buying.
    """
    from footy.models import blend_check as bc
    from footy.models import counts as cm

    stats = (stat,) if stat else tuple(cm.SPECS)
    for name in stats:
        if name not in cm.SPECS:
            console.print(f"[red]unknown stat {name}; expected one of "
                          f"{', '.join(cm.SPECS)}[/red]")
            raise typer.Exit(1)
    if scope not in ("total", "home", "away"):
        console.print(f"[red]unknown scope {scope}; expected total, home or away[/red]")
        raise typer.Exit(1)

    competitions = (competition,) if competition else bc.LEAGUES
    console.print(
        f"Comparing the blend against the plain models on "
        f"{len(competitions) * len(stats)} league-market combinations. "
        f"Each one refits the base model {'9 times' if not in_sample_offset else 'once'}, "
        f"so this takes a few minutes..."
    )
    try:
        results = bc.run(
            stats=stats,
            competitions=competitions,
            scope=scope,
            out_of_fold=not in_sample_offset,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    bc.report(results)


@app.command()
def predict(
    competition: str = typer.Option("ENG-PL", help="Competition code, e.g. ENG-PL."),
    as_of: str | None = typer.Option(
        None,
        help="Fit on matches before this date and predict from it. Defaults to today.",
    ),
    days: int = typer.Option(7, help="How far past the as-of date to predict."),
    stat: str | None = typer.Option(
        None, help="Restrict the count markets to one statistic."
    ),
    no_goals: bool = typer.Option(
        False, "--no-goals", help="Skip the Dixon-Coles goals markets."
    ),
    calibration_window_days: int = typer.Option(
        730, help="History replayed to derive the recalibration."
    ),
):
    """Fit as of a date and store probabilities for the fixtures that follow it.

    Point --as-of at a past matchday to check the output against results that
    are already known; the models still only see matches played before it.
    """
    from datetime import date as _date
    from datetime import timedelta

    from footy.models import counts as cm
    from footy.models import predict as pr

    if stat is not None and stat not in cm.SPECS:
        console.print(f"[red]unknown stat {stat}; expected one of "
                      f"{', '.join(cm.SPECS)}[/red]")
        raise typer.Exit(1)

    when = _date.fromisoformat(as_of) if as_of else _date.today()
    console.print(
        f"Predicting {competition} for {days} days from {when} "
        f"(fitting on matches before it, then replaying "
        f"{calibration_window_days} days to calibrate)..."
    )
    written = pr.run(
        competition=competition,
        as_of=when,
        days=days,
        stats=(stat,) if stat else ("corners", "cards", "fouls", "shots"),
        goals=not no_goals,
        calibration_window_days=calibration_window_days,
    )
    if not written.fixtures:
        console.print(f"[yellow]no fixtures between {when} and "
                      f"{when + timedelta(days=days)}[/yellow]")
        return
    console.print(f"  fixtures:    {written.fixtures}")
    console.print(f"  fits stored: {written.models}")
    console.print(f"  predictions: {written.predictions:,}")
    console.print(f"  calibrations:{written.calibrated_markets:>4}")
    for note in written.skipped:
        console.print(f"  [yellow]skipped {note}[/yellow]")


@app.command("show-predictions")
def show_predictions(
    competition: str = typer.Option("ENG-PL", help="Competition code, e.g. ENG-PL."),
    market: str = typer.Option("goals_1x2", help="Market code to display."),
    limit: int = typer.Option(10, help="Fixtures to show."),
    include_held: bool = typer.Option(
        False, "--include-held", help="Show markets not yet cleared for publication."
    ),
):
    """Print stored predictions, newest fixtures first, with results where known."""
    with db.connect() as conn:
        status = db.fetch_one(
            conn, "select status from ml.market where market_code = %s", (market,)
        )
        if status is None:
            console.print(f"[red]unknown market {market}[/red]")
            raise typer.Exit(1)
        if status[0] != "shipping" and not include_held:
            console.print(
                f"[yellow]{market} is marked '{status[0]}' and is not cleared for "
                f"publication; pass --include-held to see it anyway[/yellow]"
            )
            return
        rows = db.fetch_all(
            conn,
            """
            select p.kickoff_date, h.canonical_name, a.canonical_name,
                   p.line, p.selection, p.p_raw, p.p_calibrated, p.hit
              from ml.prediction_scored p
              join core.match m on m.match_id = p.match_id
              join core.team h on h.team_id = m.home_team_id
              join core.team a on a.team_id = m.away_team_id
              join core.competition c on c.competition_id = p.competition_id
                                     and c.code = %s
             where p.market_code = %s
             order by p.kickoff_date desc, m.match_id, p.line, p.selection
             limit %s
            """,
            (competition, market, limit),
        )
    if not rows:
        console.print(f"[yellow]no stored predictions for {market}[/yellow]")
        return
    console.print(f"\n[bold]{market}[/bold] ({status[0]})")
    console.print(f"  {'date':<11} {'fixture':<34} {'sel':<5} {'raw':>7} "
                  f"{'shown':>7}  result")
    for kickoff, home, away, line, selection, raw, calibrated, hit in rows:
        fixture = f"{home} v {away}"[:34]
        label = f"{selection}" + (f" {line:g}" if line is not None else "")
        result = "pending" if hit is None else ("hit" if hit else "miss")
        console.print(
            f"  {kickoff!s:<11} {fixture:<34} {label:<5} {float(raw):>6.1%} "
            f"{float(calibrated):>6.1%}  {result}"
        )


@app.command()
def verify():
    """Integrity and coverage report over what is actually in the database."""
    checks: list[tuple[str, str]] = [
        ("Matches", "select count(*) from core.match"),
        ("Teams", "select count(*) from core.team"),
        ("Team stat rows", "select count(*) from core.match_team_stat"),
        ("Odds rows", "select count(*) from core.odds"),
        ("Unresolved names", "select count(*) from core.unresolved_alias where resolved_at is null"),
        (
            "Matches with no odds",
            """select count(*) from core.match m
                 where not exists (select 1 from core.odds o where o.match_id = m.match_id)""",
        ),
        (
            "Matches missing a stat row",
            """select count(*) from core.match m
                 where (select count(*) from core.match_team_stat s
                         where s.match_id = m.match_id and s.period = 'FT') <> 2""",
        ),
        (
            "Score/stat disagreement",
            """select count(*) from core.match m
                 join core.match_team_stat s on s.match_id = m.match_id and s.period = 'FT'
                where s.goals <> case when s.is_home then m.home_goals_ft else m.away_goals_ft end""",
        ),
        (
            "Halves not summing to full time",
            """select count(*) from core.match_team_stat ft
                 join core.match_team_stat h1
                   on h1.match_id = ft.match_id and h1.team_id = ft.team_id and h1.period = '1H'
                 join core.match_team_stat h2
                   on h2.match_id = ft.match_id and h2.team_id = ft.team_id and h2.period = '2H'
                where ft.period = 'FT' and ft.goals <> h1.goals + h2.goals""",
        ),
        (
            "Closing 1X2 coverage",
            "select count(*) from core.market_1x2 where snapshot = 'closing'",
        ),
        (
            "Impossible de-vigged probabilities",
            """select count(*) from core.market_1x2
                where abs(p_home + p_draw + p_away - 1) > 0.0001""",
        ),
    ]

    table = Table(title="Integrity report")
    table.add_column("Check")
    table.add_column("Value", justify="right")
    with db.connect() as conn:
        for label, sql in checks:
            value = db.fetch_one(conn, sql)[0]
            table.add_row(label, f"{value:,}")
    console.print(table)


@app.command()
def status():
    """Show configuration and whether database credentials are present."""
    console.print(f"Project root:  {config.PROJECT_ROOT}")
    console.print(f"Leagues:       {', '.join(config.FOOTBALL_DATA_DIVISIONS)}")
    console.print(
        f"Seasons:       {config.SEASON_START_YEARS[0]}/"
        f"{str(config.SEASON_START_YEARS[0] + 1)[-2:]} - "
        f"{config.SEASON_START_YEARS[-1]}/{str(config.SEASON_START_YEARS[-1] + 1)[-2:]}"
    )
    have = config.has_database_url()
    console.print(f"DATABASE_URL:  {'[green]set[/green]' if have else '[red]missing[/red]'}")


if __name__ == "__main__":
    app()
