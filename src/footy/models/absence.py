"""Fold reported absences into a fixture's rates.

Dixon-Coles gives a club one attack rating and one defence rating. It cannot
see that the striker who earned the attack rating is in the treatment room.
Until this module, the page said so in a sentence and left the percentages
alone. That was the wrong split: the information is known before kickoff, it
is about the players who produce the goals the model is pricing, and a
probability that ignores it is answering a different match.

What this is, honestly. It is a serving-time prior, not a coefficient we
fitted. Historical pre-match absence lists do not exist for most of the
training window, so there is no walk-forward in which to measure the size of
the move. The sizes below are chosen so a star striker (around 20% of a
team's goals) cuts that side's scoring rate by about 10%, a starting
goalkeeper being out raises the concede rate by about 12%, and five fringe
squad players barely register. Caps stop a long injury list from inventing
a different club.

Doubtful players count at 40% of a confirmed absence. A manager's problem is
ordered that way, and treating a doubt as a certainty would overstate what
is known.

Cards and fouls are left alone. Those markets are driven by the referee and
by the match's temperament, not by which of the regulars is in the XI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import psycopg

from footy import db

# A confirmed absence of a player who scored this share of the team's goals
# cuts the team's scoring rate by this fraction of that share. 0.50 means a
# striker on 20% of the goals costs 10% of the attack rate, which is the
# replacement being worse rather than the goals vanishing.
ATTACK_FROM_GOALS = 0.50
ATTACK_FROM_MINUTES = {
    "attack": 0.15,
    "midfield": 0.10,
    "defender": 0.00,
    "keeper": 0.00,
}
DEFENCE_FROM_MINUTES = {
    "attack": 0.00,
    "midfield": 0.08,
    "defender": 0.22,
    "keeper": 0.35,
}
DOUBTFUL_WEIGHT = 0.40
MAX_ATTACK_CUT = 0.25
MAX_DEFENCE_HIT = 0.20

# A player is "key" when he is a regular or a meaningful share of the attack.
# The page uses the same rule so the sentence and the number agree.
KEY_MINUTE_SHARE = 0.18
KEY_GOAL_SHARE = 0.05


def _line(position: str | None) -> str:
    if position is None:
        return "midfield"
    token = position.strip().lower()
    if token in {"g", "goalkeeper", "gk"}:
        return "keeper"
    if token in {"d", "defender", "defence", "defense"}:
        return "defender"
    if token in {"f", "attacker", "attack", "forward"}:
        return "attack"
    if token in {"m", "midfielder", "midfield"}:
        return "midfield"
    return "midfield"


@dataclass(frozen=True)
class Missing:
    player_id: int | None
    player_name: str
    status: str
    position: str | None
    goal_share: float
    minute_share: float

    @property
    def weight(self) -> float:
        return 1.0 if self.status == "out" else DOUBTFUL_WEIGHT

    @property
    def line(self) -> str:
        return _line(self.position)

    @property
    def is_key(self) -> bool:
        return (
            self.minute_share >= KEY_MINUTE_SHARE
            or self.goal_share >= KEY_GOAL_SHARE
            or self.line == "keeper" and self.minute_share >= 0.10
        )

    def attack_hit(self) -> float:
        return self.weight * (
            ATTACK_FROM_GOALS * self.goal_share
            + ATTACK_FROM_MINUTES[self.line] * self.minute_share
        )

    def defence_hit(self) -> float:
        return self.weight * DEFENCE_FROM_MINUTES[self.line] * self.minute_share


@dataclass
class SideShock:
    team_id: int
    attack_factor: float = 1.0
    defence_factor: float = 1.0
    missing: list[Missing] = field(default_factory=list)

    @property
    def missing_key(self) -> int:
        return sum(1 for m in self.missing if m.is_key and m.status == "out")

    def moves(self) -> bool:
        return self.attack_factor < 0.999 or self.defence_factor > 1.001

    def detail(self) -> list[dict[str, Any]]:
        return [
            {
                "player_id": m.player_id,
                "player_name": m.player_name,
                "status": m.status,
                "position": m.position,
                "goal_share": round(m.goal_share, 4),
                "minute_share": round(m.minute_share, 4),
                "attack_hit": round(m.attack_hit(), 4),
                "defence_hit": round(m.defence_hit(), 4),
                "is_key": m.is_key,
            }
            for m in self.missing
            if m.attack_hit() > 0 or m.defence_hit() > 0 or m.is_key
        ]


@dataclass
class FixtureShock:
    match_id: int
    home: SideShock
    away: SideShock
    p_home_base: float | None = None
    p_draw_base: float | None = None
    p_away_base: float | None = None

    @property
    def home_rate_mult(self) -> float:
        """Home scoring rate: own attack × opponent's concede inflation."""
        return self.home.attack_factor * self.away.defence_factor

    @property
    def away_rate_mult(self) -> float:
        return self.away.attack_factor * self.home.defence_factor

    def moves(self) -> bool:
        return self.home.moves() or self.away.moves()


def shock_from_missing(team_id: int, missing: list[Missing]) -> SideShock:
    """Turn a list of absences into the two rate factors.

    Hits add. The cap is what stops a six-man injury list from inventing a
    League Two side: the replacements exist, they are just worse.
    """
    attack_cut = min(MAX_ATTACK_CUT, sum(m.attack_hit() for m in missing))
    defence_hit = min(MAX_DEFENCE_HIT, sum(m.defence_hit() for m in missing))
    return SideShock(
        team_id=team_id,
        attack_factor=1.0 - attack_cut,
        defence_factor=1.0 + defence_hit,
        missing=missing,
    )


def load_shocks(
    conn: psycopg.Connection, match_ids: list[int]
) -> dict[int, FixtureShock]:
    """One shock per requested match that has any reported absence.

    Players with no recorded history at the club contribute nothing: we do
    not know whether they are key, and guessing would move numbers for
    names we have only just seen. That is conservative and it is the
    right kind of conservative — a newly signed striker who is injured is
    a real miss, and also one we cannot size from this database yet.
    """
    if not match_ids:
        return {}

    rows = db.fetch_all(
        conn,
        """
        with fixture as (
            select m.match_id, m.home_team_id, m.away_team_id
              from core.match m
             where m.match_id = any(%s)
        ),
        sides as (
            select match_id, home_team_id as team_id from fixture
            union all
            select match_id, away_team_id from fixture
        ),
        history as (
            select st.team_id,
                   st.player_id,
                   sum(st.minutes) as minutes,
                   sum(st.goals) as goals
              from public.player_season_stat st
              join sides s on s.team_id = st.team_id
             where st.start_year >= extract(year from current_date)::int - 2
             group by st.team_id, st.player_id
        ),
        team_tot as (
            select team_id,
                   sum(minutes) as minutes,
                   sum(goals) as goals
              from history
             group by team_id
        )
        select a.match_id,
               a.team_id,
               a.player_id,
               a.player_name,
               a.status,
               coalesce(sm.position, (
                   select s.position from public.team_recent_starts s
                    where s.team_id = a.team_id
                      and core.norm_name(s.player_name)
                        = core.norm_name(a.player_name)
                    limit 1
               )) as position,
               coalesce(
                   h.goals::float / nullif(t.goals, 0),
                   0
               ) as goal_share,
               coalesce(
                   h.minutes::float / nullif(t.minutes, 0),
                   0
               ) as minute_share
          from core.match_absence a
          join sides s using (match_id, team_id)
          left join core.squad_member sm
                 on sm.team_id = a.team_id
                and sm.player_id = a.player_id
          left join history h
                 on h.team_id = a.team_id
                and h.player_id = a.player_id
          left join team_tot t on t.team_id = a.team_id
        """,
        (match_ids,),
    )

    by_match: dict[int, dict[int, list[Missing]]] = {}
    home_away: dict[int, tuple[int, int]] = {}
    meta = db.fetch_all(
        conn,
        """
        select match_id, home_team_id, away_team_id
          from core.match
         where match_id = any(%s)
        """,
        (match_ids,),
    )
    for match_id, home_id, away_id in meta:
        home_away[int(match_id)] = (int(home_id), int(away_id))

    for match_id, team_id, player_id, name, status, position, goal_share, minute_share in rows:
        by_match.setdefault(int(match_id), {}).setdefault(int(team_id), []).append(
            Missing(
                player_id=int(player_id) if player_id is not None else None,
                player_name=name,
                status=status,
                position=position,
                goal_share=float(goal_share or 0),
                minute_share=float(minute_share or 0),
            )
        )

    out: dict[int, FixtureShock] = {}
    for match_id, (home_id, away_id) in home_away.items():
        sides = by_match.get(match_id, {})
        if not sides:
            continue
        out[match_id] = FixtureShock(
            match_id=match_id,
            home=shock_from_missing(home_id, sides.get(home_id, [])),
            away=shock_from_missing(away_id, sides.get(away_id, [])),
        )
    return out


def write_effects(
    conn: psycopg.Connection, shocks: list[FixtureShock]
) -> int:
    """Replace the stored effect for each fixture that actually moved."""
    if not shocks:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "delete from ml.absence_effect where match_id = any(%s)",
            ([s.match_id for s in shocks],),
        )
        rows = []
        for shock in shocks:
            if not shock.moves():
                continue
            for side in (shock.home, shock.away):
                if not side.moves() and side.missing_key == 0:
                    continue
                rows.append(
                    (
                        shock.match_id,
                        side.team_id,
                        round(side.attack_factor, 4),
                        round(side.defence_factor, 4),
                        side.missing_key,
                        json.dumps(side.detail()),
                        shock.p_home_base,
                        shock.p_draw_base,
                        shock.p_away_base,
                    )
                )
        if not rows:
            return 0
        cur.executemany(
            """
            insert into ml.absence_effect
              (match_id, team_id, attack_factor, defence_factor,
               missing_key, detail, p_home_base, p_draw_base, p_away_base)
            values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            """,
            rows,
        )
        return len(rows)
