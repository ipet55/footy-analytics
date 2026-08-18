-- ============================================================
-- Stop recomputing every settled outcome on every page view.
--
-- 0049 fixed half the problem — the CTE fence. This is the other half.
-- ml.prediction_scored left-joins ml.observation to say whether a
-- prediction came true, and one arm of that view aggregates
-- core.team_match with GROUP BY ... HAVING. An aggregate blocks
-- predicate pushdown, so `where match_id = any(...)` could not reach
-- inside: every request rebuilt all 651,653 observations to decorate a
-- few hundred rows. 2.9 seconds, against 0.08 for the predictions
-- themselves.
--
-- Materialised, that same query is 0.1 seconds, and a full refresh
-- costs 9.
--
-- This trades a property the project had relied on and said so out
-- loud: ml.observation was a view over core, so a result became a
-- settled outcome the instant it landed, and `footy refresh` needed no
-- settlement step at all. That is no longer free — settlement now
-- happens when the view is refreshed.
--
-- Two things make that safe rather than merely convenient. The refresh
-- is part of the feature build, which already runs after results and
-- before predictions, so the ordering that mattered still holds. And
-- `footy freshness` now asserts the copy is not behind the results,
-- because the failure mode of a stale materialised view is silent: the
-- accuracy page would simply show fewer settled predictions than exist
-- and look entirely plausible doing it.
--
-- ml.observation stays as the definition. The materialised copy selects
-- from it, so there is one description of what an observation is.
-- ============================================================

create materialized view ml.observation_mv as
select match_id, stat, scope, value from ml.observation;

create unique index observation_mv_key on ml.observation_mv (match_id, stat, scope);

comment on materialized view ml.observation_mv is 'Settled outcomes, materialised. ml.observation remains the definition; this is the copy that gets read, because the aggregate inside it blocks predicate pushdown and made every match page rebuild all 651,653 rows. Refreshed by footy build-features, and asserted current by footy freshness.';

create or replace view ml.prediction_scored as
select p.prediction_id,
       p.match_id,
       p.model_id,
       p.market_code,
       p.line,
       p.selection,
       p.p_raw,
       p.p_calibrated,
       p.predicted_at,
       mk.stat,
       mk.scope,
       mk.status,
       m.competition_id,
       m.season_id,
       m.kickoff_date,
       o.value as observed,
       case
         when o.value is null then null::boolean
         when mk.kind = 'over_under' then o.value > p.line
         when mk.kind = 'btts' then m.home_goals_ft > 0 and m.away_goals_ft > 0
         when mk.kind = 'outcome' then p.selection = case
              when m.home_goals_ft > m.away_goals_ft then 'home'
              when m.home_goals_ft = m.away_goals_ft then 'draw'
              else 'away'
         end
         else null::boolean
       end as hit
  from ml.prediction p
  join ml.market mk on mk.market_code = p.market_code
  join core.match m on m.match_id = p.match_id
  left join ml.observation_mv o on o.match_id = p.match_id
                               and o.stat = mk.stat
                               and o.scope = mk.scope;
