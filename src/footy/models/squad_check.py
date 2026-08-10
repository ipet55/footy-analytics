"""Does knowing the eleven improve the goals model? Measured, and it does.

The first thing in this project that has. The feature blend and per-team home
advantage were both built, measured and rejected; this one replicates across
every held-out season, so it gets a harness rather than an obituary.

The correction is multiplicative on the fitted rate, which makes the plain model
the special case where every coefficient is zero:

    home rate = dixon_coles_rate * exp(a + b1*continuity_home + b2*continuity_away)
    away rate = dixon_coles_rate * exp(a + b1*continuity_away + b2*continuity_home)

One shared pair of coefficients for both sides, not two. Whatever a depleted
eleven does to a team's scoring, it should do whether the team is at home or
away, and halving the parameters halves the chance of fitting noise — the
mistake that sank the blend.

The intercept is the control that matters. It absorbs any global bias in the
fitted rates, so without it a gain from plain recalibration would masquerade as
a gain from squad strength. Running the intercept alone is how we know it does
not: it accounts for none of the improvement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

from footy.models import backtest as gb
from footy.models import dixon_coles as dc
from footy.models import squad

# The feature the correction uses. Continuity beat every other combination
# tried, including adding absent key players, which is the same finding as
# everywhere else here: fewer parameters win.
FEATURE = "xi_continuity"

REFIT_DAYS = 14


@dataclass
class Observation:
    """One match, with the model's rates and both sides' squad state."""

    kickoff: date
    lam: float
    mu: float
    rho: float
    continuity_home: float
    continuity_away: float
    home_goals: int
    away_goals: int
    market: tuple[float, float, float] | None

    def outcome(self) -> int:
        if self.home_goals > self.away_goals:
            return 0
        return 1 if self.home_goals == self.away_goals else 2


def collect(competition: str, features_from: date) -> list[Observation]:
    """Walk forward, recording what the team model expected and who played."""
    appearances = squad.load(competition)
    if not appearances:
        raise RuntimeError(
            f"no team sheets for {competition}; run `footy load-lineups` first"
        )
    feats = squad.build(appearances)
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
                continuity_home=home[FEATURE], continuity_away=away[FEATURE],
                home_goals=m.home_goals, away_goals=m.away_goals, market=m.market,
            )
        )
    return out


@dataclass
class Correction:
    beta: np.ndarray
    mean: np.ndarray
    sd: np.ndarray
    with_features: bool

    def rates(self, o: Observation) -> tuple[float, float]:
        if not self.with_features:
            factor = float(np.exp(self.beta[0]))
            return o.lam * factor, o.mu * factor
        home = (np.array([o.continuity_home, o.continuity_away]) - self.mean) / self.sd
        away = (np.array([o.continuity_away, o.continuity_home]) - self.mean) / self.sd
        return (
            float(o.lam * np.exp(self.beta[0] + home @ self.beta[1:])),
            float(o.mu * np.exp(self.beta[0] + away @ self.beta[1:])),
        )


def fit_correction(train: list[Observation], with_features: bool) -> Correction:
    """Poisson fit of goals scored, with the model's own rate as the offset.

    Both sides of every match are rows, with the features swapped for the away
    row, which is what shares one pair of coefficients across venues.
    """
    y = np.array([g for o in train for g in (o.home_goals, o.away_goals)], float)
    offset = np.array([np.log(r) for o in train for r in (o.lam, o.mu)])
    Z = np.array([
        z for o in train
        for z in ([o.continuity_home, o.continuity_away],
                  [o.continuity_away, o.continuity_home])
    ])
    mean, sd = Z.mean(0), Z.std(0)
    design = np.column_stack(
        [np.ones(len(y))] + ([(Z - mean) / sd] if with_features else [])
    )

    def objective(b):
        eta = offset + design @ b
        rate = np.exp(np.clip(eta, -20, 20))
        return float(np.sum(rate - y * eta)), design.T @ (rate - y)

    beta = minimize(
        objective, np.zeros(design.shape[1]), jac=True, method="L-BFGS-B"
    ).x
    return Correction(beta=beta, mean=mean, sd=sd, with_features=with_features)


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
    year: int
    n: int
    plain: float
    intercept_only: float
    with_squad: float
    plain_ou: float
    with_squad_ou: float
    market: float | None


def run(competition: str = "ENG-PL", features_from: date = date(2021, 8, 1),
        seasons: tuple[int, ...] = (2022, 2023, 2024)) -> list[Season]:
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
            "intercept_only": fit_correction(train, with_features=False),
            "with_squad": fit_correction(train, with_features=True),
        }
        totals = dict.fromkeys(("plain", "intercept_only", "with_squad"), 0.0)
        ou = dict.fromkeys(("plain", "with_squad"), 0.0)
        market, n_market = 0.0, 0

        for o in test:
            outcome, over = o.outcome(), (o.home_goals + o.away_goals) > 2.5
            for label in totals:
                lam, mu = (
                    (o.lam, o.mu) if label == "plain"
                    else corrections[label].rates(o)
                )
                matrix = score_matrix(lam, mu, o.rho)
                totals[label] -= np.log(
                    _clip(dc.outcome_probabilities(matrix)[outcome])
                )
                if label in ou:
                    p = dc.over_probability(matrix, 2.5)
                    ou[label] -= np.log(_clip(p if over else 1 - p))
            if o.market:
                market -= np.log(_clip(o.market[outcome]))
                n_market += 1

        n = len(test)
        results.append(Season(
            year=year, n=n,
            plain=totals["plain"] / n,
            intercept_only=totals["intercept_only"] / n,
            with_squad=totals["with_squad"] / n,
            plain_ou=ou["plain"] / n,
            with_squad_ou=ou["with_squad"] / n,
            market=(market / n_market if n_market else None),
        ))
    return results


def report(results: list[Season]) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Does knowing the eleven help? 1X2 log-loss, lower is better")
    for col in ("holdout", "matches", "plain", "intercept only", "with squad",
                "gain", "O/U gain", "market"):
        table.add_column(col, justify="right" if col != "holdout" else "left")

    n = sum(r.n for r in results)
    for r in results:
        table.add_row(
            f"{r.year}-{(r.year + 1) % 100:02d}", f"{r.n}",
            f"{r.plain:.4f}", f"{r.intercept_only:.4f}", f"{r.with_squad:.4f}",
            f"{r.plain - r.with_squad:+.4f}",
            f"{r.plain_ou - r.with_squad_ou:+.4f}",
            f"{r.market:.4f}" if r.market else "-",
        )
    if results:
        w = lambda f: sum(f(r) * r.n for r in results) / n
        table.add_section()
        table.add_row(
            "POOLED", f"{n}", f"{w(lambda r: r.plain):.4f}",
            f"{w(lambda r: r.intercept_only):.4f}", f"{w(lambda r: r.with_squad):.4f}",
            f"{w(lambda r: r.plain - r.with_squad):+.4f}",
            f"{w(lambda r: r.plain_ou - r.with_squad_ou):+.4f}",
            f"{w(lambda r: r.market or 0):.4f}",
        )
    console.print(table)

    if not results:
        return
    w = lambda f: sum(f(r) * r.n for r in results) / n
    recalibration = w(lambda r: r.plain - r.intercept_only)
    total = w(lambda r: r.plain - r.with_squad)
    console.print(
        f"\nOf the {total:+.4f} gain, recalibration accounts for {recalibration:+.4f} "
        f"and the squad features for {total - recalibration:+.4f}."
    )
    console.print(
        "The market column is the closing line, which already knows the lineups, "
        "so this is ground gained on a benchmark that had the same information."
    )
