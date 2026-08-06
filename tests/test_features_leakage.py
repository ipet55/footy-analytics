"""Leakage tests for the feature layer.

The README states the rule these enforce: every row in `features` may only
contain information that existed before its match kicked off. Break it and the
backtest improves, which is the trap — there is no error message and no failing
query, just a model that looks excellent and loses money.

These run against the live database and are skipped without DATABASE_URL. They
were run by hand once; the point of writing them down is that a future change to
a window frame, a join, or an as-of lookup cannot pass unnoticed.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.database

SAMPLE = 400


def test_rolling_average_uses_only_earlier_matches(scalar):
    """Recompute gf_5 from scratch by explicitly taking the five previous
    matches, and require the stored value to agree.

    This is the test that catches `rows between 5 preceding and current row`,
    which is the single most likely way for this pipeline to start leaking.
    """
    violations = scalar(
        f"""
        with sampled as (
            select match_id, team_id, kickoff_date, gf_5
              from features.team_match
             order by md5(match_id::text || team_id::text)
             limit {SAMPLE}
        ),
        expected as (
            select s.match_id, s.team_id, s.gf_5,
                   (select avg(p.goals_for)
                      from (select tm.goals_for
                              from core.team_match tm
                             where tm.team_id = s.team_id
                               and tm.period = 'FT'
                               and (tm.kickoff_date, tm.match_id)
                                   < (s.kickoff_date, s.match_id)
                             order by tm.kickoff_date desc, tm.match_id desc
                             limit 5) p) as recomputed
              from sampled s
        )
        -- The stored column is numeric with three decimals, so an exact match
        -- is impossible: 2/3 is persisted as 0.667. Anything beyond half of the
        -- last stored digit is a real disagreement rather than rounding.
        select count(*) from expected
         where ((gf_5 is null) <> (recomputed is null))
            or (gf_5 is not null and abs(gf_5 - recomputed) > 0.0005)
        """
    )
    assert violations == 0


def test_a_teams_first_match_has_no_history(scalar):
    """matches_before = 0 must mean every backward-looking column is null.
    A zero there instead of a null would be a silent claim that a debutant team
    averages no goals, which the model would believe."""
    violations = scalar(
        """
        select count(*) from features.team_match
         where matches_before = 0
           and (gf_5 is not null or ga_5 is not null or ppg_5 is not null
                or corners_f_5 is not null or rest_days is not null)
        """
    )
    assert violations == 0


def test_head_to_head_counts_only_previous_meetings(scalar):
    violations = scalar(
        f"""
        with sampled as (
            select f.match_id, f.h2h_matches, m.home_team_id, m.away_team_id,
                   m.competition_id, m.kickoff_date
              from features.match f
              join core.match m on m.match_id = f.match_id
             order by md5(f.match_id::text)
             limit {SAMPLE}
        )
        select count(*) from sampled s
         where s.h2h_matches <> (
                 select count(*) from core.match q
                  where q.competition_id = s.competition_id
                    and q.kickoff_date < s.kickoff_date
                    and q.home_goals_ft is not null
                    and ((q.home_team_id = s.home_team_id
                          and q.away_team_id = s.away_team_id)
                      or (q.home_team_id = s.away_team_id
                          and q.away_team_id = s.home_team_id))
               )
        """
    )
    assert violations == 0


def test_ratings_are_as_of_the_match_not_after_it(scalar):
    """Elo is stored as validity ranges. The join must land on the range
    covering kickoff; landing on a later one would import the consequences of
    the match into its own features."""
    violations = scalar(
        """
        select count(*) from features.team_match f
          join core.team_rating tr
            on tr.team_id = f.team_id
           and tr.source_id = (select source_id from core.source where code = 'elo_xg')
           and tr.rating = f.elo_xg
         where f.elo_xg is not null
           and f.kickoff_date not between tr.valid_from and tr.valid_to
           and not exists (
                 select 1 from core.team_rating ok
                  where ok.team_id = f.team_id
                    and ok.source_id = tr.source_id
                    and ok.rating = f.elo_xg
                    and f.kickoff_date between ok.valid_from and ok.valid_to
               )
        """
    )
    assert violations == 0


def test_rest_days_are_positive_and_bounded(scalar):
    violations = scalar(
        """
        select count(*) from features.team_match
         where rest_days is not null and (rest_days <= 0 or rest_days > 365)
        """
    )
    assert violations == 0


def test_market_probabilities_are_a_distribution(scalar):
    """De-vigged closing odds are the benchmark the model is judged against, so
    they have to be an honest probability distribution."""
    violations = scalar(
        """
        select count(*) from features.match
         where market_p_home is not null
           and (abs(market_p_home + market_p_draw + market_p_away - 1) > 1e-4
                or least(market_p_home, market_p_draw, market_p_away) <= 0)
        """
    )
    assert violations == 0


def test_every_played_match_has_two_feature_rows(scalar):
    """Coverage, not leakage: a missing side means a fixture silently drops out
    of training rather than failing loudly."""
    violations = scalar(
        """
        select count(*) from core.match m
         where m.home_goals_ft is not null
           and (select count(*) from features.team_match f
                 where f.match_id = m.match_id) <> 2
        """
    )
    assert violations == 0
