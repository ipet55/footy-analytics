"""Populate the feature layer.

Every rolling aggregate here uses the frame

    rows between N preceding and 1 preceding

so the window stops at the previous fixture and can never include the match
being described. That `1 preceding` is the whole ballgame: with `current row`
instead, each row would contain its own result, the backtest would look
extraordinary, and the model would be worthless live.
"""

from __future__ import annotations

import psycopg

# Stats averaged over a plain count of previous matches.
ROLLING = {
    "gf": "goals_for",
    "ga": "goals_against",
    "xgf": "xg_for",
    "xga": "xg_against",
    "ppg": "points",
    "corners_f": "corners_for",
    "corners_a": "corners_against",
    "shots_f": "shots_for",
    "shots_a": "shots_against",
    "fouls": "fouls_committed",
    "yellows": "yellows_for",
}

# Which of those are also computed restricted to the same venue.
VENUE = {
    "gf": "goals_for",
    "ga": "goals_against",
    "xgf": "xg_for",
    "xga": "xg_against",
    "corners_f": "corners_for",
    "corners_a": "corners_against",
    "yellows": "yellows_for",
}


def _rolling_terms() -> str:
    """Rolling averages for the 5 and 10 match windows, plus xG over 20."""
    parts = []
    for window in (5, 10):
        for alias, column in ROLLING.items():
            parts.append(
                f"avg({column}) over (partition by team_id order by kickoff_date, match_id "
                f"rows between {window} preceding and 1 preceding) as {alias}_{window}"
            )
    for alias in ("xgf", "xga"):
        column = ROLLING[alias]
        parts.append(
            f"avg({column}) over (partition by team_id order by kickoff_date, match_id "
            f"rows between 20 preceding and 1 preceding) as {alias}_20"
        )
    # Venue-restricted: same frame, but partitioned by venue as well, so the
    # previous 10 matches means the previous 10 at this venue.
    for alias, column in VENUE.items():
        parts.append(
            f"avg({column}) over (partition by team_id, is_home order by kickoff_date, match_id "
            f"rows between 10 preceding and 1 preceding) as {alias}_venue_10"
        )
    return ",\n           ".join(parts)


TEAM_MATCH_SQL = f"""
insert into features.team_match (
    match_id, team_id, opponent_team_id, competition_id, season_id,
    kickoff_date, as_of, is_home, matches_before,
    {", ".join(f"{a}_5" for a in ROLLING)},
    {", ".join(f"{a}_10" for a in ROLLING)},
    xgf_20, xga_20,
    {", ".join(f"{a}_venue_10" for a in VENUE)},
    season_matches, season_ppg, season_xgf, season_xga,
    rest_days, elo_xg, elo_goals, clubelo
)
with base as (
    select tm.match_id, tm.team_id, tm.opponent_team_id, tm.competition_id,
           tm.season_id, tm.kickoff_date,
           coalesce(m.kickoff_utc, tm.kickoff_date::timestamptz) as as_of,
           tm.is_home,
           tm.goals_for, tm.goals_against, tm.xg_for, tm.xg_against, tm.points,
           tm.corners_for, tm.corners_against, tm.shots_for, tm.shots_against,
           tm.fouls_committed, tm.yellows_for
      from core.team_match tm
      join core.match m on m.match_id = tm.match_id
     where tm.period = 'FT'
),
rolled as (
    select match_id, team_id, opponent_team_id, competition_id, season_id,
           kickoff_date, as_of, is_home,
           count(*) over (partition by team_id order by kickoff_date, match_id
                          rows between unbounded preceding and 1 preceding) as matches_before,
           {_rolling_terms()},
           -- Season to date. Excluding the current row here matters just as much.
           count(*) over (partition by team_id, season_id order by kickoff_date, match_id
                          rows between unbounded preceding and 1 preceding) as season_matches,
           avg(points) over (partition by team_id, season_id order by kickoff_date, match_id
                             rows between unbounded preceding and 1 preceding) as season_ppg,
           avg(xg_for) over (partition by team_id, season_id order by kickoff_date, match_id
                             rows between unbounded preceding and 1 preceding) as season_xgf,
           avg(xg_against) over (partition by team_id, season_id order by kickoff_date, match_id
                                 rows between unbounded preceding and 1 preceding) as season_xga,
           kickoff_date - lag(kickoff_date) over (partition by team_id
                                                 order by kickoff_date, match_id) as rest_days
      from base
)
select r.match_id, r.team_id, r.opponent_team_id, r.competition_id, r.season_id,
       r.kickoff_date, r.as_of, r.is_home, r.matches_before,
       {", ".join(f"r.{a}_5" for a in ROLLING)},
       {", ".join(f"r.{a}_10" for a in ROLLING)},
       r.xgf_20, r.xga_20,
       {", ".join(f"r.{a}_venue_10" for a in VENUE)},
       r.season_matches, r.season_ppg, r.season_xgf, r.season_xga,
       -- Cap long gaps without inventing one. LEAST ignores NULLs, so
       -- least(null, 365) is 365, which would give a team's first ever match a
       -- year of rest instead of no value at all.
       case when r.rest_days is null then null
            else least(r.rest_days, 365) end as rest_days,
       xg.rating, gl.rating, ce.rating
  from rolled r
  left join core.team_rating xg
         on xg.team_id = r.team_id
        and xg.source_id = (select source_id from core.source where code = 'elo_xg')
        and r.kickoff_date between xg.valid_from and xg.valid_to
  left join core.team_rating gl
         on gl.team_id = r.team_id
        and gl.source_id = (select source_id from core.source where code = 'elo_goals')
        and r.kickoff_date between gl.valid_from and gl.valid_to
  left join core.team_rating ce
         on ce.team_id = r.team_id
        and ce.source_id = (select source_id from core.source where code = 'clubelo')
        and r.kickoff_date between ce.valid_from and ce.valid_to
on conflict (match_id, team_id) do nothing
"""


# Difficulty from fixed rating-difference thresholds. Quantiles would depend on
# the distribution of the whole dataset, which includes matches that had not been
# played when any given prediction would have been made.
MATCH_SQL = """
insert into features.match (
    match_id, competition_id, season_id, kickoff_date, as_of,
    h2h_matches, h2h_home_wins, h2h_draws, h2h_away_wins,
    h2h_avg_goals, h2h_avg_corners,
    rating_diff, difficulty_home, difficulty_away,
    market_p_home, market_p_draw, market_p_away
)
with pairs as (
    select m.match_id, m.competition_id, m.season_id, m.kickoff_date,
           coalesce(m.kickoff_utc, m.kickoff_date::timestamptz) as as_of,
           m.home_team_id, m.away_team_id, m.home_goals_ft, m.away_goals_ft
      from core.match m
     where m.home_goals_ft is not null
),
h2h as (
    -- Previous meetings of the same two clubs in the same competition, strictly
    -- before this fixture. Venue is normalised so a reverse fixture still counts,
    -- but wins are attributed to the current home side.
    select p.match_id,
           count(*)::smallint as h2h_matches,
           count(*) filter (
             where (q.home_team_id = p.home_team_id and q.home_goals_ft > q.away_goals_ft)
                or (q.away_team_id = p.home_team_id and q.away_goals_ft > q.home_goals_ft)
           )::smallint as h2h_home_wins,
           count(*) filter (where q.home_goals_ft = q.away_goals_ft)::smallint as h2h_draws,
           count(*) filter (
             where (q.home_team_id = p.away_team_id and q.home_goals_ft > q.away_goals_ft)
                or (q.away_team_id = p.away_team_id and q.away_goals_ft > q.home_goals_ft)
           )::smallint as h2h_away_wins,
           avg(q.home_goals_ft + q.away_goals_ft) as h2h_avg_goals,
           avg(hc.corners_for + hc.corners_against) as h2h_avg_corners
      from pairs p
      join core.match q
        on q.competition_id = p.competition_id
       and q.kickoff_date < p.kickoff_date
       and q.home_goals_ft is not null
       and ((q.home_team_id = p.home_team_id and q.away_team_id = p.away_team_id)
         or (q.home_team_id = p.away_team_id and q.away_team_id = p.home_team_id))
      left join core.team_match hc
             on hc.match_id = q.match_id and hc.team_id = q.home_team_id and hc.period = 'FT'
     group by p.match_id
),
rated as (
    select p.match_id, hr.rating - ar.rating as rating_diff
      from pairs p
      join core.source s on s.code = 'elo_xg'
      left join core.team_rating hr
             on hr.team_id = p.home_team_id and hr.source_id = s.source_id
            and p.kickoff_date between hr.valid_from and hr.valid_to
      left join core.team_rating ar
             on ar.team_id = p.away_team_id and ar.source_id = s.source_id
            and p.kickoff_date between ar.valid_from and ar.valid_to
)
select p.match_id, p.competition_id, p.season_id, p.kickoff_date, p.as_of,
       coalesce(h.h2h_matches, 0), coalesce(h.h2h_home_wins, 0),
       coalesce(h.h2h_draws, 0), coalesce(h.h2h_away_wins, 0),
       h.h2h_avg_goals, h.h2h_avg_corners,
       r.rating_diff,
       case
         when r.rating_diff is null then 3
         when r.rating_diff >=  150 then 1
         when r.rating_diff >=   50 then 2
         when r.rating_diff >   -50 then 3
         when r.rating_diff >  -150 then 4
         else 5
       end::smallint as difficulty_home,
       case
         when r.rating_diff is null then 3
         when -r.rating_diff >=  150 then 1
         when -r.rating_diff >=   50 then 2
         when -r.rating_diff >   -50 then 3
         when -r.rating_diff >  -150 then 4
         else 5
       end::smallint as difficulty_away,
       k.p_home, k.p_draw, k.p_away
  from pairs p
  left join h2h h on h.match_id = p.match_id
  left join rated r on r.match_id = p.match_id
  left join core.market_1x2_mv k on k.match_id = p.match_id and k.snapshot = 'closing'
on conflict (match_id) do nothing
"""


# Every materialized view derived from core, refreshed together here because
# this runs after every load and nothing else does.
#
# The first two are read by this build: `market_p_*` comes from
# core.market_1x2_mv, so building against a stale copy writes null market
# probabilities and the backtest then reports the market as `nan` — a silence
# that reads like "no odds exist" rather than "the view is behind". That is
# exactly what happened when the Eredivisie, Liga Portugal and Süper Lig were
# loaded with full Pinnacle coverage.
#
# The last three are not read by this build at all; they are what the team pages
# serve. They are refreshed here because the alternative is a second command
# somebody has to remember, and a stale team page is the same class of bug: it
# would show a season as finished several matches early and look entirely
# plausible doing it.
MATERIALIZED = (
    # Settled outcomes. First, because the accuracy views and anything reading a
    # prediction's `hit` are built on it, and a stale copy under-reports rather
    # than erroring.
    "ml.observation_mv",
    "core.market_1x2_mv",
    "core.market_ou25_mv",
    "public.team",
    "public.team_season_measure",
    "public.team_season_line",
    "public.team_season_timing",
    "public.team_season_first",
)


def build(conn: psycopg.Connection, rebuild: bool = False) -> tuple[int, int]:
    """Populate the feature layer, refreshing every materialized view first."""
    with conn.cursor() as cur:
        cur.execute("set local statement_timeout = '20min'")
        for view in MATERIALIZED:
            cur.execute(f"refresh materialized view {view}")
        if rebuild:
            cur.execute("truncate features.team_match, features.match")
        cur.execute(TEAM_MATCH_SQL)
        team_rows = cur.rowcount
        cur.execute(MATCH_SQL)
        match_rows = cur.rowcount
    return team_rows, match_rows
