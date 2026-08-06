"""football-data.co.uk: historical results, match stats and bookmaker odds.

Free CSV archive covering 22 divisions back to 1993. This is the historical
backbone: it supplies results, shots, corners, fouls and cards, plus opening
and closing odds from up to 20 bookmakers. It has no possession, passes or xG —
those arrive later from Understat and FBref.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

from footy.config import (
    FOOTBALL_DATA_DIVISIONS,
    RAW_DIR,
    SEASON_START_YEARS,
    season_code,
)

SOURCE_CODE = "football_data_uk"
BASE_URL = "https://www.football-data.co.uk/mmz4281"
USER_AGENT = "footy-analytics/0.1 (research; contact via repo)"


@dataclass(frozen=True)
class CsvFile:
    competition_code: str
    division: str
    start_year: int
    path: Path

    @property
    def url(self) -> str:
        return f"{BASE_URL}/{season_code(self.start_year)}/{self.division}.csv"


def target_files() -> list[CsvFile]:
    files = []
    for comp_code, division in FOOTBALL_DATA_DIVISIONS.items():
        for year in SEASON_START_YEARS:
            path = RAW_DIR / SOURCE_CODE / season_code(year) / f"{division}.csv"
            files.append(CsvFile(comp_code, division, year, path))
    return files


def download(files: list[CsvFile], force: bool = False, timeout: int = 60) -> list[tuple[CsvFile, str]]:
    """Download CSVs to disk. Returns (file, status) where status is
    'cached', 'downloaded', 'unchanged' or an error string.
    """
    results: list[tuple[CsvFile, str]] = []
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    for f in files:
        if f.path.exists() and not force:
            results.append((f, "cached"))
            continue
        try:
            resp = session.get(f.url, timeout=timeout)
            resp.raise_for_status()
            body = resp.content
            if not body.strip():
                results.append((f, "error: empty response"))
                continue
            f.path.parent.mkdir(parents=True, exist_ok=True)
            previous = f.path.read_bytes() if f.path.exists() else None
            f.path.write_bytes(body)
            results.append((f, "unchanged" if previous == body else "downloaded"))
        except requests.RequestException as exc:
            results.append((f, f"error: {exc}"))
    return results


def content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> pd.DataFrame:
    """Read one season CSV defensively.

    These files have real-world defects: trailing all-empty columns, blank
    padding rows at the bottom, and mixed encodings (Latin-1 in older files).
    """
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(path, encoding=encoding, low_memory=False)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Could not decode {path}")

    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]
    # A row without both team names is padding, not a match.
    if {"HomeTeam", "AwayTeam"} <= set(df.columns):
        df = df.dropna(subset=["HomeTeam", "AwayTeam"])
        df = df[(df["HomeTeam"].astype(str).str.strip() != "") & (df["AwayTeam"].astype(str).str.strip() != "")]
    return df.reset_index(drop=True)


def parse_date(value: object) -> date | None:
    """Dates are dd/mm/yy in older files and dd/mm/yyyy in newer ones."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()
