from __future__ import annotations

import os
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
FOOTBALL_DATA_DIVISIONS: dict[str, str] = {
    "ENG-PL": "E0",
    "ESP-LL": "SP1",
    "ITA-SA": "I1",
    "GER-BL": "D1",
    "FRA-L1": "F1",
}

# Seasons by starting year. 2014 is the earliest season Understat publishes xG for,
# so the history window matches the availability of the strongest feature.
SEASON_START_YEARS: list[int] = list(range(2014, 2026))


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
