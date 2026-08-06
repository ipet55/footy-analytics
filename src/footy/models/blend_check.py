"""Reproduces the comparison that rejected the feature blend.

This exists because `docs/04-phase2-feature-blend.md` makes a claim — that
gradient boosting over the feature layer improves no market — and a claim in a
document is worth nothing if the only way to check it is to trust the author.
Running `footy blend-check` regenerates the table.

It is also the harness for the next attempt. When cup and European fixtures make
`rest_days` mean what it claims, and appearances and injuries give the models
some idea of who is playing, the features arrive in `features.team_match` and
this command says whether they earned their cost. Nothing else needs writing.

The comparison is a holdout rather than a walk-forward on purpose, and the
reasoning is in the document: a walk-forward is what establishes a number you
intend to publish, and a holdout is enough to reject. If something ever wins
here, it earns the walk-forward before anything reaches `ml.prediction`.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from footy.models import blend as bl
from footy.models import counts as cm
from footy.models import counts_backtest as cb

LEAGUES = ("ENG-PL", "ESP-LL", "GER-BL", "ITA-SA", "FRA-L1")

# Training ends here and the holdout runs to the end of the following two
# seasons. This deliberately stops short of the window Phase 1 reported on, so
# that a blend accepted here would still face genuinely unseen matches.
TRAIN_TO = date(2020, 7, 1)
HOLDOUT_TO = date(2022, 7, 1)


def _log_likelihood(
    counts: np.ndarray, rates: np.ndarray, dispersion: float | None
) -> float:
    if dispersion is None:
        return float(np.mean(cm.poisson_loglik(counts, rates)))
    return float(np.mean(cm.negative_binomial_loglik(counts, rates, dispersion)))


def one(
    stat: str,
    competition: str,
    scope: str = "total",
    out_of_fold: bool = True,
    train_to: date = TRAIN_TO,
    holdout_to: date = HOLDOUT_TO,
    features: bl.Features | None = None,
) -> bl.HoldoutResult:
    """Fit the base model and its correction, and score both on the holdout."""
    spec = cm.SPECS[stat]
    matches = cb.load(stat, competition)
    feats = features if features is not None else bl.load_features(competition)
    train = [m for m in matches if m.kickoff < train_to]
    holdout = [m for m in matches if train_to <= m.kickoff < holdout_to]
    if len(train) < 900 or not holdout:
        raise RuntimeError(
            f"{competition} {stat}: {len(train)} training and {len(holdout)} "
            f"holdout matches is not enough to compare on"
        )

    base = cb.fit_models(train, train_to, spec, None)
    weights = np.exp(
        -spec.xi * np.array([(train_to - m.kickoff).days for m in train], float)
    )
    X_train = feats.matrix([m.match_id for m in train])
    y_train = np.array([m.observed(scope) for m in train], float)

    if out_of_fold:
        rows, offsets = bl.out_of_fold_rates(train, spec, cb.fit_models, scope)
    else:
        rows = np.arange(len(train))
        offsets = np.array([base.base_rates(m)[scope] for m in train])

    correction = bl.fit_correction(
        X_train[rows], y_train[rows], offsets, weights[rows], spec.negative_binomial
    )

    X_holdout = feats.matrix([m.match_id for m in holdout])
    y_holdout = np.array([m.observed(scope) for m in holdout], float)
    base_rates = np.array([base.base_rates(m)[scope] for m in holdout])
    base_dispersion = (
        base.total.dispersion if scope == "total" else base.team.dispersion
    )

    # The residual correlation is computed on the training rows only. Ranking
    # features on the holdout is how the earlier version of this experiment
    # fooled itself into believing there was signal to chase.
    residual = y_train[rows] - offsets
    best, best_strength = "none", 0.0
    for j, name in enumerate(feats.names):
        column = X_train[rows, j]
        usable = ~np.isnan(column)
        if usable.sum() < 200 or np.std(column[usable]) == 0:
            continue
        strength = abs(np.corrcoef(column[usable], residual[usable])[0, 1])
        if strength > best_strength:
            best, best_strength = name, strength

    return bl.HoldoutResult(
        competition=competition,
        stat=stat,
        scope=scope,
        base_loglik=_log_likelihood(y_holdout, base_rates, base_dispersion),
        blend_loglik=_log_likelihood(
            y_holdout,
            correction.rates(base_rates, X_holdout),
            correction.dispersion,
        ),
        push_sd=correction.train_sd,
        top_feature=best,
        n_train=len(rows),
        n_holdout=len(holdout),
    )


def run(
    stats: tuple[str, ...] = ("corners", "fouls", "shots", "cards"),
    competitions: tuple[str, ...] = LEAGUES,
    scope: str = "total",
    out_of_fold: bool = True,
) -> list[bl.HoldoutResult]:
    results: list[bl.HoldoutResult] = []
    for competition in competitions:
        features = bl.load_features(competition)
        for stat in stats:
            results.append(
                one(stat, competition, scope, out_of_fold, features=features)
            )
    return results


def report(results: list[bl.HoldoutResult]) -> None:
    """Print the table, and the verdict the table implies."""
    if not results:
        print("nothing to report")
        return
    stats = sorted({r.stat for r in results}, key=lambda s: list(cm.SPECS).index(s))
    by_key = {(r.competition, r.stat): r for r in results}
    competitions = list(dict.fromkeys(r.competition for r in results))

    first = results[0]
    print(
        f"\nBlend minus base, holdout log-likelihood per match. Positive is better."
        f"\nTraining to {TRAIN_TO}, scored on {first.n_holdout} following matches "
        f"per league, scope '{first.scope}'.\n"
    )
    print(f"{'league':<9}" + "".join(f"{s:>11}" for s in stats) + "   top train feature")
    for competition in competitions:
        cells = []
        for stat in stats:
            r = by_key.get((competition, stat))
            cells.append("        n/a" if r is None else
                         f"{r.delta:>+10.5f}" + ("*" if r.better else " "))
        example = by_key.get((competition, stats[0]))
        print(f"{competition:<9}" + "".join(cells) +
              f"   {example.top_feature if example else ''}")

    better = sum(r.better for r in results)
    gains = [r.delta for r in results if r.better]
    losses = [r.delta for r in results if not r.better]
    print(f"\n  better in {better} of {len(results)} league-market combinations")
    if gains:
        print(f"  best gain  {max(gains):+.5f}   mean gain {np.mean(gains):+.5f}")
    if losses:
        print(f"  worst loss {min(losses):+.5f}   mean loss {np.mean(losses):+.5f}")

    features_chosen = {r.top_feature for r in results}
    print(f"  {len(features_chosen)} distinct features selected across "
          f"{len(results)} fits")
    if len(features_chosen) > len(results) / 2:
        print("  -> selection is unstable across leagues, which is what fitting "
              "noise looks like")
    if better <= len(results) / 2:
        print("\nVerdict: the blend does not earn a place. Nothing is published "
              "from it.")
    else:
        print("\nVerdict: worth a full walk-forward before anything is published.")
