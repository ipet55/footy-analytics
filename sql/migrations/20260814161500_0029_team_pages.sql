-- ============================================================
-- Rebuild the team history views around venue, and add a team list.
--
-- 0026 gave one number per line per season. What a reader actually
-- wants is the same line three ways — overall, at home, away —
-- because that split is most of the information. Galatasaray earn
-- 6.53 corners a game at home and 4.47 away; a single 5.5 hides the
-- thing you would bet on.
--
-- Three views replace two:
--
--   team_season_measure  one row per team, season, measure and
--                        venue: how many matches, the total, the
--                        per-match average, and how often the team
--                        had more of it than its opponent.
--
--   team_season_line     the same keys plus a line: how often the
--                        team went over it.
--
--   team               a searchable list, so a team page is
--                        reachable without knowing an id.
--
-- Split into two rather than one wide table because the line rows
-- repeat the per-match figures otherwise, and a reader comparing
-- 'over 2.5' across venues should not have to trust that three
-- copies of the average agree.
--
-- 'More than opponent' needs the opponent's value, which
-- core.team_match already carries as the *_against columns. It is
-- null for the totals, where the question is meaningless.
--
-- Lines now start at 2.5 for corners and run to 8.5, matching what
-- is actually offered on a team's corner count rather than the
-- narrower set the count models price. A reader looking up whether
-- over 2.5 corners is worth taking should find it here.
-- ============================================================

drop view if exists public.team_season_summary;
drop view if exists public.team_season_venue;

create view public.team_season_measure as
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

comment on view public.team_season_measure is 'Per-match averages and how often a team had more of something than its opponent, split overall / at home / away. Counted from matches played, so it describes the past and adjusts for nothing.';

create view public.team_season_line as
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

comment on view public.team_season_line is 'How often a team went over each line, split overall / at home / away. Historical frequency over matches played, not a forecast: it takes no account of the opponent.';

create view public.team as
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

comment on view public.team is 'Every team with at least one played match, for search and navigation. No model output.';

grant select on public.team_season_measure, public.team_season_line, public.team
  to anon, authenticated;
