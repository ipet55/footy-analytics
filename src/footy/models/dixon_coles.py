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

One home advantage for the whole league says every team travels equally badly,
which is false: some sides are transformed at home and some barely notice. Set
venue_penalty and each team also gets its own home deviation, one for attack and
one for defence, so "solid at home, porous away" becomes something the model can
say rather than something it averages away. Those deviations are shrunk toward
zero, because a team plays only nineteen home games a season and the difference
between a real venue effect and a kind fixture list is mostly sample size. The
penalty makes this a strict superset of the plain model: send it to infinity and
the deviations vanish, which is what makes the two directly comparable.

The output is a full score matrix, which is what makes every market coherent: the
1X2 probabilities, over/under on any line, both-teams-to-score and correct score
are all sums over the same matrix, so they cannot contradict each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

MAX_GOALS = 10

# How hard attack and defence are pulled toward the league average, per effective
# match. Chosen on 2022-24 across nine leagues and confirmed on 2024-26, which was
# not used to choose it: it improves eight of the nine and costs England 0.0007.
# The optimum is interior — 0.20 and 0.40 are both worse — so this is a minimum
# rather than the edge of the range that happened to be searched.
# docs/10-strength-shrinkage.md has the tables.
SHRINKAGE = 0.10


@dataclass
class Fitted:
    teams: list[int]
    attack: dict[int, float]
    defence: dict[int, float]
    home_advantage: float
    rho: float
    n_matches: int
    # Per-team deviations from the league home advantage, applied only to the
    # side playing at home. Empty when the model was fitted without them.
    venue_attack: dict[int, float] = field(default_factory=dict)
    venue_defence: dict[int, float] = field(default_factory=dict)
    # What a team absent from training gets: the average of the fitted values,
    # which is what "the league average" actually means. Only attack is centred
    # on zero by the fit; defence is not, so defaulting it to zero understated
    # every promoted club's opponent by around 18%. Set by `fit`.
    attack_default: float = 0.0
    defence_default: float = 0.0

    def rates(self, home_team: int, away_team: int) -> tuple[float, float]:
        # A promoted club has no parameters of its own and sits at the league
        # average. That is a neutral prior rather than a good one — promoted teams
        # are systematically weaker than average — but it is the honest default
        # when the team has never played in the league we have data for.
        ah = self.attack.get(home_team, self.attack_default)
        dh = self.defence.get(home_team, self.defence_default)
        aa = self.attack.get(away_team, self.attack_default)
        da = self.defence.get(away_team, self.defence_default)
        # Only the home side gets a venue term; the away side's own deviations
        # describe its home matches, not this one.
        va = self.venue_attack.get(home_team, 0.0)
        vd = self.venue_defence.get(home_team, 0.0)
        return (
            float(np.exp(ah + va + da + self.home_advantage)),
            float(np.exp(aa + dh + vd)),
        )

    def score_matrix(
        self,
        home_team: int,
        away_team: int,
        home_mult: float = 1.0,
        away_mult: float = 1.0,
    ) -> np.ndarray:
        lam, mu = self.rates(home_team, away_team)
        lam *= home_mult
        mu *= away_mult
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
    # None fits one home advantage for the league. A number adds a per-team
    # deviation on top and is the weight of the L2 penalty holding it down.
    venue_penalty: float | None = None
    # Weight of the L2 penalty pulling attack and defence toward the league
    # average. Scaled against the total time-decayed weight of the training set,
    # so it means the same thing whether a league has 400 effective matches or
    # 40, and so it does not quietly strengthen as history accumulates.
    strength_penalty: float = 0.0

    @property
    def n_teams(self) -> int:
        return len(self.teams)

    @property
    def n_venue(self) -> int:
        """Venue parameters per block: n when they are fitted, 0 when they are not."""
        return 0 if self.venue_penalty is None else len(self.teams)


def build_design(
    home_ids: np.ndarray,
    away_ids: np.ndarray,
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    days_ago: np.ndarray,
    xi: float = 0.0018,
    venue_penalty: float | None = None,
    shrinkage: float = SHRINKAGE,
) -> Design:
    teams = sorted(set(home_ids.tolist()) | set(away_ids.tolist()))
    index = {team: i for i, team in enumerate(teams)}
    weights = np.exp(-xi * np.asarray(days_ago, float))
    # Expressed per effective match, so the penalty is the same strength in a
    # league with a decade of history as in one with two seasons. A flat constant
    # would shrink a short history hard and a long one not at all.
    strength_penalty = shrinkage * float(weights.sum()) / max(len(teams), 1)
    return Design(
        teams=teams,
        index=index,
        home=np.array([index[t] for t in home_ids]),
        away=np.array([index[t] for t in away_ids]),
        home_goals=np.asarray(home_goals, float),
        away_goals=np.asarray(away_goals, float),
        weights=weights,
        m00=(home_goals == 0) & (away_goals == 0),
        m01=(home_goals == 0) & (away_goals == 1),
        m10=(home_goals == 1) & (away_goals == 0),
        m11=(home_goals == 1) & (away_goals == 1),
        venue_penalty=venue_penalty,
        strength_penalty=strength_penalty,
    )


def unpack(
    params: np.ndarray, d: Design
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, float]:
    n = d.n_teams
    attack = np.empty(n)
    # Attack strengths are only identified up to a constant, so the last is
    # pinned to make the mean zero rather than left free.
    attack[: n - 1] = params[: n - 1]
    attack[n - 1] = -params[: n - 1].sum()
    defence = params[n - 1 : 2 * n - 1]
    if d.n_venue:
        offset = 2 * n - 1
        venue_attack = params[offset : offset + n]
        venue_defence = params[offset + n : offset + 2 * n]
    else:
        venue_attack = venue_defence = np.zeros(n)
    # The venue terms would trade off against the league home advantage were
    # they free; the penalty pulls them to zero, which leaves the shared term
    # to carry the average and makes the split identified.
    return attack, defence, venue_attack, venue_defence, params[-2], params[-1]


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
    attack, defence, venue_attack, venue_defence, home_adv, rho = unpack(params, d)
    lam = np.clip(
        np.exp(attack[d.home] + venue_attack[d.home] + defence[d.away] + home_adv),
        1e-8, 30.0,
    )
    mu = np.clip(
        np.exp(attack[d.away] + defence[d.home] + venue_defence[d.home]), 1e-8, 30.0
    )

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
    if d.strength_penalty:
        # Shrink attack and defence toward the league average. Without this a
        # promoted club is fitted almost entirely to its first match, because
        # time decay gives a game played last week a weight of 1.0 against
        # 0.0004 for one from 2014 — so a single recent win outweighs thousands
        # of old matches and nothing pulls it back. Académico de Viseu came out
        # with the strongest attack in Portugal, ahead of Benfica, on one game,
        # and was priced to score 3.67 at home where Porto would score 1.88.
        #
        # The count models already shrink referee effects for the same reason,
        # stated the same way: some officials appear a handful of times and their
        # raw averages are noise.
        value += d.strength_penalty * float(np.sum(attack**2) + np.sum(defence**2))
    if d.n_venue:
        value += d.venue_penalty * float(
            np.sum(venue_attack**2) + np.sum(venue_defence**2)
        )

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
    if d.strength_penalty:
        # d/d attack_i of penalty * sum(attack^2). The pinned team's parameter is
        # -sum(the others), so its share of the penalty reaches every free one
        # with the opposite sign — the same chain rule the likelihood term above
        # applies to attack_grad.
        pen = 2.0 * d.strength_penalty
        attack_grad = attack_grad - pen * attack
        defence_grad = defence_grad - pen * defence
    grad[: n - 1] = -(attack_grad[: n - 1] - attack_grad[n - 1])
    grad[n - 1 : 2 * n - 1] = -defence_grad
    if d.n_venue:
        # A team's venue terms only bite in its own home matches: the attack one
        # on the goals it scores there, the defence one on the goals it lets in.
        offset = 2 * n - 1
        grad[offset : offset + n] = (
            -np.bincount(d.home, weights=gl, minlength=n)
            + 2.0 * d.venue_penalty * venue_attack
        )
        grad[offset + n : offset + 2 * n] = (
            -np.bincount(d.home, weights=gm, minlength=n)
            + 2.0 * d.venue_penalty * venue_defence
        )
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
    venue_penalty: float | None = None,
    shrinkage: float = SHRINKAGE,
) -> Fitted:
    """Maximum likelihood fit with exponential time decay.

    xi is the decay rate per day. 0.0018 halves a match's weight after roughly
    a year, which is the range Dixon and Coles found and a reasonable default
    before tuning.

    venue_penalty turns on per-team home deviations and sets how hard they are
    shrunk. None leaves them out entirely.

    shrinkage pulls attack and defence toward the league average, in proportion
    to how little effective data a team has. Set it to zero for the unpenalised
    maximum likelihood fit, which is what the model did before newly promoted
    clubs turned out to be rated off a single match.
    """
    d = build_design(
        home_ids, away_ids, home_goals, away_goals, days_ago, xi, venue_penalty,
        shrinkage,
    )
    n = d.n_teams

    start = np.concatenate([
        np.zeros(n - 1),          # attack, minus the pinned one
        np.zeros(n),              # defence
        np.zeros(2 * d.n_venue),  # venue deviations, attack then defence
        [0.25],                   # home advantage
        [-0.05],                  # rho
    ])
    bounds = (
        [(-3.0, 3.0)] * (n - 1)
        + [(-3.0, 3.0)] * n
        + [(-1.0, 1.0)] * (2 * d.n_venue)
        + [(-1.0, 1.0), (-0.2, 0.2)]
    )
    result = minimize(
        objective, start, args=(d,), method="L-BFGS-B", jac=True, bounds=bounds,
        options={"maxiter": 400, "ftol": 1e-9},
    )
    attack, defence, venue_attack, venue_defence, home_adv, rho = unpack(result.x, d)
    teams, index = d.teams, d.index
    return Fitted(
        teams=teams,
        attack={t: float(attack[index[t]]) for t in teams},
        defence={t: float(defence[index[t]]) for t in teams},
        attack_default=float(attack.mean()),
        defence_default=float(defence.mean()),
        home_advantage=float(home_adv),
        rho=float(rho),
        n_matches=len(home_ids),
        venue_attack=(
            {t: float(venue_attack[index[t]]) for t in teams} if d.n_venue else {}
        ),
        venue_defence=(
            {t: float(venue_defence[index[t]]) for t in teams} if d.n_venue else {}
        ),
    )
