"""Turning fitted models into stored probabilities for real fixtures.

The whole point of the pipeline arrives here: a fixture list in, a table of
percentages out, each one attributable to the fit and the calibration that
produced it.

Three things this module is careful about.

Everything is fitted as of a date, and only on matches played strictly before
it. The date is explicit rather than implied by "now" so the command can be run
against a past matchday and checked against what actually happened — which is
the only way to know it works before trusting it on fixtures that have not been
played. The database enforces the same rule independently, and will reject a
prediction whose match falls inside its model's training window.

The recalibration is derived, not assumed. Phase 1 established that the raw
count models are overconfident in a consistent way, so publishing p_raw would
put numbers on the page that are wrong by up to ten points at the extremes. The
correction is obtained by replaying the walk-forward over a window ending at the
as-of date, which is exactly what a live system accumulates by running daily.

What gets computed is decided by the market registry rather than by this file.
A market the database calls rejected is never predicted; markets it calls held
are computed and stored so they keep being measured, and the app filters them
out by status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import psycopg

from footy import db
from footy.models import backtest as goals_backtest
from footy.models import calibration as cal
from footy.models import counts as cm
from footy.models import counts_backtest as cbt
from footy.models import dixon_coles as dc
from footy.models import publish

# Goal lines worth pricing. The count models carry their own lines in CountSpec;
# goals need theirs stated somewhere, and this is the set a football page
# actually shows. 2.5 is the one that matters commercially, the rest give the
# distribution enough shape to be useful.
GOALS_TOTAL_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
GOALS_TEAM_LINES = (0.5, 1.5, 2.5)

# How much history the recalibration is replayed over. Two seasons is enough for
# the few hundred observations per line that Recalibrator.fit insists on before
# it will move a probability at all, without reaching so far back that it is
# measuring a model fitted on a different era of the league.
CALIBRATION_WINDOW_DAYS = 730


@dataclass(frozen=True)
class Fixture:
    match_id: int
    kickoff: date
    home_id: int
    away_id: int
    home_name: str
    away_name: str
    referee_id: int | None


@dataclass
class Written:
    """What a run did, for the command line to report."""

    fixtures: int = 0
    models: int = 0
    predictions: int = 0
    calibrated_markets: int = 0
    skipped: list[str] = field(default_factory=list)


def load_fixtures(
    conn: psycopg.Connection, competition: str, as_of: date, until: date
) -> list[Fixture]:
    """Matches kicking off in [as_of, until).

    Deliberately not restricted to fixtures still marked scheduled, so the same
    command can be pointed at a past matchday and its output compared with the
    results. Correctness does not rest on the status column: it rests on the
    training window ending at as_of, which the database also checks.
    """
    rows = db.fetch_all(
        conn,
        """
        select m.match_id, m.kickoff_date, m.home_team_id, m.away_team_id,
               h.canonical_name, a.canonical_name, m.referee_id
          from core.match m
          join core.competition c on c.competition_id = m.competition_id and c.code = %s
          join core.team h on h.team_id = m.home_team_id
          join core.team a on a.team_id = m.away_team_id
         where m.kickoff_date >= %s and m.kickoff_date < %s
         order by m.kickoff_date, m.match_id
        """,
        (competition, as_of, until),
    )
    return [Fixture(*r) for r in rows]


# ============================================================
# Goals
# ============================================================


def _fit_goals(
    matches: list, as_of: date, xi: float
) -> tuple[dc.Fitted, date]:
    home_ids = np.array([m.home_id for m in matches])
    away_ids = np.array([m.away_id for m in matches])
    fitted = dc.fit(
        home_ids,
        away_ids,
        np.array([m.home_goals for m in matches]),
        np.array([m.away_goals for m in matches]),
        np.array([(as_of - m.kickoff).days for m in matches], float),
        xi=xi,
    )
    return fitted, min(m.kickoff for m in matches)


def _goals_rows(
    fitted: dc.Fitted, fixture: Fixture, markets: dict[str, publish.Market]
) -> list[publish.PredictionRow]:
    """Every goals market off one score matrix, which is what keeps them
    coherent: the 1X2, the totals, each side's goals and both-teams-to-score are
    all sums over the same distribution, so they cannot contradict each other."""
    matrix = fitted.score_matrix(fixture.home_id, fixture.away_id)
    rows: list[publish.PredictionRow] = []

    def add(code: str, line: float | None, selection: str, p: float) -> None:
        if code not in markets:
            return
        rows.append(publish.PredictionRow(fixture.match_id, code, line, selection, p, p))

    home, draw, away = dc.outcome_probabilities(matrix)
    add("goals_1x2", None, "home", home)
    add("goals_1x2", None, "draw", draw)
    add("goals_1x2", None, "away", away)
    add("goals_btts", None, "yes", dc.btts_probability(matrix))
    for line in GOALS_TOTAL_LINES:
        add("goals_total", line, "over", dc.over_probability(matrix, line))
    for line in GOALS_TEAM_LINES:
        add("goals_home", line, "over", dc.team_over_probability(matrix, line, home=True))
        add("goals_away", line, "over", dc.team_over_probability(matrix, line, home=False))
    return rows


# ============================================================
# Counts
# ============================================================


def _count_recalibrators(
    stat: str, competition: str, as_of: date, window_days: int, xi: float | None
) -> dict[tuple[str, float], cal.Recalibrator]:
    """Replay the walk-forward up to as_of and keep the corrections it ended on.

    This reuses the backtest rather than reimplementing it, so the calibration
    that ships is produced by the same code path that was used to decide these
    markets were worth shipping at all.
    """
    bt = cbt.run(
        stat,
        competition,
        test_from=as_of - timedelta(days=window_days),
        test_to=as_of,
        xi=xi,
        include_convolution=False,
    )
    return bt.recalibrators


def _count_rows(
    fixture: Fixture,
    spec: cm.CountSpec,
    total: cm.FittedTotal | None,
    team: cm.FittedCount | None,
    markets: dict[str, publish.Market],
    recal: dict[tuple[str, float], cal.Recalibrator],
) -> tuple[list[publish.PredictionRow], list[publish.PredictionRow]]:
    """Rows for the direct-total model and the per-team model, kept apart
    because they are separate fits and each prediction must name its own."""
    total_rows: list[publish.PredictionRow] = []
    team_rows: list[publish.PredictionRow] = []

    def build(code: str, scope: str, line: float, p_raw: float) -> publish.PredictionRow:
        adjust = recal.get((scope, line))
        p_cal = adjust.apply(p_raw) if adjust is not None else p_raw
        return publish.PredictionRow(
            fixture.match_id, code, line, "over", p_raw, p_cal
        )

    if total is not None and f"{spec.name}_total" in markets:
        pmf = total.pmf(fixture.home_id, fixture.away_id, fixture.referee_id)
        for line in spec.total_lines:
            total_rows.append(
                build(f"{spec.name}_total", "total", line, cm.over_probability(pmf, line))
            )

    if team is not None:
        home_pmf, away_pmf = team.team_pmfs(
            fixture.home_id, fixture.away_id, fixture.referee_id
        )
        for scope, pmf in (("home", home_pmf), ("away", away_pmf)):
            code = f"{spec.name}_{scope}"
            if code not in markets:
                continue
            for line in spec.team_lines:
                team_rows.append(
                    build(code, scope, line, cm.over_probability(pmf, line))
                )
    return total_rows, team_rows


# ============================================================
# Orchestration
# ============================================================


def _write_calibrations(
    conn: psycopg.Connection,
    model_id: int,
    codes_and_lines: list[tuple[str, str, float | None]],
    recal: dict[tuple[str, float], cal.Recalibrator],
) -> int:
    """Record the correction in force for every market this fit publishes.

    The identity is written explicitly when there is not enough evidence to
    correct anything, rather than leaving the row absent. An absent row is
    ambiguous — it could mean "no correction needed" or "nobody looked" — and a
    published probability has to be reproducible from what is stored.
    """
    written = 0
    for code, scope, line in codes_and_lines:
        adjust = recal.get((scope, line), cal.Recalibrator.identity())
        publish.upsert_calibration(
            conn, model_id, code, line, adjust.intercept, adjust.slope, adjust.n
        )
        written += 1
    return written


def run(
    competition: str = "ENG-PL",
    as_of: date | None = None,
    days: int = 7,
    stats: tuple[str, ...] = ("corners", "cards", "fouls", "shots"),
    goals: bool = True,
    goals_xi: float = 0.0018,
    calibration_window_days: int = CALIBRATION_WINDOW_DAYS,
    min_train: int = 500,
) -> Written:
    as_of = as_of or date.today()
    until = as_of + timedelta(days=days)
    out = Written()

    with db.connect() as conn:
        markets = {m.code: m for m in publish.load_markets(conn)}
        comp_id = publish.competition_id(conn, competition)
        fixtures = load_fixtures(conn, competition, as_of, until)
        out.fixtures = len(fixtures)
        if not fixtures:
            return out

        if goals:
            history = [
                m for m in goals_backtest.load_matches(competition)
                if m.kickoff < as_of
            ]
            if len(history) < min_train:
                out.skipped.append(
                    f"goals: only {len(history)} matches before {as_of}"
                )
            else:
                fitted, trained_from = _fit_goals(history, as_of, goals_xi)
                model_id = publish.upsert_model(
                    conn, "dixon_coles", "goals", comp_id,
                    params={"xi": goals_xi, "max_goals": dc.MAX_GOALS},
                    coefficients={
                        "attack": fitted.attack,
                        "defence": fitted.defence,
                        "home_advantage": fitted.home_advantage,
                        "rho": fitted.rho,
                    },
                    trained_from=trained_from, trained_to=as_of,
                    n_matches=fitted.n_matches,
                )
                out.models += 1
                rows: list[publish.PredictionRow] = []
                for f in fixtures:
                    rows.extend(_goals_rows(fitted, f, markets))
                out.predictions += publish.upsert_predictions(conn, model_id, rows)
                # No goals recalibration has been measured, so the identity is
                # recorded rather than a correction invented. Dixon-Coles prices
                # every goals market off one score matrix and sat within four
                # log-loss points of the closing line in Phase 1, so there is no
                # evidence of the overconfidence the count models showed. That
                # is an absence of evidence, not evidence of absence, and it is
                # the next thing worth measuring.
                out.calibrated_markets += _write_calibrations(
                    conn, model_id, _goals_market_lines(markets), {}
                )

        for stat in stats:
            spec = cm.SPECS[stat]
            needed = {
                scope for scope in ("total", "home", "away")
                if f"{stat}_{scope}" in markets
            }
            if not needed:
                out.skipped.append(f"{stat}: every market rejected")
                continue

            history = [h for h in cbt.load(stat, competition) if h.kickoff < as_of]
            if len(history) < min_train:
                out.skipped.append(f"{stat}: only {len(history)} matches before {as_of}")
                continue

            recal = _count_recalibrators(
                stat, competition, as_of, calibration_window_days, xi=None
            )
            trained_from = min(h.kickoff for h in history)
            fitted = cbt.fit_models(history, as_of, spec, xi=None)
            base_params = {
                "xi": spec.xi,
                "negative_binomial": spec.negative_binomial,
                "use_referee": spec.use_referee,
            }

            total_model_id = team_model_id = None
            if "total" in needed:
                total_model_id = publish.upsert_model(
                    conn, "count_total", stat, comp_id,
                    params=base_params,
                    coefficients={
                        "intercept": fitted.total.intercept,
                        "tempo": fitted.total.tempo,
                        "dispersion": fitted.total.dispersion,
                        "referee": fitted.total.referee,
                    },
                    trained_from=trained_from, trained_to=as_of,
                    n_matches=fitted.total.n_matches,
                )
                out.models += 1
            if needed & {"home", "away"}:
                team_model_id = publish.upsert_model(
                    conn, "count_team", stat, comp_id,
                    params=base_params,
                    coefficients={
                        "attack": fitted.team.attack,
                        "concede": fitted.team.concede,
                        "home_advantage": fitted.team.home_advantage,
                        "dispersion": fitted.team.dispersion,
                        "referee": fitted.team.referee,
                    },
                    trained_from=trained_from, trained_to=as_of,
                    n_matches=fitted.team.n_matches,
                )
                out.models += 1

            all_total: list[publish.PredictionRow] = []
            all_team: list[publish.PredictionRow] = []
            for f in fixtures:
                total_rows, team_rows = _count_rows(
                    f, spec,
                    fitted.total if total_model_id else None,
                    fitted.team if team_model_id else None,
                    markets, recal,
                )
                all_total.extend(total_rows)
                all_team.extend(team_rows)

            if total_model_id:
                out.predictions += publish.upsert_predictions(
                    conn, total_model_id, all_total
                )
                out.calibrated_markets += _write_calibrations(
                    conn, total_model_id,
                    [(f"{stat}_total", "total", line) for line in spec.total_lines],
                    recal,
                )
            if team_model_id:
                out.predictions += publish.upsert_predictions(
                    conn, team_model_id, all_team
                )
                out.calibrated_markets += _write_calibrations(
                    conn, team_model_id,
                    [
                        (f"{stat}_{scope}", scope, line)
                        for scope in ("home", "away") if f"{stat}_{scope}" in markets
                        for line in spec.team_lines
                    ],
                    recal,
                )

        conn.commit()
    return out


def _goals_market_lines(
    markets: dict[str, publish.Market]
) -> list[tuple[str, str, float | None]]:
    """Every goals market that needs a calibration row, lines included.

    1X2 and both-teams-to-score have no line, so they get one row each. Note
    that a single row then covers all three 1X2 selections: the table is keyed
    by market and line, not by selection. That is adequate while the correction
    is the identity, and is the thing to revisit if a goals recalibration is
    ever measured, since home, draw and away could need different corrections
    and would also have to be renormalised to sum to one.
    """
    out: list[tuple[str, str, float | None]] = []
    for code in ("goals_1x2", "goals_btts"):
        if code in markets:
            out.append((code, "match", None))
    if "goals_total" in markets:
        out += [("goals_total", "total", line) for line in GOALS_TOTAL_LINES]
    for scope in ("home", "away"):
        if f"goals_{scope}" in markets:
            out += [(f"goals_{scope}", scope, line) for line in GOALS_TEAM_LINES]
    return out
