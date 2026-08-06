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
