"""Tests for the style-of-play features.

The leakage tests are the important ones. A feature that has seen its own match
will look brilliant in a backtest and lose money in production, and it fails
silently: nothing raises, the log-loss simply improves for the wrong reason. So
the properties asserted here are that a match's features depend on the past and
only on the past, and that changing the future cannot change them.
"""

from __future__ import annotations

from datetime import date, timedelta
from math import log

from footy.models import style


def pair(match_id, day, home=1, away=2, home_ppda=10.0, away_ppda=10.0,
         home_deep=6.0, away_deep=6.0):
    """Both sides of one synthetic match."""
    kickoff = date(2024, 1, 1) + timedelta(days=day)
    return [
        style.TeamMatch(match_id, kickoff, home, away, home_ppda, home_deep),
        style.TeamMatch(match_id, kickoff, away, home, away_ppda, away_deep),
    ]


def run(n, **kwargs):
    rows = []
    for i in range(n):
        rows += pair(i + 1, i * 7, **kwargs)
    return rows


def test_a_team_needs_history_before_it_has_a_style():
    """Below the minimum, inventing a number would be a default dressed up as a
    measurement."""
    assert style.build(run(style.MIN_MATCHES - 1)) == {}
    assert style.build(run(style.MIN_MATCHES + 1))


def test_pressing_is_the_negative_log_of_ppda():
    built = style.build(run(style.MIN_MATCHES + 1, home_ppda=8.0))
    features = built[(style.MIN_MATCHES + 1, 1)]
    assert features["press"] == log(1 / 8.0)


def test_deep_completions_are_split_into_created_and_conceded():
    built = style.build(
        run(style.MIN_MATCHES + 1, home_deep=9.0, away_deep=3.0)
    )
    home = built[(style.MIN_MATCHES + 1, 1)]
    away = built[(style.MIN_MATCHES + 1, 2)]
    assert (home["deep_for"], home["deep_against"]) == (9.0, 3.0)
    assert (away["deep_for"], away["deep_against"]) == (3.0, 9.0)


def test_an_unchanged_style_has_no_shift():
    """The delta is recent form against the team's own baseline, so a side that
    plays the same way every week must score zero however it plays."""
    built = style.build(run(style.WINDOW + 2, home_ppda=6.0, home_deep=11.0))
    features = built[(style.WINDOW + 2, 1)]
    assert features["press_delta"] == 0.0
    assert features["deep_for_delta"] == 0.0


def test_a_change_of_style_shows_up_as_a_shift():
    """A side that abruptly starts pressing should register a positive shift,
    and it should fade as the new way of playing becomes the baseline."""
    rows = run(style.WINDOW, home_ppda=20.0)
    for i in range(style.WINDOW, style.WINDOW * 2):
        rows += pair(i + 1, i * 7, home_ppda=5.0)

    built = style.build(rows)
    just_after = built[(style.WINDOW + 3, 1)]["press_delta"]
    long_after = built[(style.WINDOW * 2, 1)]["press_delta"]
    assert just_after > 0
    assert long_after < just_after


def test_features_cannot_see_their_own_match():
    """The last match is played at a wildly different tempo. Its own features
    must be blind to that, and the previous match's features must be too."""
    rows = run(style.MIN_MATCHES + 1)
    last = style.MIN_MATCHES + 1
    rows += pair(last + 1, (last + 1) * 7, home_ppda=40.0, home_deep=25.0)

    built = style.build(rows)
    settled = built[(last, 1)]
    assert built[(last + 1, 1)] == settled


def test_features_cannot_see_the_future():
    """Rebuilding with extra matches appended must not disturb the features of
    any match that came before them."""
    played = run(style.MIN_MATCHES + 3)
    future = [
        row
        for i in range(style.MIN_MATCHES + 3, style.MIN_MATCHES + 9)
        for row in pair(i + 1, i * 7, home_ppda=45.0, home_deep=30.0)
    ]

    early = style.build(played)
    late = style.build(played + future)
    for key, features in early.items():
        assert late[key] == features


def test_the_window_forgets():
    """A team that pressed hard long ago and stopped should look passive once the
    old matches fall out of the window."""
    rows = run(style.WINDOW, home_ppda=4.0)
    for i in range(style.WINDOW, style.WINDOW * 2 + 1):
        rows += pair(i + 1, i * 7, home_ppda=25.0)

    built = style.build(rows)
    # Featurised when every match in the window was still the pressing side.
    pressing = built[(style.WINDOW + 1, 1)]["press"]
    # Featurised one match after the last of those fell out of it.
    settled = built[(style.WINDOW * 2 + 1, 1)]["press"]
    assert pressing == log(1 / 4.0)
    assert abs(settled - log(1 / 25.0)) < 1e-9


def test_a_missing_figure_is_skipped_rather_than_guessed():
    """Deep completions conceded are the opponent's figure, so one side's gap
    costs both sides the match rather than filling it in with an average."""
    rows = run(style.MIN_MATCHES + 2)
    rows[0] = style.TeamMatch(1, rows[0].kickoff, 1, 2, None, None)

    built = style.build(rows)
    complete = style.build(run(style.MIN_MATCHES + 2))
    first = style.MIN_MATCHES + 1
    assert (first, 1) in complete and (first, 2) in complete
    assert (first, 1) not in built and (first, 2) not in built
    assert (first + 1, 1) in built and (first + 1, 2) in built
