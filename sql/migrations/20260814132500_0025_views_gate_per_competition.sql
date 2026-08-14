-- ============================================================
-- Make the published views enforce the per-competition decision.
--
-- 0024 recorded which markets may be published where. Until the
-- views read it, that record has no effect: they still filter on
-- ml.market.status, which is one verdict for all fourteen
-- competitions.
--
-- The views are the access control here — anon can read these and
-- nothing else — so this is the change that actually stops a market
-- appearing where it has not earned it, and lets the ones that have
-- appear at last.
--
-- public.market keeps its old shape and gains a competition_code
-- column. It was a flat list of markets; a market is now publishable
-- in some competitions and not others, so a flat list can no longer
-- describe it. The app reads labels from here, so the column is
-- added rather than the table reshaped, and callers that ignore it
-- see every market published anywhere.
-- ============================================================

create or replace view public.prediction as
with published as (
    select p.match_id, p.market_code, mk.kind, p.line, p.selection,
           p.p_calibrated as probability, p.predicted_at, p.observed, p.hit
      from ml.prediction_scored p
      join ml.market mk on mk.market_code = p.market_code
      join core.match m on m.match_id = p.match_id
      join ml.market_competition mc on mc.market_code = p.market_code
                                   and mc.competition_id = m.competition_id
     where mc.status = 'shipping'
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

comment on view public.prediction is 'Calibrated probabilities for markets shipping in the competition the match belongs to, with the settled result where the match has been played. Rows with is_stored false are the arithmetic complement, derived here so no client has to.';

create or replace view public.fixture as
select m.match_id,
       c.code as competition_code,
       c.name as competition_name,
       s.label as season,
       m.matchday,
       m.kickoff_date,
       m.kickoff_utc,
       m.status,
       m.home_team_id,
       h.canonical_name as home_team,
       coalesce(h.short_name, h.canonical_name) as home_team_short,
       m.away_team_id,
       a.canonical_name as away_team,
       coalesce(a.short_name, a.canonical_name) as away_team_short,
       m.home_goals_ft,
       m.away_goals_ft,
       m.venue_name,
       exists (
         select 1 from ml.prediction p
           join ml.market_competition mc on mc.market_code = p.market_code
                                        and mc.competition_id = m.competition_id
          where p.match_id = m.match_id and mc.status = 'shipping'
       ) as has_predictions
  from core.match m
  join core.competition c on c.competition_id = m.competition_id
  join core.season s      on s.season_id = m.season_id
  join core.team h        on h.team_id = m.home_team_id
  join core.team a        on a.team_id = m.away_team_id;

drop view if exists public.market;

create view public.market as
select mc.market_code,
       c.code as competition_code,
       m.stat,
       m.scope,
       m.kind,
       case
         when m.kind = 'outcome' then 'Match result'
         when m.kind = 'btts'    then 'Both teams to score'
         when m.scope = 'match'  then 'Total ' || m.stat
         when m.scope = 'home'   then 'Home ' || m.stat
         when m.scope = 'away'   then 'Away ' || m.stat
         else initcap(replace(mc.market_code, '_', ' '))
       end as label,
       coalesce(mc.notes, m.notes) as notes
  from ml.market_competition mc
  join ml.market m on m.market_code = mc.market_code
  join core.competition c on c.competition_id = mc.competition_id
 where mc.status = 'shipping';

comment on view public.market is 'Which markets may be published, in which competition, with a display label composed from stat and scope. A market absent for a competition is not served there.';

grant select on public.market to anon, authenticated;
