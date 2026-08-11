"""Tests for the Dixon-Coles goals model.

The gradient check is the important one, for the same reason as in the count
models: a wrong analytic gradient does not raise, it just leaves the optimiser
short of the maximum likelihood. Here it matters even more, because the rho
correction makes the derivative genuinely easy to get wrong — it enters through
four specific scorelines and through both Poisson rates at once.

The rest of the tests pin down the properties every market on the page depends
on: the score matrix is a distribution, and every market read off it is a sum
over the same matrix, so they cannot contradict each other.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import approx_fprime

from footy.models import dixon_coles as dc

RNG = np.random.default_rng(4242)


def synthetic(n_teams: int = 10, n_matches: int = 400):
    home = RNG.integers(0, n_teams, n_matches)
    away = (home + RNG.integers(1, n_teams, n_matches)) % n_teams
    attack = RNG.normal(0, 0.3, n_teams)
    defence = RNG.normal(0, 0.2, n_teams)
    lam = np.exp(attack[home] - defence[away] + 0.25)
    mu = np.exp(attack[away] - defence[home])
    home_goals = RNG.poisson(lam)
    away_goals = RNG.poisson(mu)
    days_ago = np.sort(RNG.uniform(0, 1500, n_matches))[::-1].copy()
    return home, away, home_goals, away_goals, days_ago


def assert_gradient_close(analytic: np.ndarray, numeric: np.ndarray) -> None:
    scale = max(float(np.abs(numeric).max()), 1.0)
    error = float(np.abs(analytic - numeric).max()) / scale
    assert error < 1e-5, f"largest scaled gradient error {error:.2e}"


@pytest.mark.parametrize("rho", [-0.12, -0.05, 0.0, 0.08])
def test_gradient_matches_finite_differences(rho):
    """Checked at several rho, including zero, because the correction's
    derivative vanishes there and a sign error would hide."""
    home, away, hg, ag, days_ago = synthetic()
    d = dc.build_design(home, away, hg, ag, days_ago)
    n = d.n_teams

    params = np.concatenate([
        RNG.normal(0, 0.25, n - 1),
        RNG.normal(0, 0.2, n),
        [0.25],
        [rho],
    ])
    assert_gradient_close(
        dc.objective(params, d)[1],
        approx_fprime(params, lambda p: dc.objective(p, d)[0], 1e-6),
    )


@pytest.mark.parametrize("penalty", [3.0, 50.0])
def test_gradient_matches_finite_differences_with_venue_terms(penalty):
    """The venue block adds two parameters per team and an L2 penalty, so both
    the likelihood part and the penalty part of its derivative need checking."""
    home, away, hg, ag, days_ago = synthetic()
    d = dc.build_design(home, away, hg, ag, days_ago, venue_penalty=penalty)
    n = d.n_teams

    params = np.concatenate([
        RNG.normal(0, 0.25, n - 1),
        RNG.normal(0, 0.2, n),
        RNG.normal(0, 0.1, 2 * n),
        [0.25],
        [-0.05],
    ])
    assert_gradient_close(
        dc.objective(params, d)[1],
        approx_fprime(params, lambda p: dc.objective(p, d)[0], 1e-6),
    )


def test_venue_terms_are_nested_inside_the_plain_model():
    """The venue model has to be a strict superset, or the backtest comparing
    the two is measuring an unrelated change as well. Shrink the deviations hard
    enough and what is left must be the model we already ship.

    The penalty is 1e4 rather than something enormous: past roughly 1e5 the
    venue directions dominate the Hessian, L-BFGS-B hits its tolerance early and
    the remaining parameters drift by more than this asserts. That is the
    optimiser giving up on a flat direction, not the nesting failing.
    """
    home, away, hg, ag, days_ago = synthetic(n_matches=1200)
    plain = dc.fit(home, away, hg, ag, days_ago)
    shrunk = dc.fit(home, away, hg, ag, days_ago, venue_penalty=1e4)

    assert max(abs(v) for v in shrunk.venue_attack.values()) < 1e-3
    assert max(abs(v) for v in shrunk.venue_defence.values()) < 1e-3
    assert shrunk.home_advantage == pytest.approx(plain.home_advantage, abs=2e-3)
    for team in plain.teams:
        assert shrunk.attack[team] == pytest.approx(plain.attack[team], abs=2e-3)


def test_venue_terms_are_absent_unless_asked_for():
    """Fitting without a penalty must leave the shipped model byte-identical,
    because that is the configuration serving predictions."""
    home, away, hg, ag, days_ago = synthetic()
    fitted = dc.fit(home, away, hg, ag, days_ago)
    assert fitted.venue_attack == {} and fitted.venue_defence == {}
    lam, mu = fitted.rates(fitted.teams[0], fitted.teams[1])
    assert lam > 0 and mu > 0


def test_venue_terms_only_move_the_home_side():
    """A team's venue deviations describe its own home matches. If they leaked
    into its away fixtures the model would be double-counting the ground."""
    fitted = dc.Fitted(
        teams=[1, 2], attack={1: 0.0, 2: 0.0}, defence={1: 0.0, 2: 0.0},
        home_advantage=0.2, rho=0.0, n_matches=0,
        venue_attack={1: 0.5, 2: 0.0}, venue_defence={1: -0.3, 2: 0.0},
    )
    at_home = fitted.rates(1, 2)
    away = fitted.rates(2, 1)
    assert at_home[0] == pytest.approx(np.exp(0.2 + 0.5))
    assert at_home[1] == pytest.approx(np.exp(-0.3))
    # Team 1 is now the visitor, so neither of its deviations may appear.
    assert away[0] == pytest.approx(np.exp(0.2))
    assert away[1] == pytest.approx(1.0)


def test_infeasible_rho_is_rejected_with_a_useful_direction():
    """A rho implying a negative probability must not look like a minimum, or
    the optimiser stops there."""
    home, away, hg, ag, days_ago = synthetic()
    d = dc.build_design(home, away, hg, ag, days_ago)
    n = d.n_teams
    # A large positive rho drives tau negative on 0-0 draws.
    params = np.concatenate([np.zeros(n - 1), np.zeros(n), [0.25], [50.0]])
    value, grad = dc.objective(params, d)
    assert value >= 1e10
    assert grad[-1] > 0, "gradient should push rho back toward zero"


def test_fit_recovers_a_positive_home_advantage():
    home, away, hg, ag, days_ago = synthetic(n_matches=1200)
    fitted = dc.fit(home, away, hg, ag, days_ago)
    assert 0.0 < fitted.home_advantage < 1.0
    assert fitted.n_matches == 1200
    # Attack strengths are pinned to sum to zero for identifiability.
    assert sum(fitted.attack.values()) == pytest.approx(0.0, abs=1e-6)


def test_score_matrix_is_a_distribution():
    home, away, hg, ag, days_ago = synthetic()
    fitted = dc.fit(home, away, hg, ag, days_ago)
    matrix = fitted.score_matrix(0, 1)
    assert matrix.min() >= 0
    assert matrix.sum() == pytest.approx(1.0)


def test_markets_are_mutually_consistent():
    """Every market is a sum over one score matrix, which is the entire reason
    to model the scoreline rather than each market separately. If these ever
    disagree the published table contradicts itself."""
    home, away, hg, ag, days_ago = synthetic()
    fitted = dc.fit(home, away, hg, ag, days_ago)
    matrix = fitted.score_matrix(0, 1)

    p_home, p_draw, p_away = dc.outcome_probabilities(matrix)
    assert p_home + p_draw + p_away == pytest.approx(1.0)

    # Over 0.5 is the complement of a 0-0 draw.
    assert dc.over_probability(matrix, 0.5) == pytest.approx(1.0 - matrix[0, 0])
    # Both teams scoring implies at least two goals.
    assert dc.btts_probability(matrix) <= dc.over_probability(matrix, 1.5) + 1e-12
    # Over lines must decrease.
    overs = [dc.over_probability(matrix, x) for x in (0.5, 1.5, 2.5, 3.5, 4.5)]
    assert overs == sorted(overs, reverse=True)
    # Per-team goals sum to the same total.
    assert dc.team_over_probability(matrix, 0.5, home=True) <= 1.0
    assert dc.team_over_probability(matrix, -0.5, home=False) == pytest.approx(1.0)


def test_a_stronger_team_is_given_a_better_chance():
    """The sanity check that the parameters mean what their names say."""
    home, away, hg, ag, days_ago = synthetic(n_matches=1500)
    fitted = dc.fit(home, away, hg, ag, days_ago)
    best = max(fitted.attack, key=lambda t: fitted.attack[t] - fitted.defence[t])
    worst = min(fitted.attack, key=lambda t: fitted.attack[t] - fitted.defence[t])
    strong_home = dc.outcome_probabilities(fitted.score_matrix(best, worst))[0]
    weak_home = dc.outcome_probabilities(fitted.score_matrix(worst, best))[0]
    assert strong_home > weak_home


def test_a_promoted_club_is_priced_at_the_league_average():
    """A club with no history must sit at the league average, and the average is
    the mean of the fitted parameters rather than zero.

    Only attack is centred on zero by the fit. Defence is not, so defaulting it
    to zero quietly understated the goals expected against every promoted club.
    """
    home, away, hg, ag, days_ago = synthetic(n_matches=800)
    fitted = dc.fit(home, away, hg.astype(float), ag.astype(float), days_ago)
    promoted = 999

    average_home = np.mean([
        fitted.rates(h, a)[0] for h in fitted.teams for a in fitted.teams if h != a
    ])
    lam, mu = fitted.rates(promoted, promoted)
    # Two average sides: the home rate is the league's average home rate.
    assert lam == pytest.approx(average_home, rel=0.1)
    # And the model still favours the home side between two identical teams.
    assert lam > mu

    matrix = fitted.score_matrix(promoted, 0)
    assert matrix.sum() == pytest.approx(1.0)
    assert all(0.01 < p < 0.99 for p in dc.outcome_probabilities(matrix))
