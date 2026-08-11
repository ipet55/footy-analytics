"""FBref match sheets: who started, who came on, and what each of them did.

FBref publishes one page per match containing both the team sheet and per-player
match statistics. soccerdata fetches that page through a real browser and caches
the HTML, so the two readers we use cost one request between them, and a re-run
costs none.

Rate limiting is not negotiable here. Sports Reference asks for no more than ten
requests a minute and soccerdata defaults to one every seven seconds, which is
already at that limit. It is not raised. A full Premier League season is 380
pages, so roughly seventy minutes, and the loader is written to resume rather
than to be run in one sitting.

Season labels are FBref's own: "2425" means 2024-25, which we store as
start_year 2024. Note that FBref currently serves the 2026-27 page for the
2025-2026 URL, so that season is unavailable through this path and the mapping
below stops at 2024.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import date

import pandas as pd

SOURCE_CODE = "fbref"

# soccerdata's league keys, mapped to ours.
LEAGUE_KEYS = {
    "ENG-PL": "ENG-Premier League",
    "ESP-LL": "ESP-La Liga",
    "GER-BL": "GER-Bundesliga",
    "ITA-SA": "ITA-Serie A",
    "FRA-L1": "FRA-Ligue 1",
}


def season_label(start_year: int) -> str:
    """2024 -> '2425', the label FBref uses for the 2024-25 season."""
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


# Per-player counting stats on the match page, mapped to our column names. The
# keys are the flattened two-level headers soccerdata produces.
STAT_MAP = {
    ("Performance", "Gls"): "goals",
    ("Performance", "Ast"): "assists",
    ("Performance", "Sh"): "shots",
    ("Performance", "SoT"): "shots_on_target",
    ("Performance", "PK"): "penalties_scored",
    ("Performance", "PKatt"): "penalties_attempted",
    ("Performance", "CrdY"): "yellows",
    ("Performance", "CrdR"): "reds",
    ("Performance", "Fls"): "fouls_committed",
    ("Performance", "Fld"): "fouls_drawn",
    ("Performance", "TklW"): "tackles_won",
    ("Performance", "Int"): "interceptions",
    ("Performance", "Crs"): "crosses",
    ("Performance", "Off"): "offsides",
    ("Performance", "OG"): "own_goals",
}


@dataclass(frozen=True)
class ScheduledMatch:
    """A fixture as FBref lists it, before it is linked to one of ours."""

    game_id: str
    kickoff_date: date
    home_name: str
    away_name: str
    referee: str | None = None


@dataclass(frozen=True)
class Appearance:
    """One player in one match. Counting stats are None for an unused
    substitute, which is not the same as zero and must not be stored as it."""

    team_name: str
    player_name: str
    is_starter: bool
    position: str | None
    shirt_number: int | None
    minutes: int
    stats: dict[str, int | None]


def reader(competition_code: str, start_year: int):
    """A soccerdata FBref reader for one competition-season.

    One season per reader, deliberately. Asking for several at once made the
    schedule for one of them come back holding another's fixtures.
    """
    import soccerdata as sd

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return sd.FBref(
            leagues=LEAGUE_KEYS[competition_code], seasons=[season_label(start_year)]
        )


def schedule(fb) -> list[ScheduledMatch]:
    """Every match of the season that has been played.

    A missing game_id means the fixture has no match page yet, which is how
    unplayed fixtures appear.

    The schedule also names the referee, at full coverage back to 2014-15. That
    is one request per season for something football-data.co.uk publishes only
    for England.
    """
    df = fb.read_schedule().reset_index()
    has_referee = "referee" in df.columns
    out = []
    for row in df.itertuples():
        if not isinstance(row.game_id, str) or pd.isna(row.date):
            continue
        referee = getattr(row, "referee", None) if has_referee else None
        out.append(
            ScheduledMatch(
                game_id=row.game_id,
                kickoff_date=row.date.date(),
                home_name=str(row.home_team),
                away_name=str(row.away_team),
                referee=(
                    str(referee).strip()
                    if referee is not None and not pd.isna(referee) and str(referee).strip()
                    else None
                ),
            )
        )
    return out


def _flatten(columns) -> list:
    return [
        tuple(str(x) for x in c if x and not str(x).startswith("Unnamed"))
        if isinstance(c, tuple)
        else (str(c),)
        for c in columns
    ]


def _as_int(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def sheets(fb, game_ids: list[str]) -> dict[str, list[Appearance]]:
    """Team sheets for a batch of matches, keyed by FBref game id.

    The lineup is the source of truth for who was in the squad, because it
    includes unused substitutes that the statistics table omits. Statistics are
    joined onto it where they exist.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lineups = fb.read_lineup(match_id=game_ids).reset_index()
        stats = fb.read_player_match_stats(
            stat_type="summary", match_id=game_ids
        ).reset_index()

    stats.columns = ["/".join(c) for c in _flatten(stats.columns)]
    stats = stats.rename(
        columns={"/".join(k): v for k, v in STAT_MAP.items()}
    )

    by_player: dict[tuple[str, str, str], dict] = {}
    # The statistics table carries both the match label and the match id; the
    # lineup table carries only the label, so this is also the bridge between them.
    label_to_id: dict[str, str] = {}
    for row in stats.to_dict("records"):
        gid = row.get("game_id")
        if not isinstance(gid, str):
            continue
        label_to_id[str(row.get("game"))] = gid
        by_player[(gid, str(row.get("team")), str(row.get("player")))] = row

    out: dict[str, list[Appearance]] = {gid: [] for gid in game_ids}
    for row in lineups.to_dict("records"):
        gid = label_to_id.get(str(row.get("game")))
        if gid is None:
            continue
        team, player = str(row["team"]), str(row["player"])
        s = by_player.get((gid, team, player), {})
        out[gid].append(
            Appearance(
                team_name=team,
                player_name=player,
                is_starter=bool(row["is_starter"]),
                position=(str(row["position"]) if row.get("position") else None),
                shirt_number=_as_int(row.get("jersey_number")),
                minutes=_as_int(row.get("minutes_played")) or 0,
                stats={col: _as_int(s.get(col)) for col in STAT_MAP.values()}
                if s
                else dict.fromkeys(STAT_MAP.values()),
            )
        )
    return out


def sheets_where_possible(
    fb, game_ids: list[str], cool_off: int = 120
) -> tuple[dict[str, list[Appearance]], list[str]]:
    """Fetch a batch, giving up on individual matches rather than on the league.

    soccerdata already retries a page five times before raising, so a failure
    here means a CAPTCHA or a block rather than a blip. The batch is then retried
    one match at a time, because the usual cause is a single bad page and the
    other nine are fine — and one unreadable page previously cost the remaining
    1,770 matches of a league.

    Skipped matches are simply not stored, so `core.lineup_coverage` still
    describes exactly what landed and a later re-run picks them up.
    """
    import time

    try:
        return sheets(fb, game_ids), []
    except Exception:
        pass

    # Whatever blocked the batch is unlikely to clear instantly.
    time.sleep(cool_off)

    out: dict[str, list[Appearance]] = {}
    failed: list[str] = []
    for game_id in game_ids:
        try:
            out.update(sheets(fb, [game_id]))
        except Exception:
            failed.append(game_id)
    return out, failed
