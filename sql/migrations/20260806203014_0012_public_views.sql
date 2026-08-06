-- ============================================================
-- 0012 — the public read surface
--
-- Everything the application is ever allowed to see. `core`, `ml`,
-- `features` and `raw` are not exposed to PostgREST, so these views are not
-- merely a convenience layer — they are the access control. Anything not
-- selected here cannot be reached with the publishable key at all.
--
-- Three rules are enforced in SQL rather than trusted to the client:
--
--   1. Only markets with status 'shipping' appear. A market that has not
--      earned publication cannot be rendered by mistake, and the verdicts
--      recorded in Phase 1 stay authoritative instead of being re-litigated
--      in application code.
--   2. Only calibrated probabilities are published. `p_raw` is a diagnostic;
--      shipping it would invite someone to display the number the backtest
--      says is overconfident.
--   3. Nothing about how a model was fitted leaves the database — no
--      coefficients, no training windows, no hyperparameters.
--
-- The views are deliberately left as the default (non-invoker) kind, so they
-- run with the owner's rights and no grants are needed on the private schemas.
-- Supabase's advisor flags that pattern because such a view can bypass
-- row-level security on the tables underneath. There is no row-level security
-- to bypass here and no per-user data: this is football results and our own
-- predictions, identical for every caller. Making the views security-invoker
-- instead would require granting select on core and ml to anon, which would be
-- strictly worse — it would expose those tables the moment anyone added the
-- schema to the exposed list.
-- ============================================================

-- ------------------------------------------------------------
-- Reference
-- ------------------------------------------------------------
create or replace view public.competition as
select c.competition_id,
       c.code,
       c.name,
       c.country,
       c.tier
  from core.competition c
 where c.type = 'league';

comment on view public.competition is 'Leagues the model covers.';

-- ------------------------------------------------------------
-- Fixtures
-- ------------------------------------------------------------
create or replace view public.fixture as
select m.match_id,
       c.code            as competition_code,
       c.name            as competition_name,
       s.label           as season,
       m.matchday,
       m.kickoff_date,
       m.kickoff_utc,
       m.status,
       m.home_team_id,
       h.canonical_name  as home_team,
       coalesce(h.short_name, h.canonical_name) as home_team_short,
       m.away_team_id,
       a.canonical_name  as away_team,
       coalesce(a.short_name, a.canonical_name) as away_team_short,
       m.home_goals_ft,
       m.away_goals_ft,
       m.venue_name,
       -- Lets the fixture list show only what it can actually open, without a
       -- second round trip per row.
       exists (
         select 1
           from ml.prediction p
           join ml.market mk on mk.market_code = p.market_code
          where p.match_id = m.match_id
            and mk.status = 'shipping'
       ) as has_predictions
  from core.match m
  join core.competition c on c.competition_id = m.competition_id
  join core.season s      on s.season_id = m.season_id
  join core.team h        on h.team_id = m.home_team_id
  join core.team a        on a.team_id = m.away_team_id;

comment on view public.fixture is 'One row per match, with names resolved. has_predictions is what the fixture list should filter on.';

-- ------------------------------------------------------------
-- Market registry
-- ------------------------------------------------------------
create or replace view public.market as
select m.market_code,
       m.stat,
       m.scope,
       m.kind,
       case m.market_code
         when 'goals_1x2'     then 'Match result'
         when 'goals_total'   then 'Total goals'
         when 'goals_home'    then 'Home goals'
         when 'goals_away'    then 'Away goals'
         when 'goals_btts'    then 'Both teams to score'
         when 'corners_home'  then 'Home corners'
         when 'corners_away'  then 'Away corners'
         when 'fouls_total'   then 'Total fouls'
         when 'shots_total'   then 'Total shots'
         else initcap(replace(m.market_code, '_', ' '))
       end as label,
       m.notes
  from ml.market m
 where m.status = 'shipping';

comment on view public.market is 'Only markets cleared for publication. Held and rejected markets are not visible here at all.';

-- ------------------------------------------------------------
-- Predictions
--
-- Stored long, one row per selection. Over/under and both-teams-to-score are
-- stored only as the positive side, so the complement is generated here: the
-- client should never be the thing that knows under = 1 - over, because a
-- rounding or filtering mistake there would silently publish a wrong price.
-- ------------------------------------------------------------
create or replace view public.prediction as
with published as (
  select p.match_id,
         p.market_code,
         mk.kind,
         p.line,
         p.selection,
         p.p_calibrated as probability,
         p.predicted_at
    from ml.prediction p
    join ml.market mk on mk.market_code = p.market_code
   where mk.status = 'shipping'
)
select match_id, market_code, line, selection, probability, predicted_at,
       true as is_stored
  from published
union all
select match_id,
       market_code,
       line,
       case kind when 'btts' then 'no' else 'under' end,
       round(1 - probability, 6),
       predicted_at,
       false
  from published
 where kind in ('over_under', 'btts');

comment on view public.prediction is 'Calibrated probabilities for shipping markets. Rows with is_stored false are the arithmetic complement (under, or both-teams-to-score no), derived here so no client has to.';

-- ------------------------------------------------------------
-- What the market thought
--
-- The disagreement between these numbers and ours is the product, so the two
-- must be directly comparable: both de-vigged, both closing.
--
-- Only 1X2 and over/under 2.5 goals exist as prices in this database. There
-- are no bookmaker odds at all for corners, fouls or shots, which is precisely
-- why those markets are worth modelling and why the app must not imply a
-- comparison it cannot make.
-- ------------------------------------------------------------
create or replace view public.market_price as
select f.match_id, 'goals_1x2'::text as market_code, null::numeric as line,
       'home'::text as selection, f.market_p_home as probability
  from features.match f where f.market_p_home is not null
union all
select f.match_id, 'goals_1x2', null, 'draw', f.market_p_draw
  from features.match f where f.market_p_draw is not null
union all
select f.match_id, 'goals_1x2', null, 'away', f.market_p_away
  from features.match f where f.market_p_away is not null
union all
-- Over/under is de-vigged here rather than in the feature layer because it is
-- needed only for display. Pinnacle preferred as the sharpest book, falling
-- back to the market average where Pinnacle is missing.
select o.match_id, 'goals_total', o.line,
       case when o.outcome = 'Over' then 'over' else 'under' end,
       round((1 / o.price) / sum(1 / o.price) over (partition by o.match_id, o.line), 6)
  from (
    select distinct on (match_id, line, outcome)
           match_id, line, outcome, price
      from core.odds
     where market = 'OU' and snapshot = 'closing' and price > 1
       and bookmaker in ('Pinnacle', '_average')
     order by match_id, line, outcome,
              case bookmaker when 'Pinnacle' then 0 else 1 end
  ) o;

comment on view public.market_price is 'De-vigged closing probabilities, comparable with public.prediction. Covers 1X2 and total goals only — no book in this database prices corners, fouls or shots.';

-- ------------------------------------------------------------
-- Context for the match page
-- ------------------------------------------------------------
create or replace view public.team_form as
select t.match_id,
       t.team_id,
       tm.canonical_name as team,
       t.is_home,
       t.matches_before,
       t.ppg_5, t.ppg_10,
       t.gf_5, t.ga_5, t.gf_10, t.ga_10,
       t.xgf_10, t.xga_10,
       t.corners_f_10, t.corners_a_10,
       t.shots_f_10, t.shots_a_10,
       t.fouls_10, t.yellows_10,
       t.rest_days,
       t.season_matches, t.season_ppg
  from features.team_match t
  join core.team tm on tm.team_id = t.team_id;

comment on view public.team_form is 'Pre-match form, point-in-time correct: every value was knowable before kickoff.';

create or replace view public.head_to_head as
select f.match_id,
       f.h2h_matches,
       f.h2h_home_wins,
       f.h2h_draws,
       f.h2h_away_wins,
       f.h2h_avg_goals,
       f.h2h_avg_corners,
       f.rating_diff,
       f.difficulty_home,
       f.difficulty_away
  from features.match f;

comment on view public.head_to_head is 'Prior meetings in the same competition, counted before this match.';

-- ------------------------------------------------------------
-- Track record
--
-- Published so the application can show how the model has actually done rather
-- than only what it currently claims. A calibration table that anyone can read
-- is the cheapest defence against quietly drifting.
-- ------------------------------------------------------------
create or replace view public.market_accuracy as
select p.market_code,
       p.line,
       p.selection,
       count(*)                                as settled,
       round(avg(p.p_calibrated), 4)           as avg_predicted,
       round(avg(p.hit::int::numeric), 4)      as actual_rate,
       round(avg(p.hit::int::numeric) - avg(p.p_calibrated), 4) as bias
  from ml.prediction_scored p
  join ml.market mk on mk.market_code = p.market_code
 where mk.status = 'shipping'
   and p.hit is not null
 group by 1, 2, 3;

comment on view public.market_accuracy is 'Predicted versus realised frequency on settled fixtures. Positive bias means the model was too low.';

-- ------------------------------------------------------------
-- Grants. Read only, and only on these views.
-- ------------------------------------------------------------
grant usage on schema public to anon, authenticated;

grant select on
  public.competition,
  public.fixture,
  public.market,
  public.prediction,
  public.market_price,
  public.team_form,
  public.head_to_head,
  public.market_accuracy
to anon, authenticated;
