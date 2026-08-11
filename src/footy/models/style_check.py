"""Does knowing how a team plays improve the goals model?

Same harness as `squad_check`, and deliberately so: a multiplicative correction
on the fitted Dixon-Coles rate, one shared pair of coefficients per feature
across venues, and an intercept-only variant as the control that separates a real
gain from plain recalibration.

    home rate = dc_rate * exp(a + b1*press_home + b2*press_away + ...)
    away rate = dc_rate * exp(a + b1*press_away + b2*press_home + ...)

Two things are different, both learned from the squad-strength false positive.

The holdout is wider. Style data reaches back to 2014-15 with full coverage in
all five leagues, so every league contributes seven held-out seasons instead of
England contributing three. That is thirty-five league-seasons rather than three,
which is the difference between a result and an anecdote.

Significance is clustered. League-seasons are not independent trials: the same
team styles persist across seasons, and the same round of fixtures appears in
every league at once. So the pooled gain is tested twice, once treating seasons
as the independent unit and once treating leagues as one, and the honest reading
is the weaker of the two.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson, t

from footy.models import backtest as gb
from footy.models import dixon_coles as dc
from footy.models import style

REFIT_DAYS = 14

LEAGUES = ("ENG-PL", "ESP-LL", "ITA-SA", "GER-BL", "FRA-L1")

# Feature sets to compare. Fewer parameters have won every previous contest in
# this project, so the single-dimension variants are the ones to beat.
VARIANTS: dict[str, tuple[str, ...]] = {
    "plain": (),
    "intercept": (),
    "press": ("press",),
    "deep": ("deep_for", "deep_against"),
    "all": ("press", "deep_for", "deep_against"),
    # Recent style against the team's own baseline rather than the level of it.
    # See `style.FEATURES` for why this is the variant with a chance: a stable
    # trait is already inside the team's rating, a recent change is not.
    "shift": ("press_delta", "deep_for_delta"),
}

# The variant reported as "the" style model, and the one significance is tested
# on. Chosen before looking at the results: pressing is the dimension with a
# mechanism behind it and the fewest parameters.
HEADLINE = "press"


@dataclass
class Observation:
    """One match, with the model's rates and both sides' style."""

    kickoff: date
    lam: float
    mu: float
    rho: float
    home_features: dict[str, float]
    away_features: dict[str, float]
    home_goals: int
    away_goals: int
    market: tuple[float, float, float] | None

    def row(self, features: tuple[str, ...], home: bool) -> list[float]:
        """Design row for one side, with the two sides' features swapped for the
        away row. That is what shares one pair of coefficients across venues."""
        mine = self.home_features if home else self.away_features
        theirs = self.away_features if home else self.home_features
        return [v for f in features for v in (mine[f], theirs[f])]

    def outcome(self) -> int:
        if self.home_goals > self.away_goals:
            return 0
        return 1 if self.home_goals == self.away_goals else 2


def collect(competition: str, features_from: date) -> list[Observation]:
    """Walk forward, recording what the team model expected and how each side plays."""
    rows = style.load(competition)
    if not rows:
        raise RuntimeError(f"no style figures for {competition}")
    feats = style.build(rows)
    matches = gb.load_matches(competition)
    test = sorted(
        (m for m in matches if m.kickoff >= features_from), key=lambda m: m.kickoff
    )

    out: list[Observation] = []
    fitted: dc.Fitted | None = None
    last: date | None = None
    for m in test:
        if fitted is None or last is None or (m.kickoff - last) >= timedelta(
            days=REFIT_DAYS
        ):
            history = [h for h in matches if h.kickoff < m.kickoff]
            fitted = dc.fit(
                np.array([h.home_id for h in history]),
                np.array([h.away_id for h in history]),
                np.array([h.home_goals for h in history], float),
                np.array([h.away_goals for h in history], float),
                np.array([(m.kickoff - h.kickoff).days for h in history], float),
            )
            last = m.kickoff

        home = feats.get((m.match_id, m.home_id))
        away = feats.get((m.match_id, m.away_id))
        if not (home and away):
            continue
        lam, mu = fitted.rates(m.home_id, m.away_id)
        out.append(
            Observation(
                kickoff=m.kickoff, lam=lam, mu=mu, rho=fitted.rho,
                home_features=home, away_features=away,
                home_goals=m.home_goals, away_goals=m.away_goals, market=m.market,
            )
        )
    return out


@dataclass
class Correction:
    beta: np.ndarray
    mean: np.ndarray
    sd: np.ndarray
    features: tuple[str, ...]

    def rates(self, o: Observation) -> tuple[float, float]:
        if not self.features:
            factor = float(np.exp(self.beta[0]))
            return o.lam * factor, o.mu * factor
        home = (np.array(o.row(self.features, True)) - self.mean) / self.sd
        away = (np.array(o.row(self.features, False)) - self.mean) / self.sd
        return (
            float(o.lam * np.exp(self.beta[0] + home @ self.beta[1:])),
            float(o.mu * np.exp(self.beta[0] + away @ self.beta[1:])),
        )


def fit_correction(train: list[Observation], features: tuple[str, ...]) -> Correction:
    """Poisson fit of goals scored, with the model's own rate as the offset."""
    y = np.array([g for o in train for g in (o.home_goals, o.away_goals)], float)
    offset = np.array([np.log(r) for o in train for r in (o.lam, o.mu)])
    if not features:
        mean = sd = np.zeros(0)
        design = np.ones((len(y), 1))
    else:
        Z = np.array([
            r for o in train
            for r in (o.row(features, True), o.row(features, False))
        ])
        mean, sd = Z.mean(0), Z.std(0)
        sd = np.where(sd > 0, sd, 1.0)
        design = np.column_stack([np.ones(len(y)), (Z - mean) / sd])

    def objective(b):
        eta = offset + design @ b
        rate = np.exp(np.clip(eta, -20, 20))
        return float(np.sum(rate - y * eta)), design.T @ (rate - y)

    beta = minimize(
        objective, np.zeros(design.shape[1]), jac=True, method="L-BFGS-B"
    ).x
    return Correction(beta=beta, mean=mean, sd=sd, features=features)


def score_matrix(lam: float, mu: float, rho: float) -> np.ndarray:
    m = np.outer(
        poisson.pmf(np.arange(dc.MAX_GOALS + 1), lam),
        poisson.pmf(np.arange(dc.MAX_GOALS + 1), mu),
    )
    m[0, 0] *= 1.0 - lam * mu * rho
    m[0, 1] *= 1.0 + lam * rho
    m[1, 0] *= 1.0 + mu * rho
    m[1, 1] *= 1.0 - rho
    total = m.sum()
    return m / total if total > 0 else m


def _clip(p: float) -> float:
    return min(max(p, 1e-6), 1 - 1e-6)


@dataclass
class Season:
    competition: str
    year: int
    n: int
    scores: dict[str, float] = field(default_factory=dict)
    over: dict[str, float] = field(default_factory=dict)
    market: float | None = None

    def gain(self, label: str = HEADLINE) -> float:
        return self.scores["plain"] - self.scores[label]


def run(competition: str, features_from: date,
        seasons: tuple[int, ...]) -> list[Season]:
    """Hold each season out, training the correction only on what came before."""
    observations = collect(competition, features_from)
    results = []
    for year in seasons:
        lo, hi = date(year, 7, 1), date(year + 1, 7, 1)
        test = [o for o in observations if lo <= o.kickoff < hi]
        train = [o for o in observations if o.kickoff < lo]
        if len(test) < 100 or len(train) < 300:
            continue

        corrections = {
            label: fit_correction(train, features)
            for label, features in VARIANTS.items()
            if label != "plain"
        }
        totals = dict.fromkeys(VARIANTS, 0.0)
        over = dict.fromkeys(VARIANTS, 0.0)
        market, n_market = 0.0, 0

        for o in test:
            outcome, is_over = o.outcome(), (o.home_goals + o.away_goals) > 2.5
            for label in totals:
                lam, mu = (
                    (o.lam, o.mu) if label == "plain"
                    else corrections[label].rates(o)
                )
                matrix = score_matrix(lam, mu, o.rho)
                totals[label] -= np.log(
                    _clip(dc.outcome_probabilities(matrix)[outcome])
                )
                p = dc.over_probability(matrix, 2.5)
                over[label] -= np.log(_clip(p if is_over else 1 - p))
            if o.market:
                market -= np.log(_clip(o.market[outcome]))
                n_market += 1

        n = len(test)
        results.append(Season(
            competition=competition, year=year, n=n,
            scores={k: v / n for k, v in totals.items()},
            over={k: v / n for k, v in over.items()},
            market=(market / n_market if n_market else None),
        ))
    return results


def clustered_test(results: list[Season], key, label: str = HEADLINE) -> tuple[float, float, int]:
    """Mean gain and its p-value, treating `key` as the independent unit.

    League-seasons are not independent trials. Averaging the gain within each
    cluster first and testing across clusters is the cheap, honest correction:
    it costs power but it stops the same persistent effect being counted five
    times over.
    """
    groups: dict[object, list[float]] = {}
    for r in results:
        groups.setdefault(key(r), []).append(r.gain(label))
    means = np.array([np.mean(v) for v in groups.values()])
    if len(means) < 2:
        return float(means.mean()), float("nan"), len(means)
    se = means.std(ddof=1) / np.sqrt(len(means))
    if se == 0:
        return float(means.mean()), float("nan"), len(means)
    stat = means.mean() / se
    return float(means.mean()), float(t.sf(stat, len(means) - 1)), len(means)


def report(results: list[Season]) -> None:
    from rich.console import Console
    from rich.table import Table

    if not results:
        return
    console = Console()
    labels = [k for k in VARIANTS if k != "plain"]

    table = Table(
        title="Style of play, 1X2 log-loss against the plain model. "
              "Positive gain means style helped."
    )
    table.add_column("league")
    table.add_column("holdout")
    table.add_column("matches", justify="right")
    table.add_column("plain", justify="right")
    for col in labels:
        table.add_column(f"{col} gain", justify="right")

    for competition in LEAGUES:
        rows = [r for r in results if r.competition == competition]
        if not rows:
            continue
        for r in rows:
            table.add_row(
                competition, f"{r.year}-{(r.year + 1) % 100:02d}", f"{r.n}",
                f"{r.scores['plain']:.4f}",
                *(f"{r.gain(k):+.4f}" for k in labels),
            )
        n_league = sum(r.n for r in rows)
        pooled_league = {
            k: sum(r.scores[k] * r.n for r in rows) / n_league for k in VARIANTS
        }
        table.add_row(
            "", "[dim]league[/dim]", f"[dim]{n_league}[/dim]",
            f"[dim]{pooled_league['plain']:.4f}[/dim]",
            *(f"[bold]{pooled_league['plain'] - pooled_league[k]:+.4f}[/bold]"
              for k in labels),
        )
        table.add_section()

    n = sum(r.n for r in results)
    pooled = {k: sum(r.scores[k] * r.n for r in results) / n for k in VARIANTS}
    table.add_row(
        "POOLED", "", f"{n}", f"{pooled['plain']:.4f}",
        *(f"{pooled['plain'] - pooled[k]:+.4f}" for k in labels),
    )
    console.print(table)

    over_pooled = {k: sum(r.over[k] * r.n for r in results) / n for k in VARIANTS}

    summary = Table(title="Pooled over every league and held-out season")
    for col, justify in (
        ("variant", "left"), ("params", "right"), ("1X2 gain", "right"),
        ("p season", "right"), ("p league", "right"), ("won", "right"),
        ("O/U gain", "right"),
    ):
        summary.add_column(col, justify=justify)
    for label in labels:
        _, season_p, _ = clustered_test(results, lambda r: r.year, label)
        _, league_p, _ = clustered_test(results, lambda r: r.competition, label)
        won = sum(1 for r in results if r.gain(label) > 0)
        summary.add_row(
            label, f"{2 * len(VARIANTS[label]) + 1}",
            f"{pooled['plain'] - pooled[label]:+.4f}",
            f"{season_p:.2f}", f"{league_p:.2f}",
            f"{won}/{len(results)}",
            f"{over_pooled['plain'] - over_pooled[label]:+.4f}",
        )
    console.print(summary)

    recalibration = pooled["plain"] - pooled["intercept"]
    console.print(
        f"\nRecalibration alone accounts for {recalibration:+.4f} of the "
        f"{pooled['plain'] - pooled[HEADLINE]:+.4f} {HEADLINE} gain; "
        f"style for {pooled['intercept'] - pooled[HEADLINE]:+.4f}."
    )
