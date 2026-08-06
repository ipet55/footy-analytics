"""Invariants of the stored predictions.

These check the table an application would actually read. The modelling tests
elsewhere check that the mathematics is right; these check that what reached the
database is coherent, out of sample, and settled against the correct results —
the properties a user would notice being wrong.

They run against the live database and are skipped without DATABASE_URL. They
pass trivially on an empty ml.prediction, which is intended: they are here to
catch a regression in `footy predict`, not to assert that it has been run.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.database


def test_no_prediction_is_in_sample(scalar):
    """The one that matters. A model must not predict a match it learned from.

    A trigger refuses these on write, so a failure here means the trigger has
    been dropped or bypassed, not merely that a bad row slipped through.
    """
    assert scalar(
        """
        select count(*)
          from ml.prediction p
          join ml.model md on md.model_id = p.model_id
          join core.match m on m.match_id = p.match_id
         where m.kickoff_date < md.trained_to
        """
    ) == 0


def test_the_database_refuses_an_in_sample_prediction(conn):
    """Prove the guard is live, rather than inferring it from an empty result.

    The previous test passes just as happily if the trigger has been dropped and
    nothing has tried to leak since, so this one actually attempts the write.
    Rolled back either way, so it leaves nothing behind.
    """
    import psycopg

    from footy import db

    target = db.fetch_one(
        conn,
        """
        select md.model_id, m.match_id
          from ml.model md
          join core.match m on m.competition_id = md.competition_id
         where m.kickoff_date < md.trained_to
         limit 1
        """,
    )
    if target is None:
        pytest.skip("no fitted model with an earlier match to test against")
    model_id, match_id = target

    # The guard raises with errcode check_violation, so it arrives as the same
    # class of error as a failed constraint rather than a generic exception.
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        conn.transaction(force_rollback=True),
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            insert into ml.prediction (match_id, model_id, market_code,
                                       line, selection, p_raw, p_calibrated)
            values (%s, %s, 'goals_1x2', null, 'home', 0.5, 0.5)
            """,
            (match_id, model_id),
        )


def test_rejected_markets_are_never_predicted(scalar):
    """A market measured and found useless should not be quietly published
    because some caller passed the wrong flag."""
    assert scalar(
        """
        select count(*)
          from ml.prediction p
          join ml.market mk on mk.market_code = p.market_code
         where mk.status = 'rejected'
        """
    ) == 0


def test_three_way_probabilities_sum_to_one(scalar):
    """1X2 comes off a single score matrix, so the three outcomes must partition
    the probability. Anything else means the matrix was mis-summed.

    The tolerance is set by storage: probabilities are numeric(7,6), so three
    of them can each round by up to 5e-7.
    """
    assert scalar(
        """
        with sums as (
          select match_id, model_id, sum(p_raw) as raw, sum(p_calibrated) as cal,
                 count(*) as selections
            from ml.prediction
           where market_code = 'goals_1x2'
           group by match_id, model_id
        )
        select count(*) from sums
         where selections <> 3
            or abs(raw - 1) > 0.000002
            or abs(cal - 1) > 0.000002
        """
    ) == 0


def test_over_probabilities_fall_as_the_line_rises(scalar):
    """P(over 5.5) can never exceed P(over 4.5).

    Worth testing rather than assuming, because each line is recalibrated by its
    own two parameters and nothing in that transformation is aware of the lines
    either side of it. Fitted slopes have been close enough for the ordering to
    survive, but it is not guaranteed by construction, so if a future
    recalibration inverts a pair this should be what says so.
    """
    assert scalar(
        """
        with ordered as (
          select p_raw, p_calibrated,
                 lead(p_raw) over w as next_raw,
                 lead(p_calibrated) over w as next_calibrated
            from ml.prediction
           where selection = 'over'
          window w as (partition by match_id, model_id, market_code order by line)
        )
        select count(*) from ordered
         where next_raw > p_raw or next_calibrated > p_calibrated
        """
    ) == 0


def test_settlement_matches_the_recorded_score(scalar):
    """Resolve the goals markets straight from core.match and require the view to
    agree. The settlement view is the one place these rules are written down, so
    a mistake in it would silently mis-score every market at once."""
    assert scalar(
        """
        select count(*)
          from ml.prediction_scored p
          join core.match m on m.match_id = p.match_id
         where m.home_goals_ft is not null
           and p.hit is distinct from case p.market_code
                 when 'goals_1x2' then p.selection = case
                        when m.home_goals_ft > m.away_goals_ft then 'home'
                        when m.home_goals_ft = m.away_goals_ft then 'draw'
                        else 'away' end
                 when 'goals_btts' then m.home_goals_ft > 0 and m.away_goals_ft > 0
                 when 'goals_total' then (m.home_goals_ft + m.away_goals_ft) > p.line
                 when 'goals_home' then m.home_goals_ft > p.line
                 when 'goals_away' then m.away_goals_ft > p.line
               end
           and p.market_code like 'goals%'
        """
    ) == 0


def test_every_prediction_records_the_calibration_applied(scalar):
    """A published probability has to be reproducible, which means the
    correction that produced it must be on file. Where none was applied the
    identity is recorded explicitly, so an absent row is a real defect rather
    than an ambiguity."""
    assert scalar(
        """
        select count(*)
          from ml.prediction p
         where not exists (
                 select 1 from ml.calibration c
                  where c.model_id = p.model_id
                    and c.market_code = p.market_code
                    and c.line is not distinct from p.line
               )
        """
    ) == 0


def test_calibration_reproduces_the_published_probability(scalar):
    """sigmoid(a + b * logit(raw)) must actually equal the stored p_calibrated.

    This is what makes the stored numbers auditable: given the raw probability
    and the calibration row, anyone can recompute what was shown.

    The comparison cannot be exact, because every input is stored rounded to its
    column precision — probabilities to six decimals, intercept and slope to
    five — so the allowance is those roundings carried through the
    transformation rather than a tolerance picked to make the test pass. Each
    term below is one stored quantity's half-unit of rounding multiplied by the
    derivative of the published probability with respect to it, and the shared
    p(1-p) is that derivative for the log-odds.
    """
    assert scalar(
        """
        with recomputed as (
          select p.p_raw, p.p_calibrated, c.slope,
                 ln(p.p_raw / (1 - p.p_raw)) as log_odds,
                 1.0 / (1.0 + exp(-(c.intercept
                     + c.slope * ln(p.p_raw / (1 - p.p_raw))))) as expected
            from ml.prediction p
            join ml.calibration c
              on c.model_id = p.model_id
             and c.market_code = p.market_code
             and c.line is not distinct from p.line
        )
        select count(*) from recomputed
         where abs(p_calibrated - expected) >
               0.0000005                                  -- p_calibrated itself
               + expected * (1 - expected) * (
                   0.000005                               -- intercept
                   + 0.000005 * abs(log_odds)             -- slope
                   + slope * 0.0000005 / (p_raw * (1 - p_raw))  -- p_raw
                 )
        """
    ) == 0
