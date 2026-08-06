"""Walk-forward backtest for the count markets.

There are no bookmaker odds for corners, cards or fouls in this database, so
unlike goals these cannot be scored against the market. Two things are measured
instead: whether the model beats the base rate, which shows it has found real
signal, and whether it is calibrated, which is what a published percentage has
to be. A number saying 70% must win about 70% of the time or the table is
misleading however good its log-loss.

Four variants are scored per line so the two design decisions are visible rather
than asserted:

  total       the direct model of the two-team total
  convolved   the older approach of adding two independent per-team distributions
  home, away  the per-team models, which are a different market, not a worse one

and each in a raw and a calibrated form. Every fit, including the calibration,
sees only matches played before the fixture being predicted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from footy import db
from footy.models import blend as bl
from footy.models import calibration as cal
from footy.models import counts as cm

# Scopes are named once here because they key the results and drive the report.
RAW_SCOPES = ("total", "convolved", "home", "away")
BLEND_SCOPES = ("total blend", "home blend", "away blend")
CALIBRATED = {s: f"{s} calibrated" for s in RAW_SCOPES + BLEND_SCOPES}


def observable(scope: str) -> str:
    """The quantity a scope is scored against: 'total', 'home' or 'away'.

    Scope names carry two independent decorations — whether the probability was
    recalibrated, and whether the feature blend produced it — but every variant
    of a market is settled against the same observed number. Deriving that here
    keeps the benchmark, the outcome and the accumulated calibration history
    from drifting apart as variants are added.
    """
    plain = scope.replace(" calibrated", "").replace(" blend", "")
    return "total" if plain == "convolved" else plain


@dataclass
class CountMatch:
    match_id: int
    kickoff: date
    home_id: int
    away_id: int
    referee_id: int | None
    home_count: float
    away_count: float

    @property
    def total(self) -> float:
        return self.home_count + self.away_count

    def observed(self, scope: str) -> float:
        which = observable(scope)
        return self.home_count if which == "home" else (
            self.away_count if which == "away" else self.total
        )


@dataclass
class LineResult:
    scope: str
    line: float
    n: int = 0
    model_ll: float = 0.0
    base_ll: float = 0.0
    rolling_ll: float = 0.0
    predicted: list[float] = field(default_factory=list)
    actual: list[int] = field(default_factory=list)

    @property
    def model(self) -> float:
        return self.model_ll / self.n

    @property
    def base(self) -> float:
        return self.base_ll / self.n

    @property
    def rolling(self) -> float:
        return self.rolling_ll / self.n

    @property
    def gain(self) -> float:
        """Percentage of the fixed base rate's log-loss removed. Negative means
        the model is worse than the historical frequency."""
        return (self.base - self.model) / self.base * 100

    @property
    def gain_vs_rolling(self) -> float:
        """The honest number, and the one the shipping decision uses.

        A base rate frozen at the end of the training period cannot follow a
        league that changes. Bundesliga fouls fell by a third between 2014 and
        2025, so a static benchmark is simply wrong by the test period and any
        model that tracks the trend scores an enormous 'gain' without predicting
        a single individual match. The rolling benchmark moves with the league,
        so beating it requires telling fixtures apart rather than telling
        seasons apart.
        """
        return (self.rolling - self.model) / self.rolling * 100

    @property
    def bias(self) -> float:
        return float(np.mean(self.predicted) - np.mean(self.actual))

    @property
    def worst_bucket(self) -> float:
        return cal.worst_bucket_error(np.array(self.predicted), np.array(self.actual))


@dataclass
class Backtest:
    stat: str
    competition: str
    results: dict[tuple[str, float], LineResult] = field(default_factory=dict)
    n_matches: int = 0
    n_refits: int = 0
    recalibrators: dict[tuple[str, float], cal.Recalibrator] = field(default_factory=dict)

    def scope(self, scope: str) -> dict[tuple[str, float], LineResult]:
        return {k: v for k, v in self.results.items() if k[0] == scope and v.n}


COLUMN_SQL = {
    "corners": ("h.corners_for", "a.corners_for"),
    "cards": ("h.yellows_for + h.reds_for", "a.yellows_for + a.reds_for"),
    "fouls": ("h.fouls_committed", "a.fouls_committed"),
    "shots": ("h.shots_for", "a.shots_for"),
}


def load(stat: str, competition: str) -> list[CountMatch]:
    home_expr, away_expr = COLUMN_SQL[stat]
    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            f"""
            select m.match_id, m.kickoff_date, m.home_team_id, m.away_team_id,
                   m.referee_id, {home_expr}, {away_expr}
              from core.match m
              join core.competition c on c.competition_id = m.competition_id and c.code = %s
              join core.team_match h on h.match_id = m.match_id
                                    and h.team_id = m.home_team_id and h.period = 'FT'
              join core.team_match a on a.match_id = m.match_id
                                    and a.team_id = m.away_team_id and a.period = 'FT'
             where {home_expr} is not null and {away_expr} is not null
             order by m.kickoff_date, m.match_id
            """,
            (competition,),
        )
    return [
        CountMatch(r[0], r[1], r[2], r[3], r[4], float(r[5]), float(r[6])) for r in rows
    ]


def _clip(p: float) -> float:
    return min(max(p, 1e-6), 1 - 1e-6)


def _referees(history: list[CountMatch], spec: cm.CountSpec) -> np.ndarray | None:
    if not spec.use_referee:
        return None
    return np.array([h.referee_id if h.referee_id else np.nan for h in history], float)


@dataclass
class Models:
    """The fitted pair for one refit. The direct total model and the per-team
    model answer different questions, so both are kept."""

    total: cm.FittedTotal
    team: cm.FittedCount
    corrections: bl.Corrections | None = None

    def base_rates(self, m: CountMatch) -> dict[str, float]:
        home_rate, away_rate = self.team.rates(m.home_id, m.away_id, m.referee_id)
        return {
            "total": self.total.rate(m.home_id, m.away_id, m.referee_id),
            "home": home_rate,
            "away": away_rate,
        }

    def probabilities(
        self,
        m: CountMatch,
        spec: cm.CountSpec,
        include_convolution: bool,
        features: np.ndarray | None = None,
    ) -> dict[tuple[str, float], float]:
        total_pmf = self.total.pmf(m.home_id, m.away_id, m.referee_id)
        home_pmf, away_pmf = self.team.team_pmfs(m.home_id, m.away_id, m.referee_id)
        out: dict[tuple[str, float], float] = {}
        for line in spec.total_lines:
            out[("total", line)] = cm.over_probability(total_pmf, line)
        if include_convolution:
            conv = np.convolve(home_pmf, away_pmf)
            for line in spec.total_lines:
                out[("convolved", line)] = cm.over_probability(conv, line)
        for line in spec.team_lines:
            out[("home", line)] = cm.over_probability(home_pmf, line)
            out[("away", line)] = cm.over_probability(away_pmf, line)

        if self.corrections is None or features is None:
            return out

        base = self.base_rates(m)
        # The blend keeps each market's own support: a total ranges over twice
        # what one side can produce, and scoring the two over different supports
        # would make the comparison meaningless.
        sizes = {
            "total": 2 * cm.MAX_COUNT + 1,
            "home": cm.MAX_COUNT + 1,
            "away": cm.MAX_COUNT + 1,
        }
        lines = {
            "total": spec.total_lines,
            "home": spec.team_lines,
            "away": spec.team_lines,
        }
        for scope in ("total", "home", "away"):
            correction = self.corrections.get(scope)
            if correction is None:
                continue
            rate = float(correction.rates(np.array([base[scope]]), features)[0])
            pmf = bl.pmf_for_rate(rate, correction.dispersion, sizes[scope])
            for line in lines[scope]:
                out[(f"{scope} blend", line)] = cm.over_probability(pmf, line)
        return out


def fit_models(
    history: list[CountMatch],
    asof: date,
    spec: cm.CountSpec,
    xi: float | None,
    features: bl.Features | None = None,
) -> Models:
    """Fit both count models on `history`, decaying each match from `asof`.

    Public because the prediction path fits exactly the same way; sharing this
    is what guarantees a published probability comes from the same procedure the
    backtest validated.

    When `features` is supplied, a boosted correction is fitted on top of each
    fitted rate — on the same history, with the same time-decay weights, so the
    blend cannot see anything the model it corrects could not.
    """
    home_ids = np.array([h.home_id for h in history])
    away_ids = np.array([h.away_id for h in history])
    days_ago = np.array([(asof - h.kickoff).days for h in history], float)
    referees = _referees(history, spec)
    models = Models(
        total=cm.fit_total(
            home_ids, away_ids, np.array([h.total for h in history], float),
            days_ago, spec, referee_ids=referees, xi=xi,
        ),
        team=cm.fit(
            home_ids, away_ids,
            np.array([h.home_count for h in history], float),
            np.array([h.away_count for h in history], float),
            days_ago, spec, referee_ids=referees, xi=xi,
        ),
    )
    if features is None:
        return models

    X = features.matrix([h.match_id for h in history])
    weights = np.exp(-(spec.xi if xi is None else xi) * days_ago)
    rates = [models.base_rates(h) for h in history]
    targets = {
        "total": np.array([h.total for h in history], float),
        "home": np.array([h.home_count for h in history], float),
        "away": np.array([h.away_count for h in history], float),
    }
    models.corrections = bl.Corrections(
        **{
            scope: bl.fit_correction(
                X, targets[scope],
                np.array([r[scope] for r in rates]),
                weights, spec.negative_binomial,
            )
            for scope in ("total", "home", "away")
        }
    )
    return models


def run(
    stat: str,
    competition: str = "ENG-PL",
    test_from: date = date(2022, 7, 1),
    test_to: date | None = None,
    xi: float | None = None,
    refit_every_days: int = 30,
    min_train: int = 500,
    include_convolution: bool = True,
    warmup_matches: int = 400,
    base_window: int = 380,
    blend: bool = False,
) -> Backtest:
    """Walk forward over [test_from, test_to).

    `test_to` bounds the window for the same reason it does for goals — a
    setting chosen on the matches it is reported on has seen the answer — and it
    is also what lets the prediction path reuse this walk-forward to derive its
    recalibration from history strictly before the fixtures being predicted.

    With `blend`, each fitted rate additionally gets a boosted correction from
    the feature layer, scored as extra scopes alongside the model it corrects.
    Both variants therefore see the same fixtures, the same benchmark and the
    same calibration path, which is the only way the comparison means anything.
    """
    spec = cm.SPECS[stat]
    matches = load(stat, competition)
    features = bl.load_features(competition) if blend else None
    test = [
        m for m in matches
        if m.kickoff >= test_from and (test_to is None or m.kickoff < test_to)
    ]
    train_all = [m for m in matches if m.kickoff < test_from]
    if not test:
        raise RuntimeError(f"no {stat} matches in {competition} on or after {test_from}")
    if len(train_all) < min_train:
        raise RuntimeError(
            f"{competition} has only {len(train_all)} matches before {test_from}, "
            f"need {min_train}"
        )

    # Base rates come from the training period only. Taking them over the whole
    # dataset would let the benchmark see the matches it is compared on. Venue
    # matters for a per-team line — home sides win more corners — so a pooled
    # base rate would be a straw man the model beats for free.
    base: dict[tuple[str, float], float] = {}
    for line in spec.total_lines:
        rate = float(np.mean([m.total > line for m in train_all]))
        base[("total", line)] = base[("convolved", line)] = rate
    for line in spec.team_lines:
        base[("home", line)] = float(np.mean([m.home_count > line for m in train_all]))
        base[("away", line)] = float(np.mean([m.away_count > line for m in train_all]))

    # The adaptive benchmark: the frequency over the previous `base_window`
    # matches, recomputed for every fixture from matches played before it.
    outcomes = {
        (scope, line): np.array(
            [m.observed(scope) > line for m in matches], float
        )
        for scope, line in base
        if scope == observable(scope)
    }
    position = {m.match_id: i for i, m in enumerate(matches)}

    def rolling_rate(scope: str, line: float, match: CountMatch) -> float:
        i = position[match.match_id]
        history = outcomes[(scope, line)][max(0, i - base_window) : i]
        return float(history.mean()) if len(history) else base[(scope, line)]

    out = Backtest(stat=stat, competition=competition)

    def score(scope: str, line: float, p: float, happened: bool, match: CountMatch) -> None:
        key = (scope, line)
        res = out.results.get(key)
        if res is None:
            res = out.results[key] = LineResult(scope, line)
        # Every variant of a market is judged against the same benchmark as the
        # market itself, so a blend cannot look good by being scored against an
        # easier target than the model it is replacing.
        rate = base[(observable(scope), line)]
        recent = rolling_rate(observable(scope), line, match)
        res.n += 1
        res.model_ll -= np.log(_clip(p if happened else 1 - p))
        res.base_ll -= np.log(_clip(rate if happened else 1 - rate))
        res.rolling_ll -= np.log(_clip(recent if happened else 1 - recent))
        res.predicted.append(p)
        res.actual.append(int(happened))

    models: Models | None = None
    recal: dict[tuple[str, float], cal.Recalibrator] = {}
    last_fit: date | None = None
    # The recalibration is fitted on the predictions this same model already
    # made, on matches that have since been played. That is what a live system
    # can do, and it avoids the trap of calibrating against a deliberately
    # weakened copy of the model, whose overconfidence is not the real one's.
    seen: dict[tuple[str, float], list[tuple[float, int]]] = {}
    warmed_up = False

    def refit_recalibrators() -> dict[tuple[str, float], cal.Recalibrator]:
        return {
            key: cal.Recalibrator.fit(
                np.array([p for p, _ in pairs]), np.array([y for _, y in pairs])
            )
            for key, pairs in seen.items()
        }

    for m in test:
        if last_fit is None or (m.kickoff - last_fit) >= timedelta(days=refit_every_days):
            history = [h for h in matches if h.kickoff < m.kickoff]
            if len(history) >= min_train:
                models = fit_models(history, m.kickoff, spec, xi, features)
                last_fit = m.kickoff
                out.n_refits += 1
                if warmed_up:
                    recal = refit_recalibrators()
        if models is None:
            continue

        row = features.matrix([m.match_id]) if features is not None else None
        probabilities = models.probabilities(m, spec, include_convolution, row)
        for key, p in probabilities.items():
            seen.setdefault(key, []).append((p, int(m.observed(key[0]) > key[1])))

        # Nothing is scored during the warm-up. Scoring the raw model over a
        # longer span than the calibrated one would make the two columns
        # incomparable, which is the only comparison this table exists for.
        if not warmed_up:
            if min((len(v) for v in seen.values()), default=0) >= warmup_matches:
                warmed_up = True
                # Fit immediately rather than waiting for the next refit, so the
                # raw and calibrated columns cover exactly the same fixtures.
                recal = refit_recalibrators()
            continue

        out.n_matches += 1
        for (scope, line), p in probabilities.items():
            happened = m.observed(scope) > line
            score(scope, line, p, happened, m)
            adjust = recal.get((scope, line))
            if adjust is not None and not adjust.is_identity:
                score(CALIBRATED[scope], line, adjust.apply(p), happened, m)
    out.recalibrators = recal
    return out


NOTES = {
    "convolved": "control: two independent sides added. Same mean, wrong spread.",
    "total calibrated": "the numbers that would be published.",
    "total blend": "same rate, corrected by the feature layer.",
}


def report(bt: Backtest, scopes: tuple[str, ...] | None = None) -> None:
    print(f"\n=== {bt.stat}, {bt.competition}: {bt.n_matches:,} matches scored, "
          f"{bt.n_refits} refits ===")
    order = scopes or (
        "total", "total calibrated", "total blend", "total blend calibrated",
        "convolved",
        "home", "home calibrated", "home blend", "home blend calibrated",
        "away", "away calibrated", "away blend", "away blend calibrated",
    )
    for scope in order:
        rows = bt.scope(scope)
        if not rows:
            continue
        print(f"\n  {scope}")
        if scope in NOTES:
            print(f"    {NOTES[scope]}")
        print(f"    {'line':>6}  {'n':>5}  {'model':>8}  {'rolling':>8}  {'vs roll':>8}  "
              f"{'fixed':>8}  {'vs fixed':>9}  {'bias':>7}  {'worst':>6}")
        for (_, line), r in sorted(rows.items()):
            print(f"    {line:>6}  {r.n:>5}  {r.model:>8.5f}  {r.rolling:>8.5f}  "
                  f"{r.gain_vs_rolling:>7.2f}%  {r.base:>8.5f}  {r.gain:>8.2f}%  "
                  f"{r.bias:>+7.3f}  {r.worst_bucket:>5.1%}")


def calibration_table(bt: Backtest, scope: str, line: float, buckets: int = 5) -> None:
    """Do the published percentages happen that often? Log-loss can look fine
    while the numbers on the page are systematically wrong, so this is checked
    separately and is what decides whether a market is fit to show a user."""
    r = bt.results.get((scope, line))
    if r is None:
        return
    print(f"\n  reliability, {scope} line {line}")
    for predicted, actual, n in cal.reliability(
        np.array(r.predicted), np.array(r.actual), buckets
    ):
        print(f"    predicted {predicted:>6.1%}  ->  actual {actual:>6.1%}   (n={n:>4})")
    print(f"    worst bucket error: {r.worst_bucket:.1%}")
