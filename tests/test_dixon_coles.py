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
