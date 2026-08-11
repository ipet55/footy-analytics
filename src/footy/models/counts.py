"""Count models for corners, cards, fouls and shots.

Same shape as the goals model — each team has a rate for producing the stat and a
rate for conceding it, plus home advantage — but with two changes that matter.

The distribution is negative binomial rather than Poisson wherever the data is
overdispersed. Measured on this dataset, variance divided by mean is 2.13 for
shots, 1.63 for corners and 1.34 for fouls, against 1.0 for a Poisson. Using
Poisson there would understate the tails and systematically underprice the overs,
which is exactly the bet that would then look attractive.

Cards get a referee term. In the Premier League the busiest official averages
4.57 cards a match against 2.81 for the quietest, a 63% swing that dwarfs most
team effects, and referee assignments are published before kickoff so this is
legitimately usable. Referee effects are shrunk toward zero, because some
officials appear only a handful of times and their raw averages are noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.special import digamma, gammaln

MAX_COUNT = 40


@dataclass(frozen=True)
class CountSpec:
    """How to model one statistic."""

    name: str
    column: str
    negative_binomial: bool
    use_referee: bool = False
    # Lines the UI cares about, as totals across both teams.
    total_lines: tuple[float, ...] = ()
    team_lines: tuple[float, ...] = ()
    # Time-decay rate: a match d days old is weighted exp(-xi * d). Each
    # statistic carries its own because they go stale at different speeds, and
    # the 0.0018 inherited from the goals model was wrong for all four. That is
    # a half-life beyond a year, which suits team quality; how often a side wins
    # corners or commits fouls follows the manager and the tactical setup and
    # moves faster. Measured walk-forward on the Premier League and Serie A,
    # 0.0040 beat 0.0018 for corners, cards and fouls, and shots wanted 0.0070.
    xi: float = 0.0040


SPECS: dict[str, CountSpec] = {
    "corners": CountSpec(
        "corners", "corners_for", negative_binomial=True,
        total_lines=(8.5, 9.5, 10.5, 11.5, 12.5), team_lines=(3.5, 4.5, 5.5, 6.5),
        xi=0.0040,
    ),
    "cards": CountSpec(
        "cards", "yellows_for + reds_for", negative_binomial=False, use_referee=True,
        total_lines=(2.5, 3.5, 4.5, 5.5), team_lines=(0.5, 1.5, 2.5, 3.5),
        xi=0.0040,
    ),
    "fouls": CountSpec(
        "fouls", "fouls_committed", negative_binomial=True,
        total_lines=(18.5, 20.5, 22.5, 24.5), team_lines=(8.5, 10.5, 12.5),
        xi=0.0040,
    ),
    "shots": CountSpec(
        "shots", "shots_for", negative_binomial=True,
        total_lines=(20.5, 23.5, 26.5), team_lines=(9.5, 12.5, 15.5),
        xi=0.0070,
    ),
}


def count_pmf(rate: float, dispersion: float | None) -> np.ndarray:
    """Distribution of one count. Poisson if dispersion is None, else negative
    binomial with that dispersion."""
    k = np.arange(MAX_COUNT + 1)
    if dispersion is None:
        with np.errstate(divide="ignore"):
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
class FittedCount:
    spec: CountSpec
    attack: dict[int, float]
    concede: dict[int, float]
    home_advantage: float
    dispersion: float | None
    referee: dict[int, float] = field(default_factory=dict)
    n_matches: int = 0
    # What a team absent from training gets, which is the league average rather
    # than zero. Zero happens to be right for attack, which the sum-to-zero
    # constraint centres, and is badly wrong for concede, which carries the whole
    # level: a promoted club would be priced at one foul a match instead of ten,
    # and the over probability underflows to zero. Set by `fit`.
    attack_default: float = 0.0
    concede_default: float = 0.0

    def rates(
        self, home_team: int, away_team: int, referee_id: int | None = None
    ) -> tuple[float, float]:
        ref = self.referee.get(referee_id, 0.0) if referee_id is not None else 0.0
        home = np.exp(
            self.attack.get(home_team, self.attack_default)
            + self.concede.get(away_team, self.concede_default)
            + self.home_advantage + ref
        )
        away = np.exp(
            self.attack.get(away_team, self.attack_default)
            + self.concede.get(home_team, self.concede_default) + ref
        )
        return float(home), float(away)

    def pmf(self, rate: float) -> np.ndarray:
        return count_pmf(rate, self.dispersion)

    def team_pmfs(
        self, home_team: int, away_team: int, referee_id: int | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        home_rate, away_rate = self.rates(home_team, away_team, referee_id)
        return self.pmf(home_rate), self.pmf(away_rate)

    def total_pmf(
        self, home_team: int, away_team: int, referee_id: int | None = None
    ) -> np.ndarray:
        """Distribution of the match total, by convolving the two sides.

        Kept only as the control the direct model is measured against; see
        `FittedTotal` for why treating the sides as independent misstates the
        spread badly enough to ruin an over/under price. Do not ship from here.
        """
        home, away = self.team_pmfs(home_team, away_team, referee_id)
        return np.convolve(home, away)


def over_probability(pmf: np.ndarray, line: float) -> float:
    k = np.arange(len(pmf))
    return float(pmf[k > line].sum())


# Both models are fitted by L-BFGS-B, which needs a gradient. Left to estimate
# one by finite differences it costs one extra likelihood evaluation per
# parameter per iteration, and the per-team model has 2n+1 parameters for n
# teams — around a hundred. Supplying the derivatives analytically is what makes
# a walk-forward backtest over five leagues finish in minutes instead of hours.
#
# Both distributions belong to the exponential family in a form where the
# derivative with respect to log mu is the plain residual, which keeps these
# short: for a Poisson it is y - mu, and the negative binomial only shrinks it
# toward zero by how far the dispersion is from Poisson.


def _d_loglik_d_log_mu(y: np.ndarray, mu: np.ndarray, r: float | None) -> np.ndarray:
    if r is None:
        return y - mu
    return y - mu * (y + r) / (r + mu)


def _d_loglik_d_log_r(y: np.ndarray, mu: np.ndarray, r: float) -> np.ndarray:
    """Derivative with respect to log dispersion, which is how it is optimised
    so the parameter stays positive without a constraint."""
    return r * (
        digamma(y + r) - digamma(r) + np.log(r / (r + mu)) + 1.0 - (r + y) / (r + mu)
    )


def negative_binomial_loglik(y: np.ndarray, mu: np.ndarray, r: float) -> np.ndarray:
    return (
        gammaln(y + r) - gammaln(r) - gammaln(y + 1)
        + r * np.log(r / (r + mu)) + y * np.log(mu / (r + mu))
    )


def poisson_loglik(y: np.ndarray, mu: np.ndarray) -> np.ndarray:
    return y * np.log(mu) - mu - gammaln(y + 1)


@dataclass
class FittedTotal:
    """Model of the match total, fitted directly rather than by combining sides.

    Convolving two per-team distributions assumes the sides are independent, and
    they are not: home and away corners correlate at -0.31 and shots at -0.41,
    because a team dominating suppresses its opponent, while cards and fouls
    correlate positively because a scrappy match produces more of both. Treating
    them as independent overstates the variance of corner and shot totals by 45%
    and 70% and understates cards and fouls, which ruins the over/under
    probabilities even when the mean is right.

    Fitting the total as its own quantity captures the real spread automatically.
    """

    spec: CountSpec
    intercept: float
    tempo: dict[int, float]
    dispersion: float | None
    referee: dict[int, float] = field(default_factory=dict)
    n_matches: int = 0

    def rate(self, home_team: int, away_team: int, referee_id: int | None = None) -> float:
        ref = self.referee.get(referee_id, 0.0) if referee_id is not None else 0.0
        return float(np.exp(
            self.intercept + self.tempo.get(home_team, 0.0)
            + self.tempo.get(away_team, 0.0) + ref
        ))

    def pmf(self, home_team: int, away_team: int, referee_id: int | None = None) -> np.ndarray:
        rate = self.rate(home_team, away_team, referee_id)
        k = np.arange(2 * MAX_COUNT + 1)
        if self.dispersion is None:
            log_p = k * np.log(rate) - rate - gammaln(k + 1)
        else:
            r = self.dispersion
            log_p = (
                gammaln(k + r) - gammaln(r) - gammaln(k + 1)
                + r * np.log(r / (r + rate)) + k * np.log(rate / (r + rate))
            )
        p = np.exp(log_p)
        total = p.sum()
        return p / total if total > 0 else p


@dataclass(frozen=True)
class Design:
    """Everything both models need about a training set: teams mapped to
    contiguous indices, the time-decay weight of each match, and the referee
    mapping. Built once per fit and shared by the likelihood and its gradient."""

    teams: list[int]
    index: dict[int, int]
    home: np.ndarray
    away: np.ndarray
    weights: np.ndarray
    referees: list[int]
    referee_index: dict[int, int]
    referee_of_match: np.ndarray
    referee_penalty: float
    negative_binomial: bool

    @property
    def n_teams(self) -> int:
        return len(self.teams)

    @property
    def n_referees(self) -> int:
        return len(self.referees)

    @property
    def n_dispersion(self) -> int:
        return 1 if self.negative_binomial else 0

    def referee_term(self, effects: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
        term = np.zeros(len(self.home))
        if not self.n_referees:
            return term, None
        known = self.referee_of_match >= 0
        term[known] = effects[self.referee_of_match[known]]
        return term, known


def build_design(
    home_ids: np.ndarray,
    away_ids: np.ndarray,
    days_ago: np.ndarray,
    spec: CountSpec,
    referee_ids: np.ndarray | None = None,
    xi: float | None = None,
    referee_penalty: float = 20.0,
) -> Design:
    teams = sorted(set(home_ids.tolist()) | set(away_ids.tolist()))
    index = {t: i for i, t in enumerate(teams)}
    if spec.use_referee and referee_ids is not None:
        refs = sorted({int(r) for r in referee_ids if r is not None and r == r})
        ref_index = {r: i for i, r in enumerate(refs)}
        # NaN marks a match whose referee was not recorded; -1 sends it to no
        # effect at all rather than silently to some arbitrary official.
        ri = np.array(
            [ref_index.get(int(r), -1) if r == r else -1 for r in referee_ids], int
        )
    else:
        refs, ref_index, ri = [], {}, np.zeros(len(home_ids), int) - 1
    return Design(
        teams=teams,
        index=index,
        home=np.array([index[t] for t in home_ids]),
        away=np.array([index[t] for t in away_ids]),
        weights=np.exp(-(spec.xi if xi is None else xi) * days_ago),
        referees=refs,
        referee_index=ref_index,
        referee_of_match=ri,
        referee_penalty=referee_penalty,
        negative_binomial=spec.negative_binomial,
    )


def unpack_total(params: np.ndarray, d: Design):
    n = d.n_teams
    tempo = np.empty(n)
    tempo[: n - 1] = params[: n - 1]
    tempo[n - 1] = -params[: n - 1].sum()
    intercept = params[n - 1]
    dispersion = np.exp(params[n]) if d.n_dispersion else None
    offset = n + d.n_dispersion
    ref_effects = params[offset : offset + d.n_referees]
    return tempo, intercept, dispersion, ref_effects


def total_objective(
    params: np.ndarray, d: Design, totals: np.ndarray
) -> tuple[float, np.ndarray]:
    """Penalised negative log-likelihood of the match total, and its gradient."""
    n = d.n_teams
    tempo, intercept, dispersion, ref_effects = unpack_total(params, d)
    ref_term, known = d.referee_term(ref_effects)
    mu = np.clip(np.exp(intercept + tempo[d.home] + tempo[d.away] + ref_term), 1e-8, 300.0)

    ll = (
        poisson_loglik(totals, mu)
        if dispersion is None
        else negative_binomial_loglik(totals, mu, dispersion)
    )
    penalty = d.referee_penalty * float(np.sum(ref_effects**2))
    value = float(-np.sum(d.weights * ll) + penalty)

    g = d.weights * _d_loglik_d_log_mu(totals, mu, dispersion)
    grad = np.zeros_like(params)
    # A team's tempo raises the total whether it is at home or away, so both
    # appearances contribute. The last team is pinned to minus the sum of the
    # others, which is why its gradient is subtracted from every one.
    tempo_grad = (
        np.bincount(d.home, weights=g, minlength=n)
        + np.bincount(d.away, weights=g, minlength=n)
    )
    grad[: n - 1] = -(tempo_grad[: n - 1] - tempo_grad[n - 1])
    grad[n - 1] = -g.sum()
    if d.n_dispersion:
        grad[n] = -float(np.sum(d.weights * _d_loglik_d_log_r(totals, mu, dispersion)))
    if d.n_referees:
        offset = n + d.n_dispersion
        grad[offset:] = (
            -np.bincount(
                d.referee_of_match[known], weights=g[known], minlength=d.n_referees
            )
            + 2.0 * d.referee_penalty * ref_effects
        )
    return value, grad


def fit_total(
    home_ids: np.ndarray,
    away_ids: np.ndarray,
    totals: np.ndarray,
    days_ago: np.ndarray,
    spec: CountSpec,
    referee_ids: np.ndarray | None = None,
    xi: float | None = None,
    referee_penalty: float = 20.0,
) -> FittedTotal:
    d = build_design(
        home_ids, away_ids, days_ago, spec, referee_ids, xi, referee_penalty
    )
    n, n_disp, n_ref = d.n_teams, d.n_dispersion, d.n_referees

    start = np.concatenate([
        np.zeros(n - 1),
        [np.log(max(totals.mean(), 1.0))],
        ([np.log(20.0)] if n_disp else []),
        np.zeros(n_ref),
    ])
    bounds = (
        [(-1.5, 1.5)] * (n - 1)
        + [(-2.0, 6.0)]
        + ([(-2.0, 8.0)] if n_disp else [])
        + [(-1.0, 1.0)] * n_ref
    )
    result = minimize(
        total_objective, start, args=(d, totals), method="L-BFGS-B", jac=True,
        bounds=bounds, options={"maxiter": 500, "ftol": 1e-9},
    )
    tempo, intercept, dispersion, ref_effects = unpack_total(result.x, d)
    return FittedTotal(
        spec=spec,
        intercept=float(intercept),
        tempo={t: float(tempo[d.index[t]]) for t in d.teams},
        dispersion=float(dispersion) if dispersion is not None else None,
        referee={
            r: float(ref_effects[d.referee_index[r]]) for r in d.referees
        } if n_ref else {},
        n_matches=len(home_ids),
    )


def unpack_count(params: np.ndarray, d: Design):
    n = d.n_teams
    n_attack = n - 1  # one pinned so the parameters are identified
    attack = np.empty(n)
    attack[:n_attack] = params[:n_attack]
    attack[n - 1] = -params[:n_attack].sum()
    concede = params[n_attack : n_attack + n]
    offset = n_attack + n
    home_adv = params[offset]
    dispersion = np.exp(params[offset + 1]) if d.n_dispersion else None
    offset += 1 + d.n_dispersion
    ref_effects = params[offset : offset + d.n_referees]
    return attack, concede, home_adv, dispersion, ref_effects


def count_objective(
    params: np.ndarray, d: Design, home_counts: np.ndarray, away_counts: np.ndarray
) -> tuple[float, np.ndarray]:
    """Penalised negative log-likelihood of the two per-team counts, and its
    gradient."""
    n = d.n_teams
    n_attack = n - 1
    attack, concede, home_adv, dispersion, ref_effects = unpack_count(params, d)
    ref_term, known = d.referee_term(ref_effects)

    mu_home = np.clip(
        np.exp(attack[d.home] + concede[d.away] + home_adv + ref_term), 1e-8, 200.0
    )
    mu_away = np.clip(np.exp(attack[d.away] + concede[d.home] + ref_term), 1e-8, 200.0)

    if dispersion is None:
        ll = poisson_loglik(home_counts, mu_home) + poisson_loglik(away_counts, mu_away)
    else:
        ll = negative_binomial_loglik(
            home_counts, mu_home, dispersion
        ) + negative_binomial_loglik(away_counts, mu_away, dispersion)
    penalty = d.referee_penalty * float(np.sum(ref_effects**2))
    value = float(-np.sum(d.weights * ll) + penalty)

    gh = d.weights * _d_loglik_d_log_mu(home_counts, mu_home, dispersion)
    ga = d.weights * _d_loglik_d_log_mu(away_counts, mu_away, dispersion)
    grad = np.zeros_like(params)
    # A team's attack rate drives its own count at either venue; its concede
    # rate drives the opponent's. Hence the crossed pairs of group sums.
    attack_grad = (
        np.bincount(d.home, weights=gh, minlength=n)
        + np.bincount(d.away, weights=ga, minlength=n)
    )
    concede_grad = (
        np.bincount(d.away, weights=gh, minlength=n)
        + np.bincount(d.home, weights=ga, minlength=n)
    )
    grad[:n_attack] = -(attack_grad[:n_attack] - attack_grad[n - 1])
    grad[n_attack : n_attack + n] = -concede_grad
    offset = n_attack + n
    grad[offset] = -gh.sum()  # home advantage only shifts the home side
    if d.n_dispersion:
        grad[offset + 1] = -float(np.sum(
            d.weights * (
                _d_loglik_d_log_r(home_counts, mu_home, dispersion)
                + _d_loglik_d_log_r(away_counts, mu_away, dispersion)
            )
        ))
    if d.n_referees:
        offset += 1 + d.n_dispersion
        grad[offset:] = (
            -np.bincount(
                d.referee_of_match[known],
                weights=(gh + ga)[known],
                minlength=d.n_referees,
            )
            + 2.0 * d.referee_penalty * ref_effects
        )
    return value, grad


def fit(
    home_ids: np.ndarray,
    away_ids: np.ndarray,
    home_counts: np.ndarray,
    away_counts: np.ndarray,
    days_ago: np.ndarray,
    spec: CountSpec,
    referee_ids: np.ndarray | None = None,
    xi: float | None = None,
    referee_penalty: float = 20.0,
) -> FittedCount:
    d = build_design(
        home_ids, away_ids, days_ago, spec, referee_ids, xi, referee_penalty
    )
    n, n_disp, n_ref = d.n_teams, d.n_dispersion, d.n_referees

    # Attack is pinned to sum to zero, so it cannot carry any of the level and
    # concede has to start at the whole of it rather than half. Starting concede
    # at half left every rate short by a factor of the other half, and since the
    # constraint forbids lifting all the attacks together the optimiser walked
    # some of them into the bounds instead, which produced fouls rates in the
    # billions for the leagues where the mean is largest.
    level = np.log(max((home_counts.mean() + away_counts.mean()) / 2, 0.5))
    start = np.concatenate([
        np.zeros(n - 1),
        np.full(n, level),
        [0.05],
        ([np.log(5.0)] if n_disp else []),
        np.zeros(n_ref),
    ])
    bounds = (
        [(-3.0, 3.0)] * (n - 1)
        + [(-3.0, 5.0)] * n
        + [(-1.0, 1.0)]
        + ([(-2.0, 6.0)] if n_disp else [])
        + [(-1.0, 1.0)] * n_ref
    )
    result = minimize(
        count_objective, start, args=(d, home_counts, away_counts), method="L-BFGS-B",
        jac=True, bounds=bounds, options={"maxiter": 500, "ftol": 1e-9},
    )
    attack, concede, home_adv, dispersion, ref_effects = unpack_count(result.x, d)
    return FittedCount(
        spec=spec,
        attack={t: float(attack[d.index[t]]) for t in d.teams},
        concede={t: float(concede[d.index[t]]) for t in d.teams},
        attack_default=float(attack.mean()),
        concede_default=float(concede.mean()),
        home_advantage=float(home_adv),
        dispersion=float(dispersion) if dispersion is not None else None,
        referee={
            r: float(ref_effects[d.referee_index[r]]) for r in d.referees
        } if n_ref else {},
        n_matches=len(home_ids),
    )
