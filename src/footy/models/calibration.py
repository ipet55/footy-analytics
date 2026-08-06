"""Probability recalibration.

A count model can rank matches well and still put the wrong number on the page.
Across all five leagues the raw count models show the same distortion: matches
they call 34% come in at 40%, matches they call 59% come in at 49%. The ordering
is right, the spread is too wide — the model separates fixtures more confidently
than the evidence supports, which is what fitting team strengths on a few hundred
matches does.

The fix is one extra transformation, on the log-odds rather than the probability:

    calibrated = sigmoid(a + b * logit(raw))

b below 1 pulls everything toward the average, a shifts the whole market. Two
parameters cannot invent signal and cannot reorder anything; all they do is
correct the confidence, which is exactly the defect. Fitting on the log-odds
rather than the probability keeps the result inside (0, 1) automatically and
leaves a perfectly calibrated model unchanged at a = 0, b = 1.

The parameters must be fitted on predictions the model did not train on, and
only ever on matches that had already been played. Fitting them on the training
data would measure the model's overconfidence about matches it had memorised,
which is a different and much smaller number.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

EPS = 1e-6


def logit(p: np.ndarray | float) -> np.ndarray:
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(z: np.ndarray | float) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(z, float)))


@dataclass(frozen=True)
class Recalibrator:
    intercept: float
    slope: float
    n: int = 0

    @classmethod
    def identity(cls) -> Recalibrator:
        return cls(0.0, 1.0, 0)

    @property
    def is_identity(self) -> bool:
        return self.n == 0

    def apply(self, p: float) -> float:
        return float(sigmoid(self.intercept + self.slope * logit(p)))

    @classmethod
    def fit(
        cls,
        raw: np.ndarray,
        outcomes: np.ndarray,
        min_observations: int = 200,
        ridge: float = 1.0,
    ) -> Recalibrator:
        """Maximum likelihood, shrunk toward leaving the probabilities alone.

        The ridge term is a prior that the model is already calibrated. With a
        few hundred observations the slope is itself a noisy estimate, and
        without the prior an unlucky stretch of results would be read as
        overconfidence and baked in. It costs nothing once there is real
        evidence, because the likelihood grows with n while the penalty does not.
        """
        raw = np.asarray(raw, float)
        y = np.asarray(outcomes, float)
        if len(raw) < min_observations or len(np.unique(y)) < 2:
            return cls.identity()

        z = logit(raw)

        def objective(params: np.ndarray) -> tuple[float, np.ndarray]:
            a, b = params
            s = sigmoid(a + b * z)
            s = np.clip(s, EPS, 1 - EPS)
            nll = -float(np.sum(y * np.log(s) + (1 - y) * np.log(1 - s)))
            nll += ridge * (a**2 + (b - 1.0) ** 2)
            residual = s - y
            grad = np.array([
                residual.sum() + 2 * ridge * a,
                float(np.sum(residual * z)) + 2 * ridge * (b - 1.0),
            ])
            return nll, grad

        result = minimize(
            objective, np.array([0.0, 1.0]), method="L-BFGS-B", jac=True,
            bounds=[(-3.0, 3.0), (0.0, 3.0)],
        )
        return cls(float(result.x[0]), float(result.x[1]), len(raw))


def reliability(
    predicted: np.ndarray, actual: np.ndarray, buckets: int = 5
) -> list[tuple[float, float, int]]:
    """Equal-count buckets of (mean predicted, observed rate, n)."""
    p = np.asarray(predicted, float)
    y = np.asarray(actual, float)
    edges = np.quantile(p, np.linspace(0, 1, buckets + 1))
    out = []
    for i in range(buckets):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p <= hi if i == buckets - 1 else p < hi)
        if mask.sum() < 10:
            continue
        out.append((float(p[mask].mean()), float(y[mask].mean()), int(mask.sum())))
    return out


def worst_bucket_error(predicted: np.ndarray, actual: np.ndarray, buckets: int = 5) -> float:
    """The number that decides whether a market is fit to publish: the largest
    gap between a stated percentage and how often it actually happened."""
    rows = reliability(predicted, actual, buckets)
    return max((abs(p - a) for p, a, _ in rows), default=0.0)
