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
    teams = sorted(set(home_ids.tolist()) | set(away_ids.tolist()))
    index = {team: i for i, team in enumerate(teams)}
    n = len(teams)

    hi = np.array([index[t] for t in home_ids])
    ai = np.array([index[t] for t in away_ids])
    weights = np.exp(-xi * days_ago)

    def unpack(params: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
        attack = np.empty(n)
        # Attack strengths are only identified up to a constant, so the last is
        # pinned to make the mean zero rather than left free.
        attack[: n - 1] = params[: n - 1]
        attack[n - 1] = -params[: n - 1].sum()
        defence = params[n - 1 : 2 * n - 1]
        return attack, defence, params[-2], params[-1]

    def negative_log_likelihood(params: np.ndarray) -> float:
        attack, defence, home_adv, rho = unpack(params)
        lam = np.exp(attack[hi] + defence[ai] + home_adv)
        mu = np.exp(attack[ai] + defence[hi])
        lam = np.clip(lam, 1e-8, 30.0)
        mu = np.clip(mu, 1e-8, 30.0)

        ll = (
            home_goals * np.log(lam) - lam
            + away_goals * np.log(mu) - mu
        )

        # Dixon-Coles correction, applied only to the four affected scorelines.
        tau = np.ones_like(lam)
        m00 = (home_goals == 0) & (away_goals == 0)
        m01 = (home_goals == 0) & (away_goals == 1)
        m10 = (home_goals == 1) & (away_goals == 0)
        m11 = (home_goals == 1) & (away_goals == 1)
        tau[m00] = 1.0 - lam[m00] * mu[m00] * rho
        tau[m01] = 1.0 + lam[m01] * rho
        tau[m10] = 1.0 + mu[m10] * rho
        tau[m11] = 1.0 - rho
        # A parameter set implying a negative probability is infeasible.
        if np.any(tau <= 0):
            return 1e10
        ll = ll + np.log(tau)
        return float(-np.sum(weights * ll))

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
        negative_log_likelihood, start, method="L-BFGS-B", bounds=bounds,
        options={"maxiter": 400, "ftol": 1e-9},
    )
    attack, defence, home_adv, rho = unpack(result.x)
    return Fitted(
        teams=teams,
        attack={t: float(attack[index[t]]) for t in teams},
        defence={t: float(defence[index[t]]) for t in teams},
        home_advantage=float(home_adv),
        rho=float(rho),
        n_matches=len(home_ids),
    )
