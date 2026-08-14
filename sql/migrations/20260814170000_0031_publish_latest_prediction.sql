-- ============================================================
-- Publish the most recent prediction for a market, not all of them.
--
-- ml.model keeps every version deliberately — the roadmap's rule is
-- no silent retraining, so a refit writes a new row rather than
-- overwriting the old one, and ml.prediction keeps what each version
-- said. That is right for the record.
--
-- public.prediction then showed all of them. Changing the model and
-- re-running the predictions duplicated every published row: 6,693
-- of them, so a match page listed 'over 2.5' twice with two
-- different percentages and no way for a reader to tell which was
-- current. Adding the shrinkage penalty is what surfaced it, but any
-- refit would have done the same, and the display would have looked
-- broken rather than stale.
--
-- distinct on the market key, newest first. The complement rows are
-- derived after the deduplication rather than before, so an 'under'
-- can never be the arithmetic complement of a different version's
-- 'over'.
-- ============================================================

create or replace view public.prediction as
with published as (
    select distinct on (p.match_id, p.market_code, p.line, p.selection)
           p.match_id, p.market_code, mk.kind, p.line, p.selection,
           p.p_calibrated as probability, p.predicted_at, p.observed, p.hit
      from ml.prediction_scored p
      join ml.market mk on mk.market_code = p.market_code
      join core.match m on m.match_id = p.match_id
      join ml.market_competition mc on mc.market_code = p.market_code
                                   and mc.competition_id = m.competition_id
     where mc.status = 'shipping'
     order by p.match_id, p.market_code, p.line, p.selection, p.predicted_at desc
)
select match_id, market_code, line, selection, probability, predicted_at,
       true as is_stored, observed, hit
  from published
union all
select match_id, market_code, line,
       case kind when 'btts' then 'no' else 'under' end,
       round(1 - probability, 6), predicted_at, false, observed, not hit
  from published
 where kind in ('over_under', 'btts');

comment on view public.prediction is 'The most recent calibrated probability for each market shipping in the competition the match belongs to, with the settled result where the match has been played. ml.prediction keeps every model version; this shows the current one. Rows with is_stored false are the arithmetic complement, derived after deduplication so a complement always matches its own version.';
