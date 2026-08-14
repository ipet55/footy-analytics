-- ============================================================
-- Count only regulation play in the timing views.
--
-- The event feed reports extra time and penalty shootouts as ordinary
-- goal events. A Champions League qualifier that finished 0-3 and went
-- to a shootout produced goal events at minutes 95 and 100, and the
-- band calculation caps at "76 and after" — so shootout kicks were
-- being counted as late goals.
--
-- That is the worst kind of error for a chart whose entire purpose is
-- when goals happen: it makes every knockout competition look like it
-- scores heavily in the closing minutes, and the reader has no way to
-- see why.
--
-- Restricted to minutes 1 to 90, with anything before kickoff folded
-- into the first band and stoppage time into the sixth. Extra time is
-- excluded rather than given bands of its own, because a team playing
-- 120 minutes is not comparable with one playing 90 and averaging them
-- together answers no question anybody asked.
--
-- 'first goal' is restricted the same way, and for a stronger reason:
-- an extra-time winner is not when a team 'tends to score first'.
-- ============================================================

drop materialized view if exists public.team_season_timing;
drop materialized view if exists public.team_season_first;

create materialized view public.team_season_timing as
with goals as (
    select e.match_id, e.team_id, e.minute,
           m.home_team_id, m.away_team_id, m.competition_id, m.season_id
      from core.match_event e
      join core.match m using (match_id)
     where e.kind = 'goal'
       and coalesce(e.detail, '') <> 'Own Goal'
       -- Regulation play only. See the migration header.
       and e.minute <= 90
),
sided as (
    select g.match_id, s.team_id, s.side, g.minute,
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

comment on materialized view public.team_season_timing is 'Goals scored and conceded by fifteen-minute band, per season and venue, in regulation play only. Extra time and penalty shootouts are excluded: the feed reports them as ordinary goals and counting them made every knockout competition look like it scored heavily after 75 minutes. Refreshed by footy build-features.';

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
               and e.team_id = p.team_id and e.minute <= 90
               and coalesce(e.detail, '') <> 'Own Goal') as first_for,
           (select min(e.minute) from core.match_event e
             where e.match_id = p.match_id and e.kind = 'goal'
               and e.team_id <> p.team_id and e.minute <= 90
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

comment on materialized view public.team_season_first is 'When a team tends to score first and concede first in regulation play, and how often it fails to score. An extra-time winner is not when a side "tends to score first", so extra time is excluded. Refreshed by footy build-features.';

create unique index team_season_timing_key
  on public.team_season_timing (team_id, competition_code, season, side, venue, band);
create index team_season_timing_team_idx on public.team_season_timing (team_id);

create unique index team_season_first_key
  on public.team_season_first (team_id, competition_code, season, venue);
create index team_season_first_team_idx on public.team_season_first (team_id);

grant select on public.team_season_timing, public.team_season_first
  to anon, authenticated;
