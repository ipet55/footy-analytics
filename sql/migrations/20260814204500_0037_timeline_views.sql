-- ============================================================
-- Publish the timeline, and the timing summaries built on it.
--
-- Three things, all impossible before core.match_event existed.
--
-- match_event: the timeline of one match, for the page.
--
-- team_season_timing: how a team's goals distribute across the match
-- in fifteen-minute bands, scored and conceded, per season and venue.
-- This is the chart every football site has and this one could not
-- draw.
--
-- team_season_first: when a team tends to score first and concede
-- first, and how often it does neither. Averages hide this: a side
-- that scores early in half its games and never otherwise has the
-- same mean minute as one that always scores on the hour.
--
-- Bands are 1-15, 16-30, 31-45, 46-60, 61-75, 76-90, with added time
-- folded into the band its minute belongs to. Stoppage-time goals are
-- 90+, so without folding they would form a phantom seventh band that
-- is really the tail of the sixth.
-- ============================================================

create or replace view public.match_event as
select e.match_id,
       e.team_id,
       t.canonical_name as team,
       t.team_id = m.home_team_id as is_home,
       e.minute,
       e.extra_minute,
       e.kind,
       e.detail,
       e.player_name,
       e.assist_name
  from core.match_event e
  join core.match m using (match_id)
  join core.team t on t.team_id = e.team_id;

comment on view public.match_event is 'The timeline of a match: goals, cards and substitutions with the minute each happened.';

create materialized view public.team_season_timing as
with goals as (
    select e.match_id, e.team_id, e.minute,
           m.home_team_id, m.away_team_id, m.competition_id, m.season_id
      from core.match_event e
      join core.match m using (match_id)
     where e.kind = 'goal'
       -- Own goals count for the side that benefits, which is how a reader reads
       -- a scoreline. The feed attributes them to the scorer's team.
       and coalesce(e.detail, '') <> 'Own Goal'
),
sided as (
    -- One row per goal per team involved: for the scorer it is 'for', for the
    -- opponent 'against'. That way one pass produces both halves of the chart.
    select g.match_id, s.team_id, s.side, g.minute,
           g.team_id = g.home_team_id as scorer_at_home,
           s.team_id = g.home_team_id as is_home,
           g.competition_id, g.season_id
      from goals g
     cross join lateral (values
            (g.team_id, 'for'),
            (case when g.team_id = g.home_team_id then g.away_team_id
                  else g.home_team_id end, 'against')
        ) as s(team_id, side)
)
select s.team_id,
       t.canonical_name as team,
       c.code  as competition_code,
       se.label as season,
       se.start_year,
       s.side,
       case when grouping(s.is_home) = 1 then 'overall'
            when s.is_home then 'home' else 'away' end as venue,
       least((greatest(s.minute, 1) - 1) / 15, 5) as band,
       count(*) as goals
  from sided s
  join core.team t on t.team_id = s.team_id
  join core.competition c on c.competition_id = s.competition_id
  join core.season se on se.season_id = s.season_id
 group by grouping sets (
    (s.team_id, t.canonical_name, c.code, se.label, se.start_year, s.side,
     least((greatest(s.minute, 1) - 1) / 15, 5), s.is_home),
    (s.team_id, t.canonical_name, c.code, se.label, se.start_year, s.side,
     least((greatest(s.minute, 1) - 1) / 15, 5))
 );

comment on materialized view public.team_season_timing is 'Goals scored and conceded by fifteen-minute band, per season and venue. Band 0 is minutes 1-15 and band 5 is 76 onward, with added time folded into the band its minute belongs to. Refreshed by footy build-features.';

create materialized view public.team_season_first as
with played as (
    select m.match_id, m.competition_id, m.season_id, t.team_id,
           t.team_id = m.home_team_id as is_home
      from core.match m
      join core.team t on t.team_id in (m.home_team_id, m.away_team_id)
     where m.home_goals_ft is not null
       and exists (select 1 from core.match_event e where e.match_id = m.match_id)
),
firsts as (
    select p.*,
           (select min(e.minute) from core.match_event e
             where e.match_id = p.match_id and e.kind = 'goal'
               and e.team_id = p.team_id
               and coalesce(e.detail, '') <> 'Own Goal') as first_for,
           (select min(e.minute) from core.match_event e
             where e.match_id = p.match_id and e.kind = 'goal'
               and e.team_id <> p.team_id
               and coalesce(e.detail, '') <> 'Own Goal') as first_against
      from played p
)
select team_id,
       t.canonical_name as team,
       c.code  as competition_code,
       s.label as season,
       s.start_year,
       case when grouping(is_home) = 1 then 'overall'
            when is_home then 'home' else 'away' end as venue,
       count(*)                                              as matches,
       round(avg(first_for)::numeric, 1)                      as avg_first_scored,
       round(avg(first_against)::numeric, 1)                  as avg_first_conceded,
       count(first_for)                                       as matches_scored,
       count(first_against)                                   as matches_conceded,
       count(*) filter (
         where first_for is not null
           and (first_against is null or first_for < first_against)
       )                                                      as scored_first,
       count(*) filter (where first_for is null)              as failed_to_score
  from firsts
  join core.team t using (team_id)
  join core.competition c using (competition_id)
  join core.season s using (season_id)
 group by grouping sets (
    (team_id, t.canonical_name, c.code, s.label, s.start_year, is_home),
    (team_id, t.canonical_name, c.code, s.label, s.start_year)
 );

comment on materialized view public.team_season_first is 'When a team tends to score first and concede first, and how often it fails to score at all. Averages over matches where it happened, so a side that scores in half its games is not credited with a goal in the others. Refreshed by footy build-features.';

create unique index team_season_timing_key
  on public.team_season_timing (team_id, competition_code, season, side, venue, band);
create index team_season_timing_team_idx on public.team_season_timing (team_id);

create unique index team_season_first_key
  on public.team_season_first (team_id, competition_code, season, venue);
create index team_season_first_team_idx on public.team_season_first (team_id);

grant select on public.match_event, public.team_season_timing, public.team_season_first
  to anon, authenticated;
