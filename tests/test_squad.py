"""Tests for the squad-strength features.

The leakage tests are the important ones. A feature that has seen its own match
will look brilliant in a backtest and lose money in production, and it fails
silently: nothing raises, the log-loss simply improves for the wrong reason. So
the properties asserted here are that a match's features depend on the past and
only on the past, and that changing the future cannot change them.
"""

from __future__ import annotations

from datetime import date, timedelta

from footy.models import squad


def sheet(match_id, day, team_id, player_ids, goals=None, minutes=90):
    """One team's eleven, all starters, for a synthetic match."""
    goals = goals or {}
    return [
        squad.Appearance(
            match_id=match_id,
            kickoff=date(2024, 1, 1) + timedelta(days=day),
            team_id=team_id,
            player_id=p,
            is_starter=True,
            minutes=minutes,
            goals=goals.get(p, 0),
            assists=0,
        )
        for p in player_ids
    ]


def season(n_matches=20, team_a=1, team_b=2, squad_a=None, squad_b=None):
    """A synthetic run of matches between two unchanged sides."""
    squad_a = squad_a or list(range(100, 111))
    squad_b = squad_b or list(range(200, 211))
    out = []
    for i in range(n_matches):
        out += sheet(i + 1, i * 7, team_a, squad_a)
        out += sheet(i + 1, i * 7, team_b, squad_b)
    return out


def test_the_first_match_has_no_features():
    """Nothing is known before the first sheet, and inventing a number there
    would be a quiet default rather than a measurement."""
    built = squad.build(season(n_matches=1))
    assert built == {}


def test_an_unchanged_side_scores_full_continuity():
    built = squad.build(season(n_matches=12))
    last = max(m for m, _ in built)
    row = built[(last, 1)]
    assert row["xi_continuity"] == 1.0
    assert row["xi_regulars"] == 11.0
    assert row["key_players_absent"] == 0.0


def test_a_wholly_changed_side_scores_zero_continuity():
    """Eleven players who have never appeared must not look like regulars."""
    apps = season(n_matches=12)
    reserves = list(range(300, 311))
    apps += sheet(99, 200, 1, reserves)
    apps += sheet(99, 200, 2, list(range(200, 211)))
    built = squad.build(apps)
    row = built[(99, 1)]
    assert row["xi_continuity"] == 0.0
    assert row["xi_regulars"] == 0.0
    # Every one of the regular eleven is missing from the sheet.
    assert row["key_players_absent"] == 11.0


def test_resting_three_regulars_is_counted():
    apps = season(n_matches=12)
    rotated = list(range(100, 108)) + [301, 302, 303]
    apps += sheet(99, 200, 1, rotated)
    apps += sheet(99, 200, 2, list(range(200, 211)))
    row = squad.build(apps)[(99, 1)]
    assert row["key_players_absent"] == 3.0
    assert row["xi_regulars"] == 8.0


def test_features_cannot_see_their_own_match():
    """The decisive one. A player who scores five in this match must not look
    like a goalscorer to this match's own feature."""
    quiet = season(n_matches=12)
    explosive = [
        squad.Appearance(a.match_id, a.kickoff, a.team_id, a.player_id,
                         a.is_starter, a.minutes,
                         goals=5 if (a.match_id == 12 and a.player_id == 100) else 0,
                         assists=0)
        for a in quiet
    ]
    assert squad.build(quiet)[(12, 1)] == squad.build(explosive)[(12, 1)]


def test_features_cannot_see_the_future():
    """Appending later matches must leave earlier features untouched."""
    short = squad.build(season(n_matches=8))
    long = squad.build(season(n_matches=20))
    for key, row in short.items():
        assert long[key] == row, f"{key} changed once later matches were added"


def test_goal_threat_reflects_history_not_the_present():
    """A striker's rating must come from what he did before today."""
    scorer = {100: 1}
    apps = []
    for i in range(12):
        apps += sheet(i + 1, i * 7, 1, list(range(100, 111)), goals=scorer)
        apps += sheet(i + 1, i * 7, 2, list(range(200, 211)))
    built = squad.build(apps)
    # Team 1 has a player scoring every match; team 2 has none.
    assert built[(12, 1)]["xi_goal_threat"] > built[(12, 2)]["xi_goal_threat"]
    # One goal per match from one of eleven starters, averaged over the eleven.
    assert built[(12, 1)]["xi_goal_threat"] == 1.0 / 11
    assert built[(12, 2)]["xi_goal_threat"] == 0.0


def test_experience_counts_only_prior_appearances():
    built = squad.build(season(n_matches=6))
    # Before match 6 each player has played the five that came before it.
    assert built[(6, 1)]["xi_experience"] == 5.0
