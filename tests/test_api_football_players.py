"""Parse API-Football /players rows into season totals."""

from footy.sources.api_football import player_seasons_from_row


GAKPO = {
    "player": {
        "id": 247,
        "name": "C. Gakpo",
        "photo": "https://media.api-sports.io/football/players/247.png",
    },
    "statistics": [
        {
            "team": {"id": 40, "name": "Liverpool"},
            "league": {"id": 39, "name": "Premier League", "season": 2025},
            "games": {
                "appearences": 36,
                "lineups": 32,
                "minutes": 2765,
            },
            "shots": {"total": 54, "on": 21},
            "goals": {"total": 7, "conceded": 0, "assists": 5, "saves": None},
            "tackles": {"total": 28, "blocks": 4, "interceptions": 13},
            "fouls": {"drawn": 44, "committed": 42},
            "cards": {"yellow": 3, "yellowred": 0, "red": 0},
        }
    ],
}


def test_player_seasons_from_row_reads_the_misspelled_fields():
    rows = player_seasons_from_row(GAKPO, league_id=39, season=2025)
    assert len(rows) == 1
    row = rows[0]
    assert row.player_id == 247
    assert row.team_id == 40
    assert row.appearances == 36
    assert row.starts == 32
    assert row.minutes == 2765
    assert row.goals == 7
    assert row.assists == 5
    assert row.shots == 54
    assert row.shots_on_target == 21
    assert row.tackles == 28
    assert row.interceptions == 13
    assert row.fouls == 42
    assert row.yellows == 3
    assert row.reds == 0


def test_player_seasons_from_row_treats_null_assists_as_zero():
    row = {
        "player": {"id": 1, "name": "A. Keeper"},
        "statistics": [
            {
                "team": {"id": 40},
                "league": {"id": 39, "season": 2025},
                "games": {"appearences": 10, "lineups": 10, "minutes": 900},
                "shots": {"total": None, "on": None},
                "goals": {"total": 0, "assists": None},
                "tackles": {"total": None, "interceptions": None},
                "fouls": {"committed": None},
                "cards": {"yellow": None, "yellowred": 1, "red": 0},
            }
        ],
    }
    parsed = player_seasons_from_row(row, 39, 2025)[0]
    assert parsed.assists == 0
    assert parsed.shots is None
    assert parsed.reds == 1


def test_player_seasons_from_row_skips_other_leagues_and_unused_players():
    row = {
        "player": {"id": 2, "name": "On Loan"},
        "statistics": [
            {
                "team": {"id": 50},
                "league": {"id": 2, "season": 2025},
                "games": {"appearences": 4, "lineups": 4, "minutes": 360},
                "shots": {},
                "goals": {},
                "tackles": {},
                "fouls": {},
                "cards": {},
            },
            {
                "team": {"id": 40},
                "league": {"id": 39, "season": 2025},
                "games": {"appearences": 0, "lineups": 0, "minutes": 0},
                "shots": {},
                "goals": {},
                "tackles": {},
                "fouls": {},
                "cards": {},
            },
        ],
    }
    assert player_seasons_from_row(row, 39, 2025) == []
