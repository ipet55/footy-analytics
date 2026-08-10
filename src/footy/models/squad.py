"""Squad strength: what the team models cannot see.

Dixon-Coles gives a club one attack rating and one defence rating estimated over
a decade of matches. It has no way to know that seven of today's eleven were on
the bench a month ago, or that the striker who earned the rating is injured.
This module turns team sheets into features that say so.

Point-in-time correctness is structural rather than checked afterwards. Matches
are walked in chronological order; the features for a match are read off the
state accumulated so far, and only then is the match folded into that state. A
feature cannot see its own match because it is computed before the match exists
in the state, not because a date filter says so.

One honest caveat about what this measures. It uses the lineup that actually
started, which is known about an hour before kickoff, not the lineup that could
have been predicted the day before. That makes any result here an upper bound on
what player data is worth in production. It is the right first question: if
knowing the true eleven does not help, knowing a guess at it certainly will not.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date

from footy import db

# How many of a team's recent matches define "the first-choice eleven". Ten is
# roughly two months of league football, long enough to be stable and short
# enough to notice a January signing.
FORM_WINDOW = 10

# A player counts as a regular if he has played this share of available minutes.
REGULAR_SHARE = 0.6

FEATURES = (
    "xi_continuity",
    "xi_regulars",
    "xi_goal_threat",
    "xi_experience",
    "key_players_absent",
    # The same continuity measure, but over the eleven we would have guessed
    # rather than the eleven that played. See _forecast_continuity.
    "xi_continuity_forecast",
)

# How many recent squads a regular must be missing from before we call him
# unavailable. One is too jumpy — players are rested for a single match all the
# time — and three is too slow to notice an injury.
ABSENT_MATCHES = 2


@dataclass
class Appearance:
    match_id: int
    kickoff: date
    team_id: int
    player_id: int
    is_starter: bool
    minutes: int
    goals: int
    assists: int
    reds: int = 0


@dataclass
class _PlayerState:
    """A player's history, as it stood before the match being featurised."""

    minutes: float = 0.0
    goals: float = 0.0
    assists: float = 0.0
    appearances: int = 0


@dataclass
class _TeamState:
    """Recent team sheets, newest last."""

    recent: deque = field(default_factory=lambda: deque(maxlen=FORM_WINDOW))
    # Everyone named, including unused substitutes. Being on the bench is the
    # difference between rested and unavailable, and only this records it.
    squads: deque = field(default_factory=lambda: deque(maxlen=FORM_WINDOW))
    sent_off: set = field(default_factory=set)

    def minutes_by_player(self) -> dict[int, float]:
        out: dict[int, float] = defaultdict(float)
        for sheet in self.recent:
            for player_id, minutes in sheet.items():
                out[player_id] += minutes
        return out

    def available_minutes(self) -> float:
        return 90.0 * len(self.recent)

    def presumed_available(self, player_id: int) -> bool:
        """Would we have expected this player to be selectable, before kickoff?

        Two signals, both knowable in advance and both already in the sheets we
        hold: a red card last time out means a suspension, and vanishing from
        the squad entirely for a couple of matches means an injury. Neither is
        an injury feed, but neither needs one.
        """
        if player_id in self.sent_off:
            return False
        window = list(self.squads)[-ABSENT_MATCHES:]
        return not window or any(player_id in squad for squad in window)


def load(competition: str) -> list[Appearance]:
    """Every appearance we hold for a competition, oldest first."""
    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            """
            select a.match_id, m.kickoff_date, a.team_id, a.player_id,
                   a.is_starter, a.minutes,
                   coalesce(a.goals, 0), coalesce(a.assists, 0),
                   coalesce(a.reds, 0)
              from core.appearance a
              join core.match m on m.match_id = a.match_id
              join core.competition c on c.competition_id = m.competition_id
             where c.code = %s
             order by m.kickoff_date, a.match_id
            """,
            (competition,),
        )
    return [Appearance(*r) for r in rows]


def _forecast_xi(team: _TeamState) -> tuple[float, list[int]] | None:
    """Continuity of the eleven we would have guessed, not the one that played.

    This is the version that could actually be served, because it uses nothing
    published after kickoff. The eleven is the most-used recent players who are
    not suspended and have not dropped out of the squad.

    The measure only varies because of who is *missing*. Guessing the eleven as
    "whoever normally plays" would give every team a full-strength side and a
    feature with no variance; what carries information is a regular being
    unavailable, which is knowable in advance.
    """
    minutes = team.minutes_by_player()
    available = team.available_minutes()
    if available <= 0:
        return None
    selectable = [p for p in minutes if team.presumed_available(p)]
    if len(selectable) < 11:
        return None
    eleven = sorted(selectable, key=lambda p: -minutes[p])[:11]
    return sum(min(minutes[p] / available, 1.0) for p in eleven) / 11, eleven


def _features_for(team: _TeamState, players: dict[int, _PlayerState],
                  starters: list[int], squad: set[int]) -> dict[str, float] | None:
    """Features for one team sheet, from state that predates its match."""
    if not team.recent or not starters:
        return None

    minutes = team.minutes_by_player()
    available = team.available_minutes()
    if available <= 0:
        return None

    # How much of the recent eleven is still the eleven. One means an unchanged
    # side, zero means a team of players who have not featured.
    shares = [min(minutes.get(p, 0.0) / available, 1.0) for p in starters]
    continuity = sum(shares) / len(shares)

    regulars = sum(1 for s in shares if s >= REGULAR_SHARE)

    # Attacking output the starters bring with them, per 90 played. Deliberately
    # career-to-date rather than recent form: recent form is already in the
    # team's fitted attack rating, whereas who is on the pitch is not.
    threat = 0.0
    experience = 0.0
    for p in starters:
        st = players.get(p)
        if st and st.minutes >= 90:
            threat += 90.0 * (st.goals + st.assists) / st.minutes
        if st:
            experience += st.appearances
    threat /= len(starters)
    experience /= len(starters)

    # Regulars who are not even on the bench. The clearest injury signal
    # available without an injury feed.
    key = sorted(minutes, key=lambda p: -minutes[p])[:11]
    absent = sum(1 for p in key if p not in squad and minutes[p] / available >= REGULAR_SHARE)

    predicted = _forecast_xi(team)
    if predicted is None:
        return None
    forecast, eleven = predicted

    return {
        "xi_continuity": continuity,
        "xi_regulars": float(regulars),
        "xi_goal_threat": threat,
        "xi_experience": experience,
        "key_players_absent": float(absent),
        "xi_continuity_forecast": forecast,
        # Diagnostic only, and deliberately not in FEATURES: it is measured
        # against the eleven that played, so it could never be served.
        "forecast_hits": float(len(set(eleven) & set(starters))),
    }


def build(appearances: list[Appearance]) -> dict[tuple[int, int], dict[str, float]]:
    """Features for every (match_id, team_id) we can compute them for.

    Chronological single pass. Everything a match's features depend on has
    already happened, because the match is folded into the state only after its
    features have been taken.
    """
    by_match: dict[int, dict[int, list[Appearance]]] = {}
    order: list[int] = []
    for a in appearances:
        if a.match_id not in by_match:
            by_match[a.match_id] = defaultdict(list)
            order.append(a.match_id)
        by_match[a.match_id][a.team_id].append(a)

    players: dict[int, _PlayerState] = defaultdict(_PlayerState)
    teams: dict[int, _TeamState] = defaultdict(_TeamState)
    out: dict[tuple[int, int], dict[str, float]] = {}

    for match_id in order:
        sides = by_match[match_id]
        for team_id, apps in sides.items():
            starters = [a.player_id for a in apps if a.is_starter]
            squad = {a.player_id for a in apps}
            row = _features_for(teams[team_id], players, starters, squad)
            if row is not None:
                out[(match_id, team_id)] = row

        # Only now does this match become history.
        for team_id, apps in sides.items():
            state = teams[team_id]
            state.recent.append(
                {a.player_id: float(a.minutes) for a in apps if a.minutes > 0}
            )
            state.squads.append({a.player_id for a in apps})
            # A red card rules the player out of the next match only, so this
            # replaces rather than accumulates.
            state.sent_off = {a.player_id for a in apps if a.reds}
            for a in apps:
                st = players[a.player_id]
                st.minutes += a.minutes
                st.goals += a.goals
                st.assists += a.assists
                st.appearances += 1 if a.minutes > 0 else 0

    return out
