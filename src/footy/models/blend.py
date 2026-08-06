"""Gradient boosting over the feature layer, as a correction to the fitted models.

The count and goals models know only who is playing, when, and the statistic
they predict. Everything in `features` — rest days, rolling form, expected
goals, Elo, head to head — has been built and leakage-tested and, until now,
used by nothing. This is where it enters.

It enters as a correction rather than a replacement:

    log(rate) = log(rate from the fitted model) + f(features)

which matters for three reasons. The fitted models are good at the thing they
do — pooling a decade of matches into a per-team strength — and a tree asked to
rediscover that from features would approximate it in step functions and lose.
The existing behaviour is the special case f = 0, so the blend is a strict
generalisation and the comparison against it is honest by construction. And if
the features carry nothing, the correction collapses toward zero on its own
rather than having to be talked out of the model.

The offset is not passed to the booster directly, because scikit-learn's
implementation has no parameter for one. It does not need one. For a Poisson
likelihood with offset t, writing w = exp(t) and z = y / exp(t),

    exp(t + f) - y(t + f)  =  w * (exp(f) - z * f)  + terms free of f

so fitting target z with sample weights w against a Poisson loss is the same
optimisation. Verified against the known answer on synthetic data before being
used here: it recovers a planted correction with slope 0.97, and leaves an
already-correct baseline alone to within a standard deviation of 0.02.

The dispersion is refitted afterwards. If the correction explains variance that
the base model was absorbing as overdispersion, keeping the old parameter would
leave every probability pulled toward the middle — underconfident rather than
over. It is one scalar given the rates, so there is no reason to leave it stale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.ensemble import HistGradientBoostingRegressor

from footy import db
from footy.models import counts as cm

# Per-team features. Deliberately the whole set rather than the columns that
# look relevant for a given statistic: hand-picking them per target would be
# fitting the feature list to expectations, and the booster is better placed to
# decide than intuition is.
TEAM_COLUMNS = (
    "matches_before",
    "gf_5", "ga_5", "xgf_5", "xga_5", "ppg_5",
    "corners_f_5", "corners_a_5", "shots_f_5", "shots_a_5", "fouls_5", "yellows_5",
    "gf_10", "ga_10", "xgf_10", "xga_10", "ppg_10",
    "corners_f_10", "corners_a_10", "shots_f_10", "shots_a_10", "fouls_10", "yellows_10",
    "xgf_20", "xga_20",
    "gf_venue_10", "ga_venue_10", "xgf_venue_10", "xga_venue_10",
    "corners_f_venue_10", "corners_a_venue_10", "yellows_venue_10",
    "season_matches", "season_ppg", "season_xgf", "season_xga",
    "rest_days", "elo_xg", "elo_goals", "clubelo",
)

# Fixture-level features. The de-vigged market probabilities in features.match
# are excluded on purpose: a model meant to disagree with the market usefully
# cannot be trained on the market's own answer.
MATCH_COLUMNS = (
    "h2h_matches", "h2h_avg_goals", "h2h_avg_corners",
    "rating_diff", "difficulty_home", "difficulty_away",
)


@dataclass
class Features:
    """Feature rows per match, with the home and away sides side by side."""

    index: dict[int, int]
    values: np.ndarray
    names: list[str]

    def matrix(self, match_ids: list[int]) -> np.ndarray:
        """Rows for these matches, in this order.

        A match with no feature row comes back as all-NaN rather than being
        dropped, because the booster handles missing values natively and losing
        the fixture would silently change what the comparison is measured over.
        """
        out = np.full((len(match_ids), self.values.shape[1]), np.nan)
        for i, mid in enumerate(match_ids):
            row = self.index.get(mid)
            if row is not None:
                out[i] = self.values[row]
        return out


def load_features(competition: str) -> Features:
    home_cols = ", ".join(f"h.{c}" for c in TEAM_COLUMNS)
    away_cols = ", ".join(f"a.{c}" for c in TEAM_COLUMNS)
    match_cols = ", ".join(f"f.{c}" for c in MATCH_COLUMNS)
    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            f"""
            select f.match_id, {home_cols}, {away_cols}, {match_cols}
              from features.match f
              join core.match m on m.match_id = f.match_id
              join core.competition c on c.competition_id = m.competition_id
                                     and c.code = %s
              join features.team_match h on h.match_id = f.match_id
                                        and h.team_id = m.home_team_id
              join features.team_match a on a.match_id = f.match_id
                                        and a.team_id = m.away_team_id
             order by f.match_id
            """,
            (competition,),
        )
    names = (
        [f"home_{c}" for c in TEAM_COLUMNS]
        + [f"away_{c}" for c in TEAM_COLUMNS]
        + list(MATCH_COLUMNS)
    )
    index = {int(r[0]): i for i, r in enumerate(rows)}
    values = np.array(
        [[np.nan if v is None else float(v) for v in r[1:]] for r in rows]
    )
    return Features(index=index, values=values, names=names)


def _fit_dispersion(y: np.ndarray, mu: np.ndarray, weights: np.ndarray) -> float:
    """Negative binomial dispersion by one-dimensional MLE, rates held fixed."""

    def negative_loglik(log_r: float) -> float:
        r = float(np.exp(log_r))
        return -float(np.sum(weights * cm.negative_binomial_loglik(y, mu, r)))

    result = minimize_scalar(
        negative_loglik, bounds=(np.log(0.5), np.log(3000.0)), method="bounded"
    )
    return float(np.exp(result.x))


@dataclass
class Correction:
    """A fitted correction, plus the dispersion that goes with the new rates."""

    booster: HistGradientBoostingRegressor
    dispersion: float | None
    n_features: int
    # Kept for reporting: how hard the correction is actually pushing. A blend
    # that turns out to be doing nothing should be visible as a number, not
    # inferred from its scores.
    train_sd: float = 0.0

    def log_adjustment(self, X: np.ndarray) -> np.ndarray:
        return np.log(np.clip(self.booster.predict(X), 1e-9, None))

    def rates(self, base_rates: np.ndarray, X: np.ndarray) -> np.ndarray:
        # Bounded because a tree extrapolating on an unusual fixture can produce
        # a large adjustment from few observations, and a rate that has tripled
        # is far more likely to be a thin leaf than a real prediction. e^0.5 is
        # a factor of 1.65 either way, which is wider than any effect the
        # features plausibly carry.
        adjustment = np.clip(self.log_adjustment(X), -0.5, 0.5)
        return np.exp(np.log(np.clip(base_rates, 1e-9, None)) + adjustment)


# Hyperparameters, set to the least-bad configuration the sweep found rather
# than to anything conventional. Shallow trees, few of them, a large leaf
# minimum: a refit sees a few thousand matches and the effect sought is small.
#
# The sweep is worth reading before changing these. Holdout loss rose
# monotonically with the number of trees at every leaf size tried, so 25 is not
# a tuned optimum — it is the smallest value tested that still does something,
# and the honest reading of the curve is that the optimum is zero. See
# docs/04-phase2-feature-blend.md.
DEFAULTS = {
    "learning_rate": 0.04,
    "max_iter": 25,
    "max_leaf_nodes": 4,
    "min_samples_leaf": 120,
    "max_bins": 64,
    "l2_regularization": 5.0,
}


def fit_correction(
    X: np.ndarray,
    y: np.ndarray,
    base_rates: np.ndarray,
    weights: np.ndarray,
    negative_binomial: bool,
    params: dict | None = None,
) -> Correction:
    """Learn what the features know that the fitted rate does not."""
    settings = {**DEFAULTS, **(params or {})}
    base = np.clip(base_rates, 1e-9, None)

    # The offset identity: target the ratio, weight by the base rate. The time
    # decay multiplies in, so an old match counts for as little here as it does
    # in the model being corrected.
    booster = HistGradientBoostingRegressor(
        loss="poisson", random_state=0, early_stopping=False, **settings
    )
    booster.fit(X, y / base, sample_weight=weights * base)

    adjustment = np.clip(
        np.log(np.clip(booster.predict(X), 1e-9, None)), -0.5, 0.5
    )
    blended = np.exp(np.log(base) + adjustment)
    dispersion = (
        _fit_dispersion(y, blended, weights) if negative_binomial else None
    )
    return Correction(
        booster=booster,
        dispersion=dispersion,
        n_features=X.shape[1],
        train_sd=float(np.std(adjustment)),
    )


@dataclass
class Corrections:
    """One correction per scope, so a market can gain a blend while another
    keeps the plain model."""

    total: Correction | None = None
    home: Correction | None = None
    away: Correction | None = None

    def get(self, scope: str) -> Correction | None:
        return {"total": self.total, "home": self.home, "away": self.away}.get(scope)


def pmf_for_rate(rate: float, dispersion: float | None, size: int) -> np.ndarray:
    """The same distributions the fitted models use, at a blended rate.

    Shares `counts.MAX_COUNT` conventions so a blended probability and a base
    one are summed over identical support and stay comparable.
    """
    k = np.arange(size)
    from scipy.special import gammaln

    if dispersion is None:
        log_p = k * np.log(rate) - rate - gammaln(k + 1)
    else:
        r = dispersion
        log_p = (
            gammaln(k + r) - gammaln(r) - gammaln(k + 1)
            + r * np.log(r / (r + rate)) + k * np.log(rate / (r + rate))
        )
    p = np.exp(log_p)
    total = p.sum()
    return p / total if total > 0 else p


@dataclass
class HoldoutResult:
    """One league and market: what the blend did to the base model's likelihood."""

    competition: str
    stat: str
    scope: str
    base_loglik: float
    blend_loglik: float
    push_sd: float
    top_feature: str
    n_train: int
    n_holdout: int

    @property
    def delta(self) -> float:
        return self.blend_loglik - self.base_loglik

    @property
    def better(self) -> bool:
        return self.delta > 0


def out_of_fold_rates(
    history: list,
    spec,
    fit_models,
    scope: str,
    warmup: int = 700,
    blocks: int = 8,
) -> tuple[np.ndarray, np.ndarray]:
    """Base rates for training matches, each from a model that had not seen them.

    Without this the correction is trained on the base model's in-sample
    residuals, which are smaller and differently shaped than the ones it will
    face in production — the team parameters have already absorbed some of the
    noise it is being asked to explain. It is the difference between measuring
    the features and measuring the base model's overfitting.

    Returns the indices covered and their rates. Matches inside the warm-up are
    not covered, because there is no earlier model to price them with.

    `fit_models` is injected rather than imported to keep this module free of a
    circular dependency on the backtest that calls it.
    """
    edges = np.linspace(warmup, len(history), blocks + 1).astype(int)
    indices: list[int] = []
    rates: list[float] = []
    for start, stop in pairwise(edges):
        if stop <= start:
            continue
        fitted = fit_models(history[:start], history[start].kickoff, spec, None)
        for j in range(start, stop):
            indices.append(j)
            rates.append(fitted.base_rates(history[j])[scope])
    return np.array(indices, dtype=int), np.array(rates)


@dataclass
class Importance:
    """Which features the correction actually leaned on, for the writeup."""

    names: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)


def permutation_importance(
    correction: Correction,
    X: np.ndarray,
    y: np.ndarray,
    base_rates: np.ndarray,
    names: list[str],
    top: int = 12,
    rng_seed: int = 0,
) -> Importance:
    """Loss increase when one feature is shuffled.

    Reported instead of the booster's split counts, which reward features that
    are merely easy to split on. This asks the only question that matters: does
    the prediction get worse without it.
    """
    rng = np.random.default_rng(rng_seed)

    def deviance(matrix: np.ndarray) -> float:
        mu = correction.rates(base_rates, matrix)
        return float(np.mean(mu - y * np.log(np.clip(mu, 1e-9, None))))

    baseline = deviance(X)
    scored: list[tuple[str, float]] = []
    for j, name in enumerate(names):
        shuffled = X.copy()
        shuffled[:, j] = rng.permutation(shuffled[:, j])
        scored.append((name, deviance(shuffled) - baseline))
    scored.sort(key=lambda kv: kv[1], reverse=True)
    return Importance(
        names=[n for n, _ in scored[:top]], scores=[s for _, s in scored[:top]]
    )
