"""Tests for the feature blend.

The blend was measured and rejected — it did not beat the plain models on a
two-season holdout in any consistent way, and the numbers are in
`docs/04-phase2-feature-blend.md`. These tests exist anyway, for one reason: a
negative result is only worth anything if the thing that produced it was
actually working. If the offset were wired up wrongly the experiment would have
measured a bug rather than the features, and the conclusion would be worthless.

So what is pinned here is the mechanism, not the outcome: that fitting on the
ratio with rate weights really is a Poisson fit with a log offset, that a
correction with nothing to find stays out of the way, and that a blended
distribution is scored over the same support as the model it is compared with.
"""

from __future__ import annotations

import numpy as np
import pytest

from footy.models import counts as cm
from footy.models.blend import fit_correction, pmf_for_rate
from footy.models.counts_backtest import observable

RNG = np.random.default_rng(7)
LOOSE = {"max_iter": 120, "min_samples_leaf": 60, "max_bins": 64,
         "max_leaf_nodes": 7, "l2_regularization": 1.0}


def planted(n: int = 5000, strength: float = 0.25):
    """A baseline that is right on average, plus one thing only a feature sees."""
    base = np.exp(np.log(RNG.uniform(8.0, 14.0, n)))
    signal = RNG.normal(0, 1, n)
    y = RNG.poisson(base * np.exp(strength * signal)).astype(float)
    X = np.column_stack([signal, RNG.normal(0, 1, (n, 3))])
    return X, y, base, signal


def test_the_offset_identity_recovers_a_planted_correction():
    """The whole method rests on fitting y/rate weighted by rate. If that is not
    equivalent to a log offset, the correction learned is not the one intended."""
    X, y, base, signal = planted()
    correction = fit_correction(X, y, base, np.ones(len(y)), False, LOOSE)
    learned = np.log(correction.rates(base, X) / base)
    slope = np.polyfit(0.25 * signal, learned, 1)[0]
    assert np.corrcoef(learned, 0.25 * signal)[0, 1] > 0.9
    assert 0.75 < slope < 1.25, f"recovered the correction at slope {slope:.2f}"


def test_a_correction_with_nothing_to_find_stays_out_of_the_way():
    """The safety property that makes the blend a fair comparison: given a rate
    that is already correct, it must not manufacture an adjustment from noise.
    Without this, a loss would not distinguish 'the features are useless' from
    'the method is destructive'."""
    n = 5000
    base = RNG.uniform(8.0, 14.0, n)
    y = RNG.poisson(base).astype(float)
    noise_only = RNG.normal(0, 1, (n, 6))
    correction = fit_correction(noise_only, y, base, np.ones(n), False, LOOSE)
    pushed = np.log(correction.rates(base, noise_only) / base)
    assert abs(float(np.mean(pushed))) < 0.05
    assert float(np.std(pushed)) < 0.10, (
        f"invented a correction of sd {np.std(pushed):.3f} out of pure noise"
    )


def test_the_adjustment_is_bounded():
    """A thin leaf on an unusual fixture must not be able to triple a rate."""
    n = 800
    base = np.full(n, 10.0)
    # A feature that perfectly predicts a wild target, to push as hard as possible.
    extreme = RNG.normal(0, 1, (n, 2))
    y = np.where(extreme[:, 0] > 0, 60.0, 1.0)
    correction = fit_correction(extreme, y, base, np.ones(n), False, LOOSE)
    ratio = correction.rates(base, extreme) / base
    assert ratio.max() <= np.exp(0.5) + 1e-9
    assert ratio.min() >= np.exp(-0.5) - 1e-9


def test_a_blended_distribution_is_a_distribution():
    for rate, dispersion in ((10.0, None), (10.0, 5.0), (2.3, 1.4), (24.0, 30.0)):
        pmf = pmf_for_rate(rate, dispersion, cm.MAX_COUNT + 1)
        assert pmf.min() >= 0.0
        assert abs(pmf.sum() - 1.0) < 1e-9


def test_a_blend_that_changed_nothing_matches_the_model_it_corrects():
    """At an unchanged rate the blended pmf must equal the base model's, or the
    comparison would be measuring a difference in plumbing rather than in rate."""
    rate, dispersion = 11.4, 7.2
    mine = pmf_for_rate(rate, dispersion, 2 * cm.MAX_COUNT + 1)
    theirs = np.exp(
        cm.negative_binomial_loglik(
            np.arange(2 * cm.MAX_COUNT + 1), np.full(2 * cm.MAX_COUNT + 1, rate),
            dispersion,
        )
    )
    theirs = theirs / theirs.sum()
    assert np.abs(mine - theirs).max() < 1e-12


@pytest.mark.parametrize(
    "scope,expected",
    [
        ("total", "total"),
        ("total blend", "total"),
        ("total blend calibrated", "total"),
        ("convolved", "total"),
        ("home", "home"),
        ("home blend calibrated", "home"),
        ("away blend", "away"),
    ],
)
def test_every_variant_is_settled_against_the_same_observed_number(scope, expected):
    """A blend scored against a different quantity than the model it replaces
    would produce a meaningless comparison, and the failure would be invisible
    in the report — it would just look like a very good or very bad blend."""
    assert observable(scope) == expected
