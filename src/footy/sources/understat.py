"""Understat: expected goals and pressing metrics, 2014/15 onward.

Scraped rather than licensed, so research and model training only. xG is the
single most predictive feature available for free — it is substantially better
than goals scored at forecasting future results, because goals are a small,
noisy sample of the chances a team actually created.

Every metric here maps onto a column that already exists in core.match_team_stat,
so this enriches existing rows rather than adding any.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from footy.config import SEASON_START_YEARS, season_code

SOURCE_CODE = "understat"

# core.competition.code -> soccerdata's Understat league name
LEAGUES: dict[str, str] = {
    "ENG-PL": "ENG-Premier League",
    "ESP-LL": "ESP-La Liga",
    "ITA-SA": "ITA-Serie A",
    "GER-BL": "GER-Bundesliga",
    "FRA-L1": "FRA-Ligue 1",
}

# Understat column suffix -> core.match_team_stat column
STAT_MAP: dict[str, str] = {
    "xg": "xg",
    "np_xg": "npxg",
    "ppda": "ppda",
    "deep_completions": "deep_completions",
    "expected_points": "expected_points",
}


@dataclass
class UnderstatSeason:
    competition_code: str
    start_year: int
    matches: list[dict] = field(default_factory=list)
    team_stats: list[dict] = field(default_factory=list)


def _clean(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return None
    except (TypeError, ValueError):
        return None
    return float(value)


def fetch_season(competition_code: str, start_year: int) -> UnderstatSeason:
    import soccerdata as sd

    # Use the four-digit YYYY form ("2122"), never the plain start year. soccerdata
    # reads "2021" as the range 20-21 because those halves are consecutive, and so
    # silently returns 2020/21 instead of 2021/22.
    scraper = sd.Understat(
        leagues=[LEAGUES[competition_code]], seasons=[season_code(start_year)]
    )
    df = scraper.read_team_match_stats().reset_index()

    returned = int(df["season_id"].iloc[0])
    if returned != start_year:
        raise RuntimeError(
            f"Understat returned season {returned} when {start_year} was requested "
            f"for {competition_code}."
        )

    out = UnderstatSeason(competition_code, start_year)
    for _, row in df.iterrows():
        # Fixtures that have not been played yet carry no usable metrics.
        if pd.isna(row.get("home_goals")) or pd.isna(row.get("away_goals")):
            continue

        row_id = len(out.matches)
        kickoff = pd.to_datetime(row["date"], errors="coerce")
        out.matches.append(
            {
                "row_id": row_id,
                "competition_code": competition_code,
                "start_year": start_year,
                "kickoff_date": None if pd.isna(kickoff) else kickoff.date().isoformat(),
                "home_name": str(row["home_team"]).strip(),
                "away_name": str(row["away_team"]).strip(),
                "home_goals": int(row["home_goals"]),
                "away_goals": int(row["away_goals"]),
                "source_match_id": str(row["game_id"]),
                "source_url": f"https://understat.com/match/{row['game_id']}",
            }
        )
        for is_home, prefix in ((True, "home"), (False, "away")):
            stats = {"row_id": row_id, "is_home": is_home, "period": "FT"}
            for suffix, column in STAT_MAP.items():
                stats[column] = _clean(row.get(f"{prefix}_{suffix}"))
            out.team_stats.append(stats)
    return out


def fetch_all(
    competitions: list[str] | None = None, seasons: list[int] | None = None
) -> list[UnderstatSeason]:
    comps = competitions or list(LEAGUES)
    years = seasons or SEASON_START_YEARS
    return [fetch_season(c, y) for c in comps for y in years]


def distinct_team_names(seasons: list[UnderstatSeason]) -> set[str]:
    names: set[str] = set()
    for season in seasons:
        for match in season.matches:
            names.add(match["home_name"])
            names.add(match["away_name"])
    return names
