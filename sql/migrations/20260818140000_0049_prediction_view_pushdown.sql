-- ============================================================
-- Stop every match page rebuilding every prediction ever made.
--
-- Symptom: a fixture with 69 stored probabilities rendered "No
-- published markets for this fixture". Not always — the first request
-- failed and the second succeeded, which is the signature of a query
-- sitting on the edge of the statement timeout.
--
-- Cause: the `published` CTE is referenced twice, once in each arm of
-- the UNION ALL that derives the under side of each over. Postgres
-- materialises a CTE referenced more than once, and a materialised CTE
-- is an optimisation fence: `where match_id = 22031` on the outside
-- cannot be pushed inside it. So every request computed DISTINCT ON
-- across all 46,230 predictions, joined through ml.prediction_scored,
-- whose settlement logic scanned 651,653 rows of match_team_stat — all
-- to return 69.
--
-- NOT MATERIALIZED lets the filter through. One match goes from 3.2
-- seconds to 0.1, which is the difference between a page that works and
-- a page that works most of the time.
--
-- The cost is that the CTE is now inlined twice, so an unfiltered scan
-- of the whole view roughly doubles. Nothing does that: every caller
-- filters by match, because a prediction is only ever read in the
-- context of a fixture. If something ever needs the lot, it should
-- select from ml.prediction directly rather than un-fixing this.
--
-- Worth noting how it presented. Not as an error — as a page calmly
-- stating there was nothing to show, which is exactly what a fixture
-- with no markets is supposed to look like. Two of the last three bugs
-- here have been a confident wrong answer rather than a failure.
-- ============================================================

create or replace view public.prediction as
with published as not materialized (
    select distinct on (p.match_id, p.market_code, p.line, p.selection)
           p.match_id,
           p.market_code,
           mk.kind,
           p.line,
           p.selection,
           p.p_calibrated as probability,
           p.predicted_at,
           p.observed,
           p.hit
      from ml.prediction_scored p
      join ml.market mk on mk.market_code = p.market_code
      join core.match m on m.match_id = p.match_id
      join ml.market_competition mc on mc.market_code = p.market_code
                                   and mc.competition_id = m.competition_id
     where mc.status = 'shipping'
     order by p.match_id, p.market_code, p.line, p.selection, p.predicted_at desc
)
select match_id,
       market_code,
       line,
       selection,
       probability,
       predicted_at,
       true as is_stored,
       observed,
       hit
  from published
union all
select match_id,
       market_code,
       line,
       case kind when 'btts' then 'no' else 'under' end as selection,
       round(1 - probability, 6) as probability,
       predicted_at,
       false as is_stored,
       observed,
       not hit as hit
  from published
 where kind = any (array['over_under', 'btts']);

grant select on public.prediction to anon, authenticated;
