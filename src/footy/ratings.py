"""Elo ratings computed from results already in the database.

Kept deliberately parameterised. Every constant here is a modelling choice that
should be judged by whether it improves out-of-sample log-loss, not accepted
because it is conventional, so the feature step can sweep them.

Two variants are produced from the same algorithm. The goals variant uses the
scoreline. The xG variant substitutes expected goals, on the theory that it
measures the performance rather than its finishing luck and so should track a
team's real strength with less lag.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta

# Sentinel end date for a rating that is still current.
OPEN_ENDED = date(9999, 12, 31)


@dataclass(frozen=True)
class EloParams:
    k: float = 20.0
    home_advantage: float = 65.0
    # Fraction of the way a rating is pulled back to the mean between seasons.
    # Squads change, so last May's rating overstates what is known in August.
    season_regression: float = 0.25
    start_rating: float = 1500.0
    # A three-goal win says more than a one-goal win. Weighting K by margin is
    # the standard World Football Elo treatment.
    use_margin: bool = True


@dataclass(frozen=True)
class MatchInput:
    match_id: int
    kickoff_date: date
    season_start_year: int
    home_team_id: int
    away_team_id: int
    home_value: float
    away_value: float


@dataclass(frozen=True)
class RatingPeriod:
    team_id: int
    valid_from: date
    valid_to: date
    rating: float


def _margin_multiplier(margin: float, use_margin: bool) -> float:
    if not use_margin:
        return 1.0
    m = abs(margin)
    if m <= 1:
        return 1.0
    if m < 3:
        return 1.5
    return (11.0 + m) / 8.0


def _score(home_value: float, away_value: float) -> float:
    """Match outcome as a number in [0, 1] from the home side's perspective.

    For goals this is simply win/draw/loss. For xG a draw is a band rather than
    an exact tie, because expected goals are continuous and two teams never
    produce precisely equal xG.
    """
    diff = home_value - away_value
    if abs(diff) < 0.25:
        return 0.5
    return 1.0 if diff > 0 else 0.0


def compute(
    matches: Iterable[MatchInput], params: EloParams | None = None
) -> Iterator[RatingPeriod]:
    """Walk matches in chronological order, emitting each rating's validity range.

    Ratings are emitted as ranges so that a lookup by match date returns the
    rating as it stood before that match was played. A rating produced by a match
    takes effect the day after it, which keeps the feature layer honest: nothing
    can accidentally read a rating that already contains the result being predicted.
    """
    p = params or EloParams()
    rating: dict[int, float] = {}
    # Where each team's current rating period began.
    since: dict[int, date] = {}
    season: dict[int, int] = {}

    ordered = sorted(matches, key=lambda m: (m.kickoff_date, m.match_id))

    for m in ordered:
        for team_id in (m.home_team_id, m.away_team_id):
            if team_id not in rating:
                rating[team_id] = p.start_rating
                # A team's opening rating is knowable from the start of time; it
                # carries no information about any match.
                since[team_id] = date.min
                season[team_id] = m.season_start_year
            elif season[team_id] != m.season_start_year:
                # Close last season's rating the day before this match, then regress.
                # The new period opens on match day itself, so the two never share
                # a date — overlapping ranges would make an as-of lookup ambiguous.
                yield RatingPeriod(
                    team_id,
                    since[team_id],
                    m.kickoff_date - timedelta(days=1),
                    rating[team_id],
                )
                rating[team_id] += (p.start_rating - rating[team_id]) * p.season_regression
                since[team_id] = m.kickoff_date
                season[team_id] = m.season_start_year

        home, away = rating[m.home_team_id], rating[m.away_team_id]
        expected_home = 1.0 / (1.0 + 10 ** ((away - (home + p.home_advantage)) / 400.0))
        actual_home = _score(m.home_value, m.away_value)
        adjust = (
            p.k
            * _margin_multiplier(m.home_value - m.away_value, p.use_margin)
            * (actual_home - expected_home)
        )

        effective_from = m.kickoff_date + timedelta(days=1)
        for team_id, delta in ((m.home_team_id, adjust), (m.away_team_id, -adjust)):
            # The rating held up to and including match day; the new one starts after.
            if since[team_id] <= m.kickoff_date:
                yield RatingPeriod(team_id, since[team_id], m.kickoff_date, rating[team_id])
            rating[team_id] += delta
            since[team_id] = effective_from

    for team_id, value in rating.items():
        yield RatingPeriod(team_id, since[team_id], OPEN_ENDED, value)


def with_start(period: RatingPeriod, earliest: date) -> RatingPeriod:
    """Clamp the open-ended first period to a real date for storage."""
    return replace(period, valid_from=max(period.valid_from, earliest))
