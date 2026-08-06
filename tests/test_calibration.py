"""Tests for probability recalibration.

The recalibrator is only allowed to fix confidence. It must not be able to
invent signal, reorder fixtures, or damage probabilities that were already
correct — those three properties are what make it safe to apply to every market
rather than only the ones it was tuned on.
"""

from __future__ import annotations

import numpy as np
import pytest

from footy.models.calibration import (
    Recalibrator,
    logit,
    sigmoid,
    worst_bucket_error,
)

RNG = np.random.default_rng(11)


def overconfident_sample(n: int = 4000, spread: float = 1.8):
    """Probabilities that rank correctly but are pushed too far from the average,
    which is the exact defect the count models show."""
    truth = sigmoid(RNG.normal(0, 0.8, n))
    outcomes = (RNG.random(n) < truth).astype(int)
    stretched = sigmoid(spread * logit(truth))
    return stretched, outcomes, truth


def test_identity_leaves_probabilities_untouched():
    r = Recalibrator.identity()
    assert r.is_identity
    for p in (0.01, 0.25, 0.5, 0.87, 0.999):
        assert r.apply(p) == pytest.approx(p, abs=1e-9)


def test_too_few_observations_falls_back_to_identity():
    """Better to publish the model's own number than one corrected on the
    strength of thirty matches."""
    p, y, _ = overconfident_sample(n=30)
    assert Recalibrator.fit(p, y).is_identity


def test_single_outcome_class_falls_back_to_identity():
    p = np.full(500, 0.4)
    y = np.zeros(500, int)
    assert Recalibrator.fit(p, y).is_identity


def test_overconfidence_is_corrected():
    p, y, _ = overconfident_sample()
    r = Recalibrator.fit(p, y)
    assert r.slope < 1.0, "an overconfident model needs its spread compressed"
    assert worst_bucket_error(np.array([r.apply(x) for x in p]), y) < worst_bucket_error(p, y)


def test_calibrated_probabilities_beat_raw_on_log_loss():
    p, y, _ = overconfident_sample()
    calibrated = np.array([Recalibrator.fit(p, y).apply(x) for x in p])

    def log_loss(probs):
        probs = np.clip(probs, 1e-9, 1 - 1e-9)
        return -np.mean(y * np.log(probs) + (1 - y) * np.log(1 - probs))

    assert log_loss(calibrated) < log_loss(p)


def test_ordering_is_preserved():
    """A monotone transform cannot change which fixture looks likelier, so
    recalibration can never turn a good ranking into a bad one."""
    p, y, _ = overconfident_sample()
    r = Recalibrator.fit(p, y)
    sample = np.linspace(0.01, 0.99, 60)
    adjusted = np.array([r.apply(x) for x in sample])
    assert np.all(np.diff(adjusted) > 0)


def test_an_already_calibrated_model_is_barely_touched():
    truth = sigmoid(RNG.normal(0, 0.8, 4000))
    y = (RNG.random(4000) < truth).astype(int)
    r = Recalibrator.fit(truth, y)
    assert r.slope == pytest.approx(1.0, abs=0.15)
    assert r.intercept == pytest.approx(0.0, abs=0.15)


def test_output_stays_a_probability():
    p, y, _ = overconfident_sample()
    r = Recalibrator.fit(p, y)
    for x in (1e-9, 0.001, 0.5, 0.999, 1 - 1e-9):
        assert 0.0 < r.apply(x) < 1.0


def test_worst_bucket_error_is_zero_for_a_perfect_forecaster():
    p = np.repeat([0.2, 0.5, 0.8], 400)
    y = np.concatenate([
        (np.arange(400) < 80).astype(int),
        (np.arange(400) < 200).astype(int),
        (np.arange(400) < 320).astype(int),
    ])
    assert worst_bucket_error(p, y, buckets=3) == pytest.approx(0.0, abs=1e-9)
