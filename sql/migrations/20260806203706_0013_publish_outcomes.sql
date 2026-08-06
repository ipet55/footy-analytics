-- ============================================================
-- 0013 — publish what actually happened alongside what was predicted
--
-- 0012 published probabilities but not outcomes, which would have let the
-- application show confident percentages with no way to check them. For a
-- product whose entire claim is that its numbers are honest, the result has to
-- travel with the prediction.
--
-- `hit` is inverted on the generated complement rows: if 'over 2.5' hit then
-- 'under 2.5' did not. Deriving that here keeps the client from having to know
-- which selections are complements of which.
-- ============================================================

create or replace view public.prediction as
with published as (
  select p.match_id,
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
   where mk.status = 'shipping'
)
select match_id, market_code, line, selection, probability, predicted_at,
       true as is_stored, observed, hit
  from published
union all
select match_id,
       market_code,
       line,
       case kind when 'btts' then 'no' else 'under' end,
       round(1 - probability, 6),
       predicted_at,
       false,
       observed,
       not hit
  from published
 where kind in ('over_under', 'btts');

comment on view public.prediction is 'Calibrated probabilities for shipping markets, with the settled result where the match has been played. Rows with is_stored false are the arithmetic complement (under, or both-teams-to-score no), derived here so no client has to.';

-- The realised numbers behind every market, so a page can say "we gave 62% to
-- over 4.5 home corners, and there were 7" rather than only "hit".
create or replace view public.match_outcome as
select o.match_id, o.stat, o.scope, o.value
  from ml.observation o;

comment on view public.match_outcome is 'Actual counts per statistic once a match is played.';

grant select on public.match_outcome to anon, authenticated;
