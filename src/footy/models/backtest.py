"""Walk-forward backtest.

The model is refitted as the season progresses and only ever sees matches played
before the fixture it is predicting. Refitting on the whole history and scoring
the same matches would report a far better number that means nothing.

Everything is scored against the same benchmark: the de-vigged closing odds. The
market is the thing to beat, and a model that cannot beat it is still useful for
the markets bookmakers price lazily, but the number should be honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from footy import db
from footy.models import dixon_coles as dc


@dataclass
class Match:
    match_id: int
    kickoff: date
    home_id: int
    away_id: int
    home_goals: int
    away_goals: int
    market: tuple[float, float, float] | None
    total_goals: int = 0

    def outcome(self) -> int:
        if self.home_goals > self.away_goals:
            return 0
        return 1 if self.home_goals == self.away_goals else 2


@dataclass
class Scores:
    n: int = 0
    model_ll: float = 0.0
    market_ll: float = 0.0
    base_ll: float = 0.0
    model_ou_ll: float = 0.0
    market_ou_ll: float = 0.0
    n_ou: int = 0
    predictions: list[tuple] = field(default_factory=list)


def load_matches(competition: str, start_year_from: int = 2014) -> list[Match]:
    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            """
            select m.match_id, m.kickoff_date, m.home_team_id, m.away_team_id,
                   m.home_goals_ft, m.away_goals_ft,
                   f.market_p_home, f.market_p_draw, f.market_p_away
              from core.match m
              join core.competition c on c.competition_id = m.competition_id and c.code = %s
              join core.season se on se.season_id = m.season_id and se.start_year >= %s
              left join features.match f on f.match_id = m.match_id
             where m.home_goals_ft is not null
             order by m.kickoff_date, m.match_id
            """,
            (competition, start_year_from),
        )
    out = []
    for r in rows:
        market = None
        if r[6] is not None and r[7] is not None and r[8] is not None:
            market = (float(r[6]), float(r[7]), float(r[8]))
        out.append(
            Match(
                match_id=r[0], kickoff=r[1], home_id=r[2], away_id=r[3],
                home_goals=r[4], away_goals=r[5], market=market,
                total_goals=r[4] + r[5],
            )
        )
    return out


def _clip(p: float) -> float:
    """Keep log-loss finite. A model certain of a wrong outcome would score
    infinity, which tells us nothing except that it was overconfident."""
    return min(max(p, 1e-6), 1 - 1e-6)


def run(
    competition: str = "ENG-PL",
    test_from: date = date(2022, 7, 1),
    test_to: date | None = None,
    xi: float = 0.0018,
    refit_every_days: int = 14,
    min_train: int = 500,
) -> Scores:
    """Walk forward over [test_from, test_to).

    `test_to` exists so a hyperparameter can be chosen on one window and the
    result reported on a later one. Tuning and reporting on the same matches
    gives a number that cannot be trusted, however carefully the walk-forward
    itself is done — the choice of setting has then seen the answer.
    """
    matches = load_matches(competition)
    test = [
        m for m in matches
        if m.kickoff >= test_from and (test_to is None or m.kickoff < test_to)
    ]
    if not test:
        raise RuntimeError("no matches in the test period")

    # Base rates from the training period only.
    train_all = [m for m in matches if m.kickoff < test_from]
    counts = np.bincount([m.outcome() for m in train_all], minlength=3)
    base = counts / counts.sum()
    train_totals = np.array([m.total_goals for m in train_all])
    base_over25 = float((train_totals > 2.5).mean())

    scores = Scores()
    fitted: dc.Fitted | None = None
    last_fit: date | None = None

    for m in test:
        if fitted is None or last_fit is None or (m.kickoff - last_fit) >= timedelta(
            days=refit_every_days
        ):
            history = [h for h in matches if h.kickoff < m.kickoff]
            if len(history) >= min_train:
                days_ago = np.array([(m.kickoff - h.kickoff).days for h in history], float)
                fitted = dc.fit(
                    np.array([h.home_id for h in history]),
                    np.array([h.away_id for h in history]),
                    np.array([h.home_goals for h in history], float),
                    np.array([h.away_goals for h in history], float),
                    days_ago,
                    xi=xi,
                )
                last_fit = m.kickoff

        if fitted is None:
            continue

        matrix = fitted.score_matrix(m.home_id, m.away_id)
        p = dc.outcome_probabilities(matrix)
        actual = m.outcome()

        scores.n += 1
        scores.model_ll -= np.log(_clip(p[actual]))
        scores.base_ll -= np.log(_clip(base[actual]))
        if m.market:
            scores.market_ll -= np.log(_clip(m.market[actual]))

        p_over = dc.over_probability(matrix, 2.5)
        went_over = m.total_goals > 2.5
        scores.n_ou += 1
        scores.model_ou_ll -= np.log(_clip(p_over if went_over else 1 - p_over))
        scores.market_ou_ll -= np.log(
            _clip(base_over25 if went_over else 1 - base_over25)
        )

        scores.predictions.append(
            (m.match_id, m.kickoff, p[0], p[1], p[2], p_over, actual, went_over,
             m.market[0] if m.market else None)
        )
    return scores


def report(scores: Scores, label: str = "") -> dict[str, float]:
    n = scores.n
    market_n = sum(1 for p in scores.predictions if p[8] is not None)
    out = {
        "matches": n,
        "model": scores.model_ll / n,
        "base_rates": scores.base_ll / n,
        "market": scores.market_ll / market_n if market_n else float("nan"),
        "model_ou25": scores.model_ou_ll / scores.n_ou,
        "base_ou25": scores.market_ou_ll / scores.n_ou,
    }
    if label:
        print(f"\n=== {label} ===")
    print(f"  matches scored: {n:,}")
    print("  1X2 log-loss")
    print(f"    base rates   {out['base_rates']:.5f}")
    print(f"    Dixon-Coles  {out['model']:.5f}")
    print(f"    market       {out['market']:.5f}")
    print("  over/under 2.5 log-loss")
    print(f"    base rate    {out['base_ou25']:.5f}")
    print(f"    Dixon-Coles  {out['model_ou25']:.5f}")
    return out
