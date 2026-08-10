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


def sheet(match_id, day, team_id, player_ids, goals=None, minutes=90,
          bench=(), reds=()):
    """One team's eleven, all starters, for a synthetic match.

    Bench players are named but unused, which is what separates a rested player
    from an unavailable one.
    """
    goals = goals or {}

    def app(p, starter):
        return squad.Appearance(
            match_id=match_id,
            kickoff=date(2024, 1, 1) + timedelta(days=day),
            team_id=team_id,
            player_id=p,
            is_starter=starter,
            minutes=minutes if starter else 0,
            goals=goals.get(p, 0),
            assists=0,
            reds=1 if p in reds else 0,
        )

    return [app(p, True) for p in player_ids] + [app(p, False) for p in bench]


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


def rotating(n_matches=12, pool=None, dropped=None, reds_in=None, in_squad=True):
    """A side that rotates two players out per match, so a squad rather than an
    eleven accumulates minutes.

    dropped maps a match number to players who do not play in it. in_squad says
    whether they sit on the bench or vanish from the team sheet. That switch is
    the control the availability tests need: either way the player loses the
    same minutes, so any difference between them is the absence itself.
    """
    pool = pool or list(range(100, 113))
    dropped, reds_in = dropped or {}, reds_in or {}
    apps = []
    for i in range(n_matches):
        m = i + 1
        rested = {pool[(2 * i) % len(pool)], pool[(2 * i + 1) % len(pool)]}
        out = set(dropped.get(m, ()))
        starters = [p for p in pool if p not in rested and p not in out][:11]
        bench = [p for p in pool if p not in starters and (p not in out or in_squad)]
        apps += sheet(m, i * 7, 1, starters, bench=bench, reds=reds_in.get(m, ()))
        apps += sheet(m, i * 7, 2, list(range(200, 211)))
    return apps


def test_the_forecast_cannot_see_the_eleven_it_is_predicting():
    """The decisive test for the servable feature. Whoever actually walks out
    for this match must not change what we would have predicted for it."""
    played = season(n_matches=12)
    upset = [a for a in played if not (a.match_id == 12 and a.team_id == 1)]
    upset += sheet(12, 77, 1, list(range(300, 311)))

    normal = squad.build(played)[(12, 1)]
    shuffled = squad.build(upset)[(12, 1)]

    assert shuffled["xi_continuity_forecast"] == normal["xi_continuity_forecast"]
    # And the actual measure does move, so the test is not vacuous.
    assert shuffled["xi_continuity"] != normal["xi_continuity"]


def test_a_sending_off_weakens_the_next_match_forecast():
    """A red card is a suspension we know about before kickoff, so the eleven we
    predict should fall back on someone less established."""
    clean = squad.build(rotating())[(12, 1)]
    suspended = squad.build(rotating(reds_in={11: (100,)}))[(12, 1)]
    assert suspended["xi_continuity_forecast"] < clean["xi_continuity_forecast"]


def settled_side(n_matches=12, dropped=None, in_squad=True):
    """Ten ever-presents plus three players competing for the last shirt.

    The absence tests need a first-choice player who is still among the eleven
    most-used even after missing a couple of matches. Under even rotation he is
    not, so skipping him changes nothing and the test would pass whatever the
    availability rule did.
    """
    core, fringe = list(range(100, 110)), [110, 111, 112]
    dropped = dropped or {}
    apps = []
    for i in range(n_matches):
        m = i + 1
        out = set(dropped.get(m, ()))
        starters = [p for p in core if p not in out]
        rotating_in = [p for p in fringe if p not in out]
        starters += rotating_in[i % len(rotating_in):][:11 - len(starters)]
        starters = (starters + [p for p in fringe if p not in starters and p not in out])[:11]
        bench = [p for p in core + fringe
                 if p not in starters and (p not in out or in_squad)]
        apps += sheet(m, i * 7, 1, starters, bench=bench)
        apps += sheet(m, i * 7, 2, list(range(200, 211)))
    return apps


def test_a_regular_missing_from_recent_squads_is_presumed_unavailable():
    """Dropping out of the squad entirely, rather than being rested on the
    bench, is the only injury signal available without an injury feed.

    Both sides of this comparison lose the same two matches of minutes, so the
    gap between them is the absence and nothing else.
    """
    out = {10: (100,), 11: (100,)}
    benched = squad.build(settled_side(dropped=out, in_squad=True))[(12, 1)]
    vanished = squad.build(settled_side(dropped=out, in_squad=False))[(12, 1)]
    assert vanished["xi_continuity_forecast"] < benched["xi_continuity_forecast"]


def test_one_match_out_is_not_yet_treated_as_an_injury():
    """Missing a single match is ordinary rotation. Reading it as absence would
    fire the feature on half the league every week."""
    out = {11: (100,)}
    benched = squad.build(settled_side(dropped=out, in_squad=True))[(12, 1)]
    vanished = squad.build(settled_side(dropped=out, in_squad=False))[(12, 1)]
    assert vanished["xi_continuity_forecast"] == benched["xi_continuity_forecast"]
