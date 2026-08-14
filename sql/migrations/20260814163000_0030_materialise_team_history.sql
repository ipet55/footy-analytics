-- ============================================================
-- Materialise the team history views.
--
-- As plain views they timed out. Each one aggregates 99,000
-- team-match rows, fans them out across nine measures, several lines
-- and two grouping sets, and does all of it again for every request.
-- Filtering to one team does not help much: the grouping sets are
-- computed before the filter can be applied, so a single team page
-- cost 3.4 seconds directly and exceeded the API's statement timeout
-- through PostgREST. The page returned 404, because a failed query
-- and an unknown team are indistinguishable to the caller.
--
-- Materialising is the right answer rather than a workaround. This is
-- history: a season's counts change only when a match is played, and
-- are then fixed forever. Recomputing them per request is work with
-- no purpose.
--
-- The cost is staleness, and this codebase has already been bitten by
-- exactly that — core.market_1x2_mv went unrefreshed after a load and
-- wrote null market probabilities, which read as "no odds exist"
-- rather than "the view is behind". So the refresh is attached to
-- `build-features`, which already refreshes the odds views and
-- already runs after every load, rather than left to be remembered.
-- ============================================================

drop view if exists public.team_season_measure;
drop view if exists public.team_season_line;
drop view if exists public.team;

create materialized view public.team_season_measure as
with played as (
    select tm.team_id, t.canonical_name as team, c.code as competition_code,
           s.label as season, s.start_year, tm.is_home,
           tm.goals_for, tm.goals_against, tm.corners_for, tm.corners_against,
           tm.shots_for, tm.shots_against, tm.yellows_for, tm.yellows_against,
           tm.fouls_committed, tm.fouls_drawn,
           tm.goals_total, tm.corners_total, tm.points
      from core.team_match tm
      join core.match m       on m.match_id = tm.match_id
      join core.team t        on t.team_id = tm.team_id
      join core.competition c on c.competition_id = m.competition_id
      join core.season s      on s.season_id = m.season_id
     where tm.period = 'FT' and m.home_goals_ft is not null
),
spread as (
    select p.team_id, p.team, p.competition_code, p.season, p.start_year,
           p.is_home, p.points, v.measure, v.own, v.opponent
      from played p
     cross join lateral (values
            ('goals scored',    p.goals_for,       p.goals_against),
            ('goals conceded',  p.goals_against,   p.goals_for),
            ('goals total',     p.goals_total,     null::numeric),
            ('corners for',     p.corners_for,     p.corners_against),
            ('corners against', p.corners_against, p.corners_for),
            ('corners total',   p.corners_total,   null::numeric),
            ('shots',           p.shots_for,       p.shots_against),
            ('cards',           p.yellows_for,     p.yellows_against),
            ('fouls',           p.fouls_committed, p.fouls_drawn)
        ) as v(measure, own, opponent)
)
select team_id, team, competition_code, season, start_year, measure,
       case when grouping(is_home) = 1 then 'overall'
            when is_home then 'home' else 'away' end as venue,
       count(*)                                            as matches,
       sum(own)                                            as total,
       round(avg(own)::numeric, 2)                         as per_match,
       round(avg(points)::numeric, 2)                      as points_per_game,
       case when count(opponent) = 0 then null
            else round(avg((own > opponent)::int)::numeric, 4) end as beat_opponent_rate
  from spread
 where own is not null
 group by grouping sets (
    (team_id, team, competition_code, season, start_year, measure, is_home),
    (team_id, team, competition_code, season, start_year, measure)
 );

comment on materialized view public.team_season_measure is 'Per-match averages and how often a team had more of something than its opponent, split overall / at home / away. History counted from matches played; it adjusts for nothing. Refreshed by footy build-features.';

create materialized view public.team_season_line as
with played as (
    select tm.team_id, t.canonical_name as team, c.code as competition_code,
           s.label as season, s.start_year, tm.is_home,
           tm.goals_for, tm.goals_against, tm.corners_for, tm.corners_against,
           tm.shots_for, tm.yellows_for, tm.fouls_committed,
           tm.goals_total, tm.corners_total
      from core.team_match tm
      join core.match m       on m.match_id = tm.match_id
      join core.team t        on t.team_id = tm.team_id
      join core.competition c on c.competition_id = m.competition_id
      join core.season s      on s.season_id = m.season_id
     where tm.period = 'FT' and m.home_goals_ft is not null
),
spread as (
    select p.team_id, p.team, p.competition_code, p.season, p.start_year,
           p.is_home, v.measure, v.own, line
      from played p
     cross join lateral (values
            ('goals scored',    p.goals_for,       array[0.5,1.5,2.5,3.5]),
            ('goals conceded',  p.goals_against,   array[0.5,1.5,2.5,3.5]),
            ('goals total',     p.goals_total,     array[0.5,1.5,2.5,3.5,4.5,5.5]),
            ('corners for',     p.corners_for,     array[2.5,3.5,4.5,5.5,6.5,7.5,8.5]),
            ('corners against', p.corners_against, array[2.5,3.5,4.5,5.5,6.5,7.5,8.5]),
            ('corners total',   p.corners_total,   array[6.5,7.5,8.5,9.5,10.5,11.5,12.5,13.5]),
            ('shots',           p.shots_for,       array[6.5,9.5,12.5,15.5,18.5]),
            ('cards',           p.yellows_for,     array[0.5,1.5,2.5,3.5]),
            ('fouls',           p.fouls_committed, array[8.5,10.5,12.5,14.5])
        ) as v(measure, own, lines)
     cross join lateral unnest(v.lines) as line
)
select team_id, team, competition_code, season, start_year, measure,
       case when grouping(is_home) = 1 then 'overall'
            when is_home then 'home' else 'away' end as venue,
       line,
       count(*)                                    as matches,
       count(*) filter (where own > line)          as over_count,
       round(avg((own > line)::int)::numeric, 4)   as over_rate
  from spread
 where own is not null
 group by grouping sets (
    (team_id, team, competition_code, season, start_year, measure, line, is_home),
    (team_id, team, competition_code, season, start_year, measure, line)
 );

comment on materialized view public.team_season_line is 'How often a team went over each line, split overall / at home / away. Historical frequency, not a forecast. Refreshed by footy build-features.';

create materialized view public.team as
select t.team_id,
       t.canonical_name as team,
       coalesce(t.short_name, t.canonical_name) as team_short,
       t.country,
       count(*)                                as matches,
       max(s.label)                            as latest_season,
       max(s.start_year)                       as latest_start_year,
       array_agg(distinct c.code order by c.code) as competitions
  from core.team t
  join core.match m on m.home_team_id = t.team_id or m.away_team_id = t.team_id
  join core.competition c on c.competition_id = m.competition_id
  join core.season s      on s.season_id = m.season_id
 where m.home_goals_ft is not null
 group by t.team_id, t.canonical_name, t.short_name, t.country;

comment on materialized view public.team is 'Every team with at least one played match, for search and navigation. No model output. Refreshed by footy build-features.';

-- A team page filters on team_id and nothing else, so that is the index that
-- matters. The unique ones also make a concurrent refresh possible later.
create unique index team_season_measure_key
  on public.team_season_measure (team_id, competition_code, season, measure, venue);
create index team_season_measure_team_idx on public.team_season_measure (team_id);

create unique index team_season_line_key
  on public.team_season_line (team_id, competition_code, season, measure, venue, line);
create index team_season_line_team_idx on public.team_season_line (team_id);

create unique index team_key on public.team (team_id);
create index team_name_idx on public.team (team);

grant select on public.team_season_measure, public.team_season_line, public.team
  to anon, authenticated;
