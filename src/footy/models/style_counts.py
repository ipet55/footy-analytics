"""Does style of play improve the count markets?

Pressing has a mechanism here that it does not have for goals. A side that hunts
the ball high up the pitch commits more fouls, and fouls become cards; a side
that sits deep concedes territory and wins fewer corners. The count models see
none of that directly — like Dixon-Coles they reduce a team to a rate for
producing the statistic and a rate for conceding it.

The correction is the same shape as in `style_check`, multiplicative on the
fitted rate with one shared pair of coefficients per feature across venues, and
the same intercept-only control to separate a real gain from recalibration.

Scoring is the held-out negative log-likelihood of the observed team count under
the model's own distribution, which avoids having to nominate a line, plus the
log-loss at a representative team line for something interpretable. The
correction itself is fitted as a Poisson regression even where the count model is
negative binomial: only the mean is being corrected, and Poisson scoring
estimates a mean structure consistently whatever the dispersion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from scipy.optimize import minimize

from footy.models import counts as cm
from footy.models import counts_backtest as cb
from footy.models import style
from footy.models.style_check import (
    LEAGUES,
    VARIANTS,
    clustered_test,
)

# Monthly rather than fortnightly. The walk covers a decade in five leagues for
# two statistics, and the count models carry a hundred-odd parameters each.
REFIT_DAYS = 28

# Headline variant, chosen before seeing results: pressing is the dimension with
# a mechanism behind it and the fewest parameters.
HEADLINE = "press"

# Team lines used for the interpretable second metric.
TEAM_LINE = {"fouls": 10.5, "cards": 1.5, "corners": 4.5, "shots": 12.5}


@dataclass
class Observation:
    kickoff: date
    home_rate: float
    away_rate: float
    dispersion: float | None
    home_features: dict[str, float]
    away_features: dict[str, float]
    home_count: float
    away_count: float

    def row(self, features: tuple[str, ...], home: bool) -> list[float]:
        mine = self.home_features if home else self.away_features
        theirs = self.away_features if home else self.home_features
        return [v for f in features for v in (mine[f], theirs[f])]

    def sides(self):
        yield self.home_rate, self.home_count, True
        yield self.away_rate, self.away_count, False


def collect(stat: str, competition: str, features_from: date) -> list[Observation]:
    """Walk forward, recording what the count model expected and how each side plays."""
    spec = cm.SPECS[stat]
    matches = cb.load(stat, competition)
    if not matches:
        raise RuntimeError(f"no {stat} for {competition}")
    feats = style.build(style.load(competition))
    test = [m for m in matches if m.kickoff >= features_from]

    out: list[Observation] = []
    fitted: cm.FittedCount | None = None
    last: date | None = None
    for m in test:
        if fitted is None or last is None or (m.kickoff - last) >= timedelta(
            days=REFIT_DAYS
        ):
            history = [h for h in matches if h.kickoff < m.kickoff]
            fitted = cm.fit(
                np.array([h.home_id for h in history]),
                np.array([h.away_id for h in history]),
                np.array([h.home_count for h in history], float),
                np.array([h.away_count for h in history], float),
                np.array([(m.kickoff - h.kickoff).days for h in history], float),
                spec,
                cb._referees(history, spec),
            )
            last = m.kickoff

        home = feats.get((m.match_id, m.home_id))
        away = feats.get((m.match_id, m.away_id))
        if not (home and away):
            continue
        home_rate, away_rate = fitted.rates(m.home_id, m.away_id, m.referee_id)
        out.append(
            Observation(
                kickoff=m.kickoff, home_rate=home_rate, away_rate=away_rate,
                dispersion=fitted.dispersion,
                home_features=home, away_features=away,
                home_count=m.home_count, away_count=m.away_count,
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
            return o.home_rate * factor, o.away_rate * factor
        home = (np.array(o.row(self.features, True)) - self.mean) / self.sd
        away = (np.array(o.row(self.features, False)) - self.mean) / self.sd
        return (
            float(o.home_rate * np.exp(self.beta[0] + home @ self.beta[1:])),
            float(o.away_rate * np.exp(self.beta[0] + away @ self.beta[1:])),
        )


def fit_correction(train: list[Observation], features: tuple[str, ...]) -> Correction:
    y = np.array([c for o in train for c in (o.home_count, o.away_count)], float)
    offset = np.array([np.log(r) for o in train for r in (o.home_rate, o.away_rate)])
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


def _clip(p: float) -> float:
    return min(max(p, 1e-9), 1 - 1e-9)


@dataclass
class Season:
    stat: str
    competition: str
    year: int
    n: int
    nll: dict[str, float] = field(default_factory=dict)
    line: dict[str, float] = field(default_factory=dict)

    def gain(self, label: str = HEADLINE) -> float:
        return self.nll["plain"] - self.nll[label]


def run(stat: str, competition: str, features_from: date,
        seasons: tuple[int, ...]) -> list[Season]:
    observations = collect(stat, competition, features_from)
    line = TEAM_LINE[stat]
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
        nll = dict.fromkeys(VARIANTS, 0.0)
        line_ll = dict.fromkeys(VARIANTS, 0.0)
        n = 0

        for o in test:
            for label in nll:
                if label == "plain":
                    rates = (o.home_rate, o.away_rate)
                else:
                    rates = corrections[label].rates(o)
                for rate, (_, count, _is_home) in zip(rates, o.sides()):
                    pmf = cm.count_pmf(rate, o.dispersion)
                    k = int(min(count, len(pmf) - 1))
                    nll[label] -= np.log(_clip(float(pmf[k])))
                    p = cm.over_probability(pmf, line)
                    over = count > line
                    line_ll[label] -= np.log(_clip(p if over else 1 - p))
            n += 2

        results.append(Season(
            stat=stat, competition=competition, year=year, n=n,
            nll={k: v / n for k, v in nll.items()},
            line={k: v / n for k, v in line_ll.items()},
        ))
    return results


def report(results: list[Season], stat: str) -> None:
    from rich.console import Console
    from rich.table import Table

    if not results:
        return
    console = Console()
    labels = [k for k in VARIANTS if k != "plain"]
    n = sum(r.n for r in results)
    pooled = {k: sum(r.nll[k] * r.n for r in results) / n for k in VARIANTS}
    pooled_line = {k: sum(r.line[k] * r.n for r in results) / n for k in VARIANTS}

    table = Table(
        title=f"Style of play and {stat}. Gain in held-out log-likelihood per "
              f"team-match; positive means style helped."
    )
    table.add_column("league")
    table.add_column("team-matches", justify="right")
    table.add_column("plain", justify="right")
    for col in labels:
        table.add_column(f"{col} gain", justify="right")

    for competition in LEAGUES:
        rows = [r for r in results if r.competition == competition]
        if not rows:
            continue
        n_league = sum(r.n for r in rows)
        pooled_league = {
            k: sum(r.nll[k] * r.n for r in rows) / n_league for k in VARIANTS
        }
        table.add_row(
            competition, f"{n_league}", f"{pooled_league['plain']:.4f}",
            *(f"{pooled_league['plain'] - pooled_league[k]:+.4f}" for k in labels),
        )
    table.add_section()
    table.add_row(
        "POOLED", f"{n}", f"{pooled['plain']:.4f}",
        *(f"{pooled['plain'] - pooled[k]:+.4f}" for k in labels),
    )
    console.print(table)

    summary = Table(title=f"{stat}: pooled over every league and held-out season")
    for col in ("variant", "params", "NLL gain", "p season", "p league", "won",
                f"over {TEAM_LINE[stat]} gain"):
        summary.add_column(col, justify="right" if col != "variant" else "left")
    for label in labels:
        _, season_p, _ = clustered_test(results, lambda r: r.year, label)
        _, league_p, _ = clustered_test(results, lambda r: r.competition, label)
        won = sum(1 for r in results if r.gain(label) > 0)
        summary.add_row(
            label, f"{2 * len(VARIANTS[label]) + 1}",
            f"{pooled['plain'] - pooled[label]:+.4f}",
            f"{season_p:.3f}", f"{league_p:.3f}",
            f"{won}/{len(results)}",
            f"{pooled_line['plain'] - pooled_line[label]:+.4f}",
        )
    console.print(summary)
