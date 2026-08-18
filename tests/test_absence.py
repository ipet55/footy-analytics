"""The absence prior: whose unavailability is allowed to move a rate.

These tests do not touch the database. They pin the arithmetic so a later
change to the weights cannot silently invent a 40% swing, and so a fringe
squad player cannot be treated as a star.
"""

import pytest

from footy.models.absence import Missing, shock_from_missing


def _player(**kwargs) -> Missing:
    defaults = dict(
        player_id=1,
        player_name="X",
        status="out",
        position="F",
        goal_share=0.0,
        minute_share=0.0,
    )
    defaults.update(kwargs)
    return Missing(**defaults)


def test_a_star_striker_cuts_the_attack_and_leaves_defence_alone():
    """A regular who scores a fifth of the team's goals is the case this
    exists for. The cut is half of that share, not the share itself: the
    replacement still plays."""
    shock = shock_from_missing(1, [_player(goal_share=0.20, minute_share=0.12)])
    assert shock.attack_factor == 1.0 - (0.20 * 0.50 + 0.12 * 0.15)
    assert shock.defence_factor == 1.0
    assert shock.missing_key == 1


def test_a_starting_goalkeeper_raises_what_the_team_concedes():
    shock = shock_from_missing(1, [_player(position="G", minute_share=0.35)])
    assert shock.attack_factor == 1.0
    assert shock.defence_factor == 1.0 + 0.35 * 0.35


def test_a_doubtful_player_counts_at_forty_percent():
    out = shock_from_missing(1, [_player(goal_share=0.20, status="out")])
    doubt = shock_from_missing(1, [_player(goal_share=0.20, status="doubtful")])
    assert 1.0 - doubt.attack_factor == pytest.approx(
        (1.0 - out.attack_factor) * 0.40
    )


def test_a_fringe_squad_player_is_not_key():
    """Two percent of minutes and no goals is a rotation name. The concede
    rate moves by a fraction of a percent, which is not a reason to put
    his name on the page."""
    shock = shock_from_missing(1, [_player(position="D", minute_share=0.02)])
    assert shock.missing_key == 0
    assert shock.attack_factor == 1.0
    assert shock.defence_factor < 1.01


def test_six_injuries_cannot_invent_a_different_club():
    """The cap is the whole point of having one. Without it a long list of
    regulars would drive the attack rate toward zero, which is not what
    happens when the replacements exist."""
    missing = [
        _player(player_id=i, goal_share=0.15, minute_share=0.20, player_name=str(i))
        for i in range(6)
    ]
    shock = shock_from_missing(1, missing)
    assert shock.attack_factor == 0.75
    assert shock.defence_factor == 1.0


def test_identity_when_nobody_is_missing():
    shock = shock_from_missing(1, [])
    assert shock.attack_factor == 1.0
    assert shock.defence_factor == 1.0
    assert not shock.moves()
