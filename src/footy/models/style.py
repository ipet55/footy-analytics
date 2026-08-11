"""Style of play: how a team plays, as opposed to how well.

Dixon-Coles reduces a club to two numbers, an attack rating and a defence
rating. Two teams can share both and still be nothing alike — one pressing high
and conceding the counter, the other sitting deep and inviting pressure. If that
difference matters to a scoreline, the team model cannot see it.

Two measures, both from Understat and both with full coverage back to 2014-15:

    ppda              passes the opponent completes per defensive action. Low
                      means a high press. Right-skewed, so we work with its log.
    deep_completions  passes completed within roughly 20 metres of goal, which
                      is territorial penetration rather than shot volume.

These are traits rather than match noise, which is the thing worth establishing
before modelling anything with them. Split-half reliability within a team-season
is 0.91 for pressing and 0.93 for deep completions, and a team's pressing
carries over to the following season at r=0.73. Per-team home advantage was
rejected in this project for failing exactly that test.

Because the trait is stable, the window is long: estimation noise dominates, so
twenty matches beats ten even though it reaches back across a season boundary.

Point-in-time correctness is structural, as in `squad`. Matches are walked in
order, features are read off the state accumulated so far, and only then is the
match folded into that state. A feature cannot see its own match because the
match is not yet in the state that produced it.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from math import log

from footy import db

# Matches of history behind each feature. Long because style is stable; see the
# reliability figures above.
WINDOW = 20

# The recent form window, used only for the deltas below.
SHORT_WINDOW = 5

# A team needs this many prior matches before we claim to know its style.
MIN_MATCHES = 8

FEATURES = (
    # How hard this team presses. Higher is more intense.
    "press",
    # Territory it reaches, and territory it gives up.
    "deep_for",
    "deep_against",
    # Recent style minus the team's own baseline. These exist because the levels
    # above turned out to be useless, and for a reason that predicts the deltas
    # might not be: a stable trait is already inside the team's fitted attack and
    # defence ratings, so restating it adds parameters and no information. What a
    # rating cannot absorb is a team that has just changed how it plays — a new
    # manager, a tactical switch — because the rating is an average over years.
    "press_delta",
    "deep_for_delta",
)


@dataclass
class TeamMatch:
    """One team's side of one match."""

    match_id: int
    kickoff: date
    team_id: int
    opponent_id: int
    ppda: float | None
    deep: float | None


def _mean(values: deque) -> float:
    return sum(values) / len(values)


def _recent(values: deque) -> float:
    window = list(values)[-SHORT_WINDOW:]
    return sum(window) / len(window)


@dataclass
class _TeamState:
    press: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    deep_for: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    deep_against: deque = field(default_factory=lambda: deque(maxlen=WINDOW))

    def features(self) -> dict[str, float] | None:
        if len(self.press) < MIN_MATCHES:
            return None
        press = _mean(self.press)
        deep_for = _mean(self.deep_for)
        return {
            "press": press,
            "deep_for": deep_for,
            "deep_against": _mean(self.deep_against),
            "press_delta": _recent(self.press) - press,
            "deep_for_delta": _recent(self.deep_for) - deep_for,
        }


def load(competition: str) -> list[TeamMatch]:
    """Every team-match we hold style figures for, oldest first."""
    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            """
            select st.match_id, m.kickoff_date, st.team_id, st.opponent_team_id,
                   st.ppda::float, st.deep_completions::float
              from core.match_team_stat st
              join core.match m on m.match_id = st.match_id
              join core.competition c on c.competition_id = m.competition_id
             where c.code = %s
               and st.period = 'FT'
               and m.home_goals_ft is not null
             order by m.kickoff_date, st.match_id
            """,
            (competition,),
        )
    return [TeamMatch(*r) for r in rows]


def build(rows: list[TeamMatch]) -> dict[tuple[int, int], dict[str, float]]:
    """Style features for every team-match, using only earlier matches.

    Deep completions conceded need the other team's row, so matches are handled
    as pairs rather than one side at a time.
    """
    by_match: dict[int, list[TeamMatch]] = defaultdict(list)
    order: list[int] = []
    for r in rows:
        if r.match_id not in by_match:
            order.append(r.match_id)
        by_match[r.match_id].append(r)

    state: dict[int, _TeamState] = defaultdict(_TeamState)
    out: dict[tuple[int, int], dict[str, float]] = {}

    for match_id in order:
        sides = by_match[match_id]
        if len(sides) != 2:
            continue

        for side in sides:
            features = state[side.team_id].features()
            if features is not None:
                out[(match_id, side.team_id)] = features

        # Only now does the match become history.
        first, second = sides
        for side, other in ((first, second), (second, first)):
            if side.ppda is None or side.deep is None or other.deep is None:
                continue
            if side.ppda <= 0:
                continue
            team = state[side.team_id]
            team.press.append(-log(side.ppda))
            team.deep_for.append(side.deep)
            team.deep_against.append(other.deep)

    return out
