-- ============================================================
-- What actually happened to a team in a season.
--
-- Every number the app shows so far is a prediction: a probability
-- from a fitted model, adjusted for the opponent. This is the other
-- thing entirely — a count of what happened, over the games a team
-- actually played, with no model involved.
--
-- Keeping them apart matters. "Arsenal went over 0.5 goals in 92%
-- of their league games" is a description of the past, and reading
-- it as a forecast is the exact mistake the roadmap warns about:
-- it says nothing about who they play next. The view is named for
-- what it is, and the app labels it as history rather than
-- prediction.
--
-- Long rather than wide. Six measures times five lines would be
-- thirty columns and a new migration every time a line is added;
-- as rows the app can pivot whatever it wants and the shape never
-- changes.
--
-- Lines are the ones the count models already price, so the
-- historical frequency sits next to the model's probability for the
-- same threshold and the two can be compared directly.
-- ============================================================

create or replace view public.team_season_summary as
with played as (
    select tm.team_id,
           t.canonical_name as team,
           c.code  as competition_code,
           s.label as season,
           s.start_year,
           tm.is_home,
           tm.goals_for,
           tm.goals_against,
           tm.goals_for + tm.goals_against as goals_total,
           tm.corners_for,
           tm.corners_against,
           tm.corners_for + tm.corners_against as corners_total,
           tm.yellows_for,
           tm.fouls_committed,
           tm.shots_for
      from core.team_match tm
      join core.match m      on m.match_id = tm.match_id
      join core.team t       on t.team_id = tm.team_id
      join core.competition c on c.competition_id = m.competition_id
      join core.season s      on s.season_id = m.season_id
     where tm.period = 'FT'
       and m.home_goals_ft is not null
),
measures as (
    -- (label, value, the lines worth reporting for it)
    select p.*, m.measure, m.value, m.lines
      from played p
     cross join lateral (values
            ('goals scored',    p.goals_for,        array[0.5, 1.5, 2.5, 3.5]),
            ('goals conceded',  p.goals_against,    array[0.5, 1.5, 2.5, 3.5]),
            ('goals total',     p.goals_total,      array[0.5, 1.5, 2.5, 3.5, 4.5]),
            ('corners for',     p.corners_for,      array[3.5, 4.5, 5.5, 6.5]),
            ('corners against', p.corners_against,  array[3.5, 4.5, 5.5, 6.5]),
            ('corners total',   p.corners_total,    array[8.5, 9.5, 10.5, 11.5, 12.5]),
            ('cards',           p.yellows_for,      array[0.5, 1.5, 2.5, 3.5]),
            ('fouls',           p.fouls_committed,  array[8.5, 10.5, 12.5]),
            ('shots',           p.shots_for,        array[9.5, 12.5, 15.5])
        ) as m(measure, value, lines)
)
select team_id,
       team,
       competition_code,
       season,
       start_year,
       measure,
       line,
       count(*)                                        as matches,
       count(*) filter (where value > line)            as over_count,
       round(avg((value > line)::int)::numeric, 4)     as over_rate,
       round(avg(value)::numeric, 3)                   as mean_value
  from measures
 cross join lateral unnest(lines) as line
 where value is not null
 group by team_id, team, competition_code, season, start_year, measure, line;

comment on view public.team_season_summary is 'How often a team actually went over each line, per season, counted from the matches they played. History, not prediction: it does not adjust for who the opponent was, so it describes the past and forecasts nothing.';

-- Home and away separately, because the split is most of why a season average
-- misleads: a side can be over 3.5 corners in nearly every home game and under
-- it in most away ones, and one number hides that completely.
create or replace view public.team_season_venue as
select tm.team_id,
       t.canonical_name as team,
       c.code  as competition_code,
       s.label as season,
       case when tm.is_home then 'home' else 'away' end as venue,
       count(*)                                          as matches,
       round(avg(tm.goals_for)::numeric, 3)              as goals_for,
       round(avg(tm.goals_against)::numeric, 3)          as goals_against,
       round(avg(tm.corners_for)::numeric, 3)            as corners_for,
       round(avg(tm.corners_against)::numeric, 3)        as corners_against,
       round(avg(tm.shots_for)::numeric, 3)              as shots_for,
       round(avg(tm.yellows_for)::numeric, 3)            as cards,
       round(avg(tm.fouls_committed)::numeric, 3)        as fouls,
       round(avg((tm.goals_for > 0.5)::int)::numeric, 4) as scored_rate,
       round(avg((tm.goals_against > 0.5)::int)::numeric, 4) as conceded_rate,
       round(avg(tm.points)::numeric, 3)                 as points_per_game
  from core.team_match tm
  join core.match m       on m.match_id = tm.match_id
  join core.team t        on t.team_id = tm.team_id
  join core.competition c on c.competition_id = m.competition_id
  join core.season s      on s.season_id = m.season_id
 where tm.period = 'FT'
   and m.home_goals_ft is not null
 group by tm.team_id, t.canonical_name, c.code, s.label, tm.is_home;

comment on view public.team_season_venue is 'Season averages split by home and away. The split is most of why a single season average misleads.';

grant select on public.team_season_summary, public.team_season_venue
  to anon, authenticated;
