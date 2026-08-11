"""Tests for the count models.

The gradient checks are the important ones. A wrong analytic gradient does not
raise; the optimiser just stops somewhere that is not the maximum likelihood, so
the model quietly gets worse and every backtest number after it is wrong. These
compare the derivatives against finite differences of the likelihood itself, so
the two would have to be wrong in exactly the same way to agree.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import approx_fprime

from footy.models import counts as cm

RNG = np.random.default_rng(20260806)


def assert_gradient_close(analytic: np.ndarray, numeric: np.ndarray) -> None:
    """Compare against the size of the whole gradient rather than element by
    element. Forward differences carry an error proportional to the magnitude of
    the likelihood, so a component that is near zero while its neighbours are in
    the hundreds cannot be checked on its own relative error."""
    scale = max(float(np.abs(numeric).max()), 1.0)
    error = float(np.abs(analytic - numeric).max()) / scale
    assert error < 1e-5, f"largest scaled gradient error {error:.2e}"


def synthetic(n_teams: int = 8, n_matches: int = 240, with_referees: bool = False):
    """A season-shaped sample: every team plays, counts are overdispersed."""
    home = RNG.integers(0, n_teams, n_matches)
    away = (home + RNG.integers(1, n_teams, n_matches)) % n_teams
    strength = RNG.normal(0, 0.25, n_teams)
    mu_home = np.exp(1.7 + strength[home] - strength[away] * 0.5)
    mu_away = np.exp(1.6 + strength[away] - strength[home] * 0.5)
    home_counts = RNG.poisson(mu_home).astype(float)
    away_counts = RNG.poisson(mu_away).astype(float)
    days_ago = np.sort(RNG.uniform(0, 1200, n_matches))[::-1].copy()
    referees = RNG.integers(1, 6, n_matches).astype(float) if with_referees else None
    return home, away, home_counts, away_counts, days_ago, referees


@pytest.mark.parametrize("stat", ["corners", "cards", "fouls", "shots"])
def test_total_gradient_matches_finite_differences(stat):
    spec = cm.SPECS[stat]
    home, away, hc, ac, days_ago, refs = synthetic(with_referees=spec.use_referee)
    d = cm.build_design(home, away, days_ago, spec, refs)
    totals = hc + ac

    n_params = (
        d.n_teams + d.n_dispersion + d.n_referees
    )  # n-1 tempo + intercept + dispersion + referees
    params = RNG.normal(0, 0.2, n_params)
    params[d.n_teams - 1] = np.log(totals.mean())  # intercept near a sane value
    if d.n_dispersion:
        params[d.n_teams] = np.log(8.0)

    assert_gradient_close(
        cm.total_objective(params, d, totals)[1],
        approx_fprime(params, lambda p: cm.total_objective(p, d, totals)[0], 1e-6),
    )


@pytest.mark.parametrize("stat", ["corners", "cards"])
def test_count_gradient_matches_finite_differences(stat):
    spec = cm.SPECS[stat]
    home, away, hc, ac, days_ago, refs = synthetic(with_referees=spec.use_referee)
    d = cm.build_design(home, away, days_ago, spec, refs)

    n_params = (
        (d.n_teams - 1) + d.n_teams + 1 + d.n_dispersion + d.n_referees
    )
    params = RNG.normal(0, 0.2, n_params)
    params[d.n_teams - 1 : 2 * d.n_teams - 1] = np.log(hc.mean()) / 2
    if d.n_dispersion:
        params[2 * d.n_teams] = np.log(6.0)

    assert_gradient_close(
        cm.count_objective(params, d, hc, ac)[1],
        approx_fprime(params, lambda p: cm.count_objective(p, d, hc, ac)[0], 1e-6),
    )


def test_referee_effects_are_shrunk_toward_zero():
    """The penalty is what stops an official with five appearances from getting
    a large effect on the strength of noise."""
    spec = cm.SPECS["cards"]
    home, away, hc, ac, days_ago, refs = synthetic(with_referees=True)
    loose = cm.fit(home, away, hc, ac, days_ago, spec, refs, referee_penalty=0.1)
    tight = cm.fit(home, away, hc, ac, days_ago, spec, refs, referee_penalty=500.0)
    assert max(abs(v) for v in tight.referee.values()) < max(
        abs(v) for v in loose.referee.values()
    )


def promoted_and_relegated(mean_count: float, n_current: int = 20,
                           n_departed: int = 13, per_season: int = 380):
    """A decade of one league, including teams long since relegated.

    The relegated teams are what makes this the shape that broke. Time decay
    leaves them with almost no weight, so the data says nothing about their
    parameters, but the sum-to-zero constraint still applies to them — and a
    parameter free to drift while bound by a constraint drags the teams that are
    identified along with it.
    """
    home, away, days = [], [], []
    for season in range(8):
        # Departed teams appear only in the earliest seasons.
        squad = (
            list(range(n_current + n_departed))
            if season < 3
            else list(range(n_current))
        )
        for _ in range(per_season):
            h, a = RNG.choice(squad, 2, replace=False)
            home.append(h)
            away.append(a)
            days.append((7 - season) * 365 + RNG.uniform(0, 365))

    home = np.array(home)
    away = np.array(away)
    days_ago = np.array(days)
    strength = RNG.normal(0, 0.2, n_current + n_departed)
    hc = RNG.poisson(mean_count * np.exp(strength[home])).astype(float)
    ac = RNG.poisson(mean_count * np.exp(strength[away])).astype(float)
    return home, away, hc, ac, days_ago, n_current


@pytest.mark.parametrize("stat,mean_count",
                         [("cards", 1.7), ("corners", 5.4),
                          ("fouls", 10.7), ("shots", 12.7)])
def test_fitted_rates_stay_near_the_data_whatever_its_level(stat, mean_count):
    """The regression test for the divergence that produced fouls rates in the
    billions.

    Attack is pinned to sum to zero, so it cannot carry any of the level. When
    concede started at only half of that level the optimiser had to find the rest
    somewhere, and with relegated teams free to drift it pushed attacks into
    their bounds instead. Fitted fouls rates for real fixtures came out at 1e12
    in four of the five leagues.

    Nothing raised. Cards and corners were unaffected because their means are
    small enough that half the level is close enough to start from, so the
    failure was invisible in three of the four markets, which is why it needs a
    test that sweeps the level rather than one fixture of synthetic data.
    """
    spec = cm.SPECS[stat]
    home, away, hc, ac, days_ago, n_current = promoted_and_relegated(mean_count)

    fitted = cm.fit(home, away, hc, ac, days_ago, spec)
    # Only the teams still playing matter; the departed ones are unidentified by
    # construction and no model can say anything about them.
    rates = [r for h in range(n_current) for a in range(n_current) if h != a
             for r in fitted.rates(h, a)]

    observed = float(np.mean(np.concatenate([hc, ac])))
    assert max(rates) < 5 * observed, f"rate {max(rates):.3g} against mean {observed:.1f}"
    assert min(rates) > observed / 5
    current = [fitted.attack[t] for t in range(n_current)]
    assert all(abs(v) < 2.99 for v in current), "an attack hit its bound"


def test_a_promoted_club_is_priced_at_the_league_average():
    """A club with no history must come out near the league average, not near
    zero.

    `concede` carries the whole level of the count, so defaulting an unknown team
    to zero priced a promoted club's match at about one foul instead of ten. That
    is not a slightly-off prediction: the over probability underflows, and the
    stored value violates its own check constraint. Four clubs were promoted into
    these leagues for 2026-27, so this is a live path, not a hypothetical.
    """
    spec = cm.SPECS["fouls"]
    home, away, hc, ac, days_ago, _ = synthetic(n_teams=8, n_matches=600)
    fitted = cm.fit(home, away, hc, ac, days_ago, spec)

    observed = float(np.mean(np.concatenate([hc, ac])))
    promoted = 999
    for rates in (fitted.rates(promoted, 0), fitted.rates(0, promoted)):
        for rate in rates:
            assert observed / 2 < rate < observed * 2, (
                f"rate {rate:.3f} against a league mean of {observed:.1f}"
            )

    # And the resulting distribution has to be usable, which is the thing that
    # actually broke: a rate of 1 makes P(over 10.5) round to zero.
    pmf = fitted.pmf(fitted.rates(promoted, 0)[0])
    assert 0.01 < cm.over_probability(pmf, 10.5) < 0.99


def test_fitted_rates_recover_a_known_home_advantage():
    spec = cm.SPECS["corners"]
    home, away, hc, ac, days_ago, _ = synthetic(n_matches=600)
    fitted = cm.fit(home, away, hc, ac, days_ago, spec)
    # The synthetic data gives the home side a slightly higher rate.
    assert fitted.home_advantage > 0
    assert fitted.dispersion is not None and fitted.dispersion > 0


@pytest.mark.parametrize("stat", ["corners", "cards", "fouls", "shots"])
def test_distributions_are_proper(stat):
    spec = cm.SPECS[stat]
    home, away, hc, ac, days_ago, refs = synthetic(with_referees=spec.use_referee)
    team = cm.fit(home, away, hc, ac, days_ago, spec, refs)
    total = cm.fit_total(home, away, hc + ac, days_ago, spec, refs)

    home_pmf, away_pmf = team.team_pmfs(0, 1)
    total_pmf = total.pmf(0, 1)
    for pmf in (home_pmf, away_pmf, total_pmf):
        assert pmf.min() >= 0
        assert pmf.sum() == pytest.approx(1.0)

    # Over probabilities must fall as the line rises, and stay in [0, 1].
    overs = [cm.over_probability(total_pmf, line) for line in (0.5, 4.5, 9.5, 30.5)]
    assert all(0.0 <= p <= 1.0 for p in overs)
    assert overs == sorted(overs, reverse=True)


def test_over_probability_excludes_the_line_itself():
    """A 2.5 line is settled by whether the count exceeds 2, and a whole-number
    line would be a push. Off-by-one here misprices every market on the page."""
    pmf = np.zeros(11)
    pmf[2] = 0.5
    pmf[3] = 0.5
    assert cm.over_probability(pmf, 2.5) == pytest.approx(0.5)
    assert cm.over_probability(pmf, 1.5) == pytest.approx(1.0)
    assert cm.over_probability(pmf, 3.5) == pytest.approx(0.0)


def test_negative_binomial_is_wider_than_poisson_at_the_same_mean():
    """Why the distribution choice matters: at equal means the overdispersed one
    puts more weight in the tail, which is precisely the over/under price."""
    spec = cm.SPECS["corners"]
    poisson = cm.FittedCount(spec, {}, {}, 0.0, dispersion=None)
    overdispersed = cm.FittedCount(spec, {}, {}, 0.0, dispersion=3.0)
    rate = 5.0
    assert cm.over_probability(overdispersed.pmf(rate), 9.5) > cm.over_probability(
        poisson.pmf(rate), 9.5
    )
