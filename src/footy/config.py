from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
STAGE_DIR = DATA_DIR / "stage"

load_dotenv(PROJECT_ROOT / ".env")


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and paste the Supabase "
            "session pooler connection string (Project Settings -> Database)."
        )
    return url


def has_database_url() -> bool:
    return bool(os.getenv("DATABASE_URL", "").strip())


# Competition code in core.competition -> football-data.co.uk division code.
#
# The four after France publish the same columns as the first five — shots,
# corners, fouls, cards and Pinnacle closing odds — so every model and market
# applies to them unchanged. Their files omit the referee column, which only E0
# carries, and referees are backfilled from FBref anyway.
FOOTBALL_DATA_DIVISIONS: dict[str, str] = {
    "ENG-PL": "E0",
    "ESP-LL": "SP1",
    "ITA-SA": "I1",
    "GER-BL": "D1",
    "FRA-L1": "F1",
    "NED-ED": "N1",
    "BEL-PL": "B1",
    "POR-PL": "P1",
    "TUR-SL": "T1",
}

FIRST_SEASON = 2014


def current_season_year(today: date | None = None) -> int:
    """The season now being played, by starting year.

    A European season starting in August is named for the year it began, so
    anything from July onward belongs to this calendar year and anything before it
    to the last one.
    """
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


# Seasons by starting year. 2014 is the earliest season Understat publishes xG for,
# so the history window matches the availability of the strongest feature.
#
# The upper bound is computed rather than written down. It was hard-coded at 2025
# and the season rolled over, which meant the CSV for the season being played was
# never in the list of files to fetch — so a daily refresh reported success and
# loaded no results, indefinitely. A constant here ages into a silent outage.
SEASON_START_YEARS: list[int] = list(range(FIRST_SEASON, current_season_year() + 1))


def season_code(start_year: int) -> str:
    """2014 -> '1415', matching football-data.co.uk's directory naming."""
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


# Twenty bookmakers quoting the same match are ~99% correlated, so storing all of
# them costs ~100 MB for very little extra signal. These five carry it all: the
# sharpest book, the consensus, the best available price, the largest retail book,
# and the exchange. Load the rest with `footy load --all-books` if ever needed —
# the CSVs stay on disk, so nothing is lost by starting narrow.
CORE_BOOKMAKERS: frozenset[str] = frozenset(
    {"Pinnacle", "_average", "_maximum", "Bet365", "Betfair Exchange"}
)
