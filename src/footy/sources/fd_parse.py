"""Turn football-data.co.uk CSVs into normalised records for core.*."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from footy.sources import fd_schema as fds
from footy.sources.football_data_uk import CsvFile, parse_date, read_csv

# Verified against 2024/25 kickoffs: La Liga's 21:00 local appears as 20:00 and
# Serie A's 20:45 as 19:45, so the Time column is UK time, not local time.
UK = ZoneInfo("Europe/London")

STAT_COLUMNS: list[str] = [
    "goals",
    "goals_conceded",
    *fds.TEAM_STATS.keys(),
    *fds.MIRRORED_STATS.keys(),
]


@dataclass
class ParsedSeason:
    competition_code: str
    start_year: int
    matches: list[dict] = field(default_factory=list)
    team_stats: list[dict] = field(default_factory=list)
    odds: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def restrict_bookmakers(season: ParsedSeason, keep: frozenset[str]) -> ParsedSeason:
    season.odds = [o for o in season.odds if o["bookmaker"] in keep]
    return season


def _num(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    n = _num(value)
    return None if n is None else round(n)


def _price(value: object) -> float | None:
    """Odds are only meaningful above 1.0; anything else is a placeholder."""
    n = _num(value)
    return None if n is None or n <= 1.0 else round(n, 3)


def _kickoff_utc(day, time_value: object) -> datetime | None:
    if day is None:
        return None
    text = str(time_value).strip() if time_value is not None else ""
    if not text or text in {"nan", "NaT"}:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            t = datetime.strptime(text, fmt).time()
        except ValueError:
            continue
        return datetime.combine(day, t, tzinfo=UK).astimezone(ZoneInfo("UTC"))
    return None


def _pick(row: pd.Series, candidates: tuple[str, ...]) -> object:
    for col in candidates:
        if col in row.index:
            value = row[col]
            if _num(value) is not None:
                return value
    return None


def parse_season(csv_file: CsvFile) -> ParsedSeason:
    df = read_csv(csv_file.path)
    out = ParsedSeason(csv_file.competition_code, csv_file.start_year)
    columns = set(df.columns)

    for position, row in df.iterrows():
        home_raw = str(row["HomeTeam"]).strip()
        away_raw = str(row["AwayTeam"]).strip()
        day = parse_date(row.get("Date"))
        hg, ag = _int(row.get("FTHG")), _int(row.get("FTAG"))

        if day is None or hg is None or ag is None:
            out.skipped.append(
                {
                    "division": csv_file.division,
                    "start_year": csv_file.start_year,
                    "row": int(position) + 2,
                    "home": home_raw,
                    "away": away_raw,
                    "reason": "missing date or full-time score",
                }
            )
            continue

        row_id = len(out.matches)
        referee = str(row.get("Referee", "") or "").strip()
        out.matches.append(
            {
                "row_id": row_id,
                "competition_code": csv_file.competition_code,
                "start_year": csv_file.start_year,
                "kickoff_date": day.isoformat(),
                "kickoff_utc": (k.isoformat() if (k := _kickoff_utc(day, row.get("Time"))) else None),
                # Source spellings, deliberately not canonicalised here. Resolution
                # happens in the database through core.team_alias so that an
                # unrecognised name surfaces in core.unresolved_alias instead of
                # being silently invented by the ingester.
                "home_name": home_raw,
                "away_name": away_raw,
                "home_goals_ft": hg,
                "away_goals_ft": ag,
                "home_goals_ht": _int(row.get("HTHG")),
                "away_goals_ht": _int(row.get("HTAG")),
                "referee_name": referee if referee and referee.lower() != "nan" else None,
                "source_match_id": f"{csv_file.division}-{csv_file.start_year}-{row_id}",
            }
        )
        out.team_stats.extend(_team_stat_rows(row, row_id, hg, ag))
        out.odds.extend(_odds_rows(row, row_id, columns))

    return out


def _team_stat_rows(row: pd.Series, row_id: int, hg: int, ag: int) -> list[dict]:
    """Six rows per match: both teams x (full time, first half, second half).

    Half-time splits come from HTHG/HTAG, so goals are exact for every period.
    The other stats are full-match only in this source and stay null for the halves.
    """
    hhg, ahg = _int(row.get("HTHG")), _int(row.get("HTAG"))
    rows: list[dict] = []

    for is_home in (True, False):
        own_ft, opp_ft = (hg, ag) if is_home else (ag, hg)
        base = {"row_id": row_id, "is_home": is_home}

        ft = {**base, "period": "FT", "goals": own_ft, "goals_conceded": opp_ft}
        for column, (home_col, away_col) in fds.TEAM_STATS.items():
            ft[column] = _int(row.get(home_col if is_home else away_col))
        for column, mirrored in fds.MIRRORED_STATS.items():
            source_home, source_away = fds.TEAM_STATS[mirrored]
            ft[column] = _int(row.get(source_away if is_home else source_home))
        rows.append(ft)

        if hhg is not None and ahg is not None:
            own_ht, opp_ht = (hhg, ahg) if is_home else (ahg, hhg)
            rows.append({**base, "period": "1H", "goals": own_ht, "goals_conceded": opp_ht})
            rows.append(
                {
                    **base,
                    "period": "2H",
                    "goals": own_ft - own_ht,
                    "goals_conceded": opp_ft - opp_ht,
                }
            )
    return rows


def _odds_rows(row: pd.Series, row_id: int, columns: set[str]) -> list[dict]:
    rows: list[dict] = []

    def add(bookmaker: str, market: str, outcome: str, line, price, snapshot: str, agg: bool):
        if price is None:
            return
        rows.append(
            {
                "row_id": row_id,
                "bookmaker": bookmaker,
                "market": market,
                "outcome": outcome,
                "line": line,
                "price": price,
                "snapshot": snapshot,
                "is_aggregate": agg,
            }
        )

    for book in fds.BOOKS_1X2:
        for prefix, snapshot in ((book.open_prefix, "opening"), (book.close_prefix, "closing")):
            if prefix is None:
                continue
            cols = {o: f"{prefix}{o}" for o in ("H", "D", "A")}
            if not all(c in columns for c in cols.values()):
                continue
            prices = {o: _price(row[c]) for o, c in cols.items()}
            # A partial 1X2 triplet cannot be de-vigged, so require all three.
            if any(p is None for p in prices.values()):
                continue
            for outcome, price in prices.items():
                add(book.name, "1X2", outcome, None, price, snapshot, book.is_aggregate)

    for bookmaker, over_col, under_col, snapshot, agg in fds.OVER_UNDER_25:
        if over_col not in columns or under_col not in columns:
            continue
        over, under = _price(row[over_col]), _price(row[under_col])
        if over is None or under is None:
            continue
        add(bookmaker, "OU", "Over", 2.5, over, snapshot, agg)
        add(bookmaker, "OU", "Under", 2.5, under, snapshot, agg)

    line_open = _num(_pick(row, fds.AH_LINE_OPEN))
    line_close = _num(_pick(row, fds.AH_LINE_CLOSE))
    for bookmaker, home_col, away_col, snapshot, agg in fds.ASIAN_HANDICAP:
        if home_col not in columns or away_col not in columns:
            continue
        line = line_close if snapshot == "closing" else line_open
        if line is None:
            line = line_open if snapshot == "closing" else None
        if line is None:
            continue
        home, away = _price(row[home_col]), _price(row[away_col])
        if home is None or away is None:
            continue
        add(bookmaker, "AH", "Home", line, home, snapshot, agg)
        add(bookmaker, "AH", "Away", line, away, snapshot, agg)

    return rows
