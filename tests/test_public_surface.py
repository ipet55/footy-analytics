"""Tests for the public read surface.

These views are not a convenience layer, they are the access control: `core`,
`ml`, `features` and `raw` are unreachable through the API, so whatever these
views select is exactly what the world can see. That makes two classes of
mistake expensive and invisible.

The first is publishing a market that has not earned it. The Phase 1 verdicts
live in `ml.market.status`, and a view that forgot to filter on it would quietly
put cards — which are held precisely because their percentages are not accurate
enough — in front of a user as though they were trustworthy.

The second is leaking the machinery. Model coefficients, training windows and
raw uncalibrated probabilities have no business leaving the database, and the
uncalibrated numbers are the ones the backtest specifically found overconfident.

Supabase's advisor reports these views as SECURITY DEFINER errors. That lint
exists for multi-tenant applications, where such a view can return another
user's rows. There is no per-user data here and no row-level security to bypass;
the alternative, security-invoker views, would require granting select on `core`
and `ml` to `anon` and would be strictly worse. Rather than argue that in a
comment, `test_anon_can_read_nothing_but_the_views` measures it.
"""

from __future__ import annotations

VIEWS = (
    "competition", "fixture", "market", "prediction", "market_price",
    "team_form", "head_to_head", "market_accuracy", "match_outcome",
    # Descriptive rather than predictive: counts of what happened in matches a
    # team played. Safe to publish for the opposite reason to the others — they
    # contain no model output at all, only results that are already public.
    # Materialized, so they appear as relkind 'm' rather than 'v'.
    "team", "team_season_measure", "team_season_line",
    # What happened in a played match, and when. Results, already public
    # everywhere, with no model output in them.
    "match_stat", "match_event", "team_season_timing", "team_season_first",
)


def test_anon_can_read_nothing_but_the_views(conn, scalar):
    """The claim the security advisory turns on, stated as a number.

    If this ever fails, the API is exposing internals regardless of what any
    comment says about the lint being a false positive.
    """
    readable = scalar(
        """
        select count(*)
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname in ('core', 'ml', 'features', 'raw')
           and c.relkind in ('r', 'v', 'm')
           and has_table_privilege('anon', c.oid, 'select')
        """
    )
    assert readable == 0, f"anon can read {readable} objects in the private schemas"


def test_the_public_surface_is_exactly_the_intended_views(conn, scalar):
    """A new view in public is published to the world the moment it is created,
    so appearing here should be a deliberate act rather than a side effect."""
    unexpected = scalar(
        """
        select count(*)
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relkind in ('r', 'v', 'm')
           and c.relname <> all(%s)
        """,
        (list(VIEWS),),
    )
    assert unexpected == 0


def test_only_shipping_markets_are_published(conn, scalar):
    """Published in *this* competition, which is the rule that actually binds.

    A market can be validated in England and unpublishable in Portugal, so the
    global status is no longer sufficient: checking it would pass while Portugal
    served numbers whose calibration was rejected.
    """
    not_shipping_here = scalar(
        """
        select count(*)
          from public.prediction p
          join core.match m on m.match_id = p.match_id
          left join ml.market_competition mc
                 on mc.market_code = p.market_code
                and mc.competition_id = m.competition_id
         where mc.status is distinct from 'shipping'
        """
    )
    assert not_shipping_here == 0


def test_no_competition_publishes_a_market_it_has_not_earned(conn, scalar):
    """Absence must mean no.

    The dangerous failure is a competition with no row at all quietly inheriting
    the global verdict, which is how eight leagues would appear on the site
    having never been measured.
    """
    unearned = scalar(
        """
        select count(*) from (
          select market_code, competition_code from public.market
          except
          select mc.market_code, c.code
            from ml.market_competition mc
            join core.competition c using (competition_id)
           where mc.status = 'shipping'
        ) x
        """
    )
    assert unearned == 0


def test_the_original_five_still_serve_what_they_did(conn, scalar):
    """The per-competition split had to be a no-op where the evidence came from.

    Those five are where every global verdict was measured, so if the migration
    changed what they publish, it changed a decision rather than relocating it.
    """
    changed = scalar(
        """
        select count(*) from (
          select m.market_code
            from ml.market m
           where m.status = 'shipping'
          except
          select mc.market_code
            from ml.market_competition mc
            join core.competition c using (competition_id)
           where c.code = 'ENG-PL' and mc.status = 'shipping'
        ) x
        """
    )
    assert changed == 0


def test_no_raw_probability_is_exposed(conn, scalar):
    """Only the calibrated number ships. The raw one is the model's own
    overconfident estimate and exists for diagnosis."""
    # Matched as whole words rather than as a substring, because 'h2h_draws'
    # contains 'raw' and a greedy pattern fails on legitimate columns.
    leaked = scalar(
        """
        select count(*)
          from information_schema.columns
         where table_schema = 'public'
           and (column_name = 'p_raw'
                or column_name like 'raw\\_%%'
                or column_name like '%%\\_raw')
        """
    )
    assert leaked == 0


def test_no_model_internals_are_exposed(conn, scalar):
    """Coefficients, hyperparameters and training windows stay private."""
    leaked = scalar(
        """
        select count(*)
          from information_schema.columns
         where table_schema = 'public'
           and column_name in ('coefficients', 'params', 'hyperparameters',
                               'trained_from', 'trained_to', 'model_id',
                               'intercept', 'slope')
        """
    )
    assert leaked == 0


def test_published_outcome_probabilities_sum_to_one(conn, scalar):
    """Across every published market, the selections offered for a fixture must
    form a distribution. The complements are generated in SQL, so an error here
    would reach the screen as a wrong price."""
    bad = scalar(
        """
        with grouped as (
          select match_id, market_code, line, sum(probability) as total
            from public.prediction
           where selection in ('home', 'draw', 'away')
              or selection in ('over', 'under')
              or selection in ('yes', 'no')
           group by 1, 2, 3
        )
        select count(*) from grouped where abs(total - 1) > 0.00001
        """
    )
    assert bad == 0


def test_every_probability_is_a_probability(conn, scalar):
    bad = scalar(
        "select count(*) from public.prediction "
        "where probability <= 0 or probability >= 1"
    )
    assert bad == 0


def test_market_prices_are_comparable_with_ours(conn, scalar):
    """De-vigged, so they sum to one and sit on the same scale as the model's."""
    bad = scalar(
        """
        with grouped as (
          select match_id, market_code, line, sum(probability) as total
            from public.market_price
           group by 1, 2, 3
        )
        select count(*) from grouped where abs(total - 1) > 0.0001
        """
    )
    assert bad == 0


def test_fixtures_flagged_as_predictable_really_have_predictions(conn, scalar):
    """`has_predictions` drives the fixture list, so a wrong value is either a
    dead link or a hidden fixture."""
    wrong = scalar(
        """
        select count(*)
          from public.fixture f
         where f.has_predictions
           and not exists (
                 select 1 from public.prediction p where p.match_id = f.match_id
               )
        """
    )
    assert wrong == 0
