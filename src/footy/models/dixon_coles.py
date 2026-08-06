"""Dixon-Coles: the standard baseline for football scorelines.

Each team gets an attack and a defence strength. Expected goals for a fixture are

    home rate = exp(attack_home + defence_away + home_advantage)
    away rate = exp(attack_away + defence_home)

and the scoreline is two Poisson draws, with one correction. Independent Poissons
understate draws and low-scoring games, because goals in a real match are not
independent events, so Dixon and Coles reweight the 0-0, 1-0, 0-1 and 1-1 cells
by a fitted parameter.

Older matches are down-weighted exponentially. A team's form two years ago says
much less about it than last month, and without decay the model is an average of
squads that no longer exist.

The output is a full score matrix, which is what makes every market coherent: the
1X2 probabilities, over/under on any line, both-teams-to-score and correct score
are all sums over the same matrix, so they cannot contradict each other.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

MAX_GOALS = 10


@dataclass
class Fitted:
    teams: list[int]
    attack: dict[int, float]
    defence: dict[int, float]
    home_advantage: float
    rho: float
    n_matches: int

    def rates(self, home_team: int, away_team: int) -> tuple[float, float]:
        # A team absent from training sits at the league average, which is what
        # attack = defence = 0 means once the parameters are centred.
        ah = self.attack.get(home_team, 0.0)
        dh = self.defence.get(home_team, 0.0)
        aa = self.attack.get(away_team, 0.0)
        da = self.defence.get(away_team, 0.0)
        return (
            float(np.exp(ah + da + self.home_advantage)),
            float(np.exp(aa + dh)),
        )

    def score_matrix(self, home_team: int, away_team: int) -> np.ndarray:
        lam, mu = self.rates(home_team, away_team)
        home = poisson.pmf(np.arange(MAX_GOALS + 1), lam)
        away = poisson.pmf(np.arange(MAX_GOALS + 1), mu)
        matrix = np.outer(home, away)
        matrix[0, 0] *= 1.0 - lam * mu * self.rho
        matrix[0, 1] *= 1.0 + lam * self.rho
        matrix[1, 0] *= 1.0 + mu * self.rho
        matrix[1, 1] *= 1.0 - self.rho
        total = matrix.sum()
        return matrix / total if total > 0 else matrix


def outcome_probabilities(matrix: np.ndarray) -> tuple[float, float, float]:
    """Home win, draw, away win."""
    home = float(np.tril(matrix, -1).sum())
    draw = float(np.trace(matrix))
    away = float(np.triu(matrix, 1).sum())
    return home, draw, away


def over_probability(matrix: np.ndarray, line: float) -> float:
    """P(total goals > line). Lines are halves, so no tie handling is needed."""
    totals = np.add.outer(np.arange(MAX_GOALS + 1), np.arange(MAX_GOALS + 1))
    return float(matrix[totals > line].sum())


def team_over_probability(matrix: np.ndarray, line: float, home: bool) -> float:
    """P(this team's goals > line), used for the per-team goal markets."""
    goals = np.arange(MAX_GOALS + 1)
    per_team = matrix.sum(axis=1 if home else 0)
    return float(per_team[goals > line].sum())


def btts_probability(matrix: np.ndarray) -> float:
    return float(matrix[1:, 1:].sum())


@dataclass(frozen=True)
class Design:
    """A training set reduced to what the likelihood needs: teams as contiguous
    indices, each match's time-decay weight, and the four low-score masks the
    Dixon-Coles correction applies to, precomputed once instead of per iteration."""

    teams: list[int]
    index: dict[int, int]
    home: np.ndarray
    away: np.ndarray
    home_goals: np.ndarray
    away_goals: np.ndarray
    weights: np.ndarray
    m00: np.ndarray
    m01: np.ndarray
    m10: np.ndarray
    m11: np.ndarray

    @property
    def n_teams(self) -> int:
        return len(self.teams)


def build_design(
    home_ids: np.ndarray,
    away_ids: np.ndarray,
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    days_ago: np.ndarray,
    xi: float = 0.0018,
) -> Design:
    teams = sorted(set(home_ids.tolist()) | set(away_ids.tolist()))
    index = {team: i for i, team in enumerate(teams)}
    return Design(
        teams=teams,
        index=index,
        home=np.array([index[t] for t in home_ids]),
        away=np.array([index[t] for t in away_ids]),
        home_goals=np.asarray(home_goals, float),
        away_goals=np.asarray(away_goals, float),
        weights=np.exp(-xi * days_ago),
        m00=(home_goals == 0) & (away_goals == 0),
        m01=(home_goals == 0) & (away_goals == 1),
        m10=(home_goals == 1) & (away_goals == 0),
        m11=(home_goals == 1) & (away_goals == 1),
    )


def unpack(params: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray, float, float]:
    attack = np.empty(n)
    # Attack strengths are only identified up to a constant, so the last is
    # pinned to make the mean zero rather than left free.
    attack[: n - 1] = params[: n - 1]
    attack[n - 1] = -params[: n - 1].sum()
    defence = params[n - 1 : 2 * n - 1]
    return attack, defence, params[-2], params[-1]


def objective(params: np.ndarray, d: Design) -> tuple[float, np.ndarray]:
    """Negative log-likelihood and its gradient.

    Supplying the derivatives rather than letting L-BFGS-B estimate them costs
    one extra likelihood evaluation per parameter per iteration, and there are
    2n+1 parameters for n teams. On the Premier League this is the difference
    between a walk-forward backtest taking minutes and taking seconds.

    Both Poisson rates enter through their logarithms, where the derivative of
    the uncorrected likelihood is just the residual, goals minus expected goals.
    The rho correction only touches four scorelines, so its contribution is
    assembled per mask.
    """
    n = d.n_teams
    attack, defence, home_adv, rho = unpack(params, n)
    lam = np.clip(np.exp(attack[d.home] + defence[d.away] + home_adv), 1e-8, 30.0)
    mu = np.clip(np.exp(attack[d.away] + defence[d.home]), 1e-8, 30.0)

    tau = np.ones_like(lam)
    tau[d.m00] = 1.0 - lam[d.m00] * mu[d.m00] * rho
    tau[d.m01] = 1.0 + lam[d.m01] * rho
    tau[d.m10] = 1.0 + mu[d.m10] * rho
    tau[d.m11] = 1.0 - rho
    if np.any(tau <= 0):
        # This rho implies a negative probability for some observed scoreline.
        # Report it as terrible and point the gradient back toward rho = 0,
        # which is always feasible, rather than returning a flat gradient the
        # optimiser would mistake for a minimum.
        grad = np.zeros_like(params)
        grad[-1] = 1e3 if rho > 0 else -1e3
        return 1e10, grad

    ll = (
        d.home_goals * np.log(lam) - lam
        + d.away_goals * np.log(mu) - mu
        + np.log(tau)
    )
    value = float(-np.sum(d.weights * ll))

    # d log(tau) / d log(lam), d log(tau) / d log(mu), d log(tau) / d rho.
    dtau_dloglam = np.zeros_like(lam)
    dtau_dlogmu = np.zeros_like(lam)
    dtau_drho = np.zeros_like(lam)
    joint = lam[d.m00] * mu[d.m00] * rho
    dtau_dloglam[d.m00] = -joint
    dtau_dlogmu[d.m00] = -joint
    dtau_drho[d.m00] = -lam[d.m00] * mu[d.m00]
    dtau_dloglam[d.m01] = lam[d.m01] * rho
    dtau_drho[d.m01] = lam[d.m01]
    dtau_dlogmu[d.m10] = mu[d.m10] * rho
    dtau_drho[d.m10] = mu[d.m10]
    dtau_drho[d.m11] = -1.0

    gl = d.weights * (d.home_goals - lam + dtau_dloglam / tau)
    gm = d.weights * (d.away_goals - mu + dtau_dlogmu / tau)

    grad = np.zeros_like(params)
    # A team's attack drives the goals it scores at either venue; its defence
    # drives the goals its opponent scores. Hence the crossed group sums.
    attack_grad = (
        np.bincount(d.home, weights=gl, minlength=n)
        + np.bincount(d.away, weights=gm, minlength=n)
    )
    defence_grad = (
        np.bincount(d.away, weights=gl, minlength=n)
        + np.bincount(d.home, weights=gm, minlength=n)
    )
    grad[: n - 1] = -(attack_grad[: n - 1] - attack_grad[n - 1])
    grad[n - 1 : 2 * n - 1] = -defence_grad
    grad[-2] = -gl.sum()  # home advantage shifts only the home rate
    grad[-1] = -float(np.sum(d.weights * dtau_drho / tau))
    return value, grad


def fit(
    home_ids: np.ndarray,
    away_ids: np.ndarray,
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    days_ago: np.ndarray,
    xi: float = 0.0018,
) -> Fitted:
    """Maximum likelihood fit with exponential time decay.

    xi is the decay rate per day. 0.0018 halves a match's weight after roughly
    a year, which is the range Dixon and Coles found and a reasonable default
    before tuning.
    """
    d = build_design(home_ids, away_ids, home_goals, away_goals, days_ago, xi)
    n = d.n_teams

    start = np.concatenate([
        np.zeros(n - 1),      # attack, minus the pinned one
        np.zeros(n),          # defence
        [0.25],               # home advantage
        [-0.05],              # rho
    ])
    bounds = (
        [(-3.0, 3.0)] * (n - 1)
        + [(-3.0, 3.0)] * n
        + [(-1.0, 1.0), (-0.2, 0.2)]
    )
    result = minimize(
        objective, start, args=(d,), method="L-BFGS-B", jac=True, bounds=bounds,
        options={"maxiter": 400, "ftol": 1e-9},
    )
    attack, defence, home_adv, rho = unpack(result.x, n)
    teams, index = d.teams, d.index
    return Fitted(
        teams=teams,
        attack={t: float(attack[index[t]]) for t in teams},
        defence={t: float(defence[index[t]]) for t in teams},
        home_advantage=float(home_adv),
        rho=float(rho),
        n_matches=len(home_ids),
    )
