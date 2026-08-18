-- ============================================================
-- Season totals from API-Football /players.
--
-- 2025/26 player pages were thin in every league for the same
-- reason: FBref match sheets stop at 2024/25, and the event
-- path only knows starts, goals, assists and cards. Minutes
-- were 90 times starts. Shots, tackles, interceptions and
-- fouls were null.
--
-- /players?league=&season= publishes those totals for every
-- competition we cover, including the ones FBref never
-- reached. Grain is player, club, competition, season — a
-- mid-season transfer is two rows, which is what the page
-- already expects.
-- ============================================================

create table core.player_season (
  player_id         integer  not null references core.player(player_id) on delete cascade,
  team_id           integer  not null references core.team(team_id),
  competition_id    smallint not null references core.competition,
  season_id         integer  not null references core.season,
  appearances       smallint not null,
  starts            smallint not null,
  minutes           integer  not null,
  goals             smallint not null,
  assists           smallint not null,
  shots             smallint,
  shots_on_target   smallint,
  tackles           smallint,
  interceptions     smallint,
  fouls             smallint,
  yellows           smallint not null,
  reds              smallint not null,
  source_id         smallint not null references core.source,
  loaded_at         timestamptz not null default now(),
  primary key (player_id, team_id, competition_id, season_id)
);
comment on table core.player_season is 'Provider season totals per player, club and competition. Loaded from API-Football /players.';

create index player_season_team_idx
  on core.player_season (team_id, season_id);
create index player_season_comp_idx
  on core.player_season (competition_id, season_id);

drop view if exists public.team_key_player;
drop materialized view if exists public.player_season_stat;

create materialized view public.player_season_stat as
with identity_map as (
    select fbref_id, api_id, team_id
      from (
            select fb.player_id as fbref_id,
                   api.player_id as api_id,
                   sm.team_id,
                   count(*) over (
                       partition by fb.player_id, sm.team_id
                   ) as aliases_from_fb,
                   count(*) over (
                       partition by api.player_id, sm.team_id
                   ) as aliases_from_api
              from core.squad_member sm
              join core.player api on api.player_id = sm.player_id
                                  and api.origin = 'api_football'
              join (
                    select distinct player_id, team_id from core.appearance
                   ) a on a.team_id = sm.team_id
              join core.player fb on fb.player_id = a.player_id
                                 and fb.origin = 'fbref'
             where lower(extensions.unaccent(
                       split_part(trim(fb.canonical_name), ' ', -1)
                   ))
                 = lower(extensions.unaccent(
                       split_part(trim(api.canonical_name), ' ', -1)
                   ))
               and left(regexp_replace(
                       extensions.unaccent(fb.canonical_name), '[^A-Za-z]', '', 'g'
                   ), 1)
                 = left(regexp_replace(
                       extensions.unaccent(api.canonical_name), '[^A-Za-z]', '', 'g'
                   ), 1)
             group by fb.player_id, api.player_id, sm.team_id
           ) pairs
     where aliases_from_fb = 1
       and aliases_from_api = 1
),
from_appearance as (
    select a.player_id,
           a.team_id,
           t.canonical_name as team,
           c.code as competition_code,
           s.label as season,
           s.start_year,
           count(*) as appearances,
           count(*) filter (where a.is_starter) as starts,
           coalesce(sum(a.minutes), 0)::integer as minutes,
           coalesce(sum(a.goals), 0)::integer as goals,
           coalesce(sum(a.assists), 0)::integer as assists,
           coalesce(sum(a.shots), 0)::integer as shots,
           coalesce(sum(a.shots_on_target), 0)::integer as shots_on_target,
           coalesce(sum(a.tackles_won), 0)::integer as tackles,
           coalesce(sum(a.interceptions), 0)::integer as interceptions,
           coalesce(sum(a.yellows), 0)::integer as yellows,
           coalesce(sum(a.reds), 0)::integer as reds,
           coalesce(sum(a.fouls_committed), 0)::integer as fouls,
           'appearance'::text as source
      from core.appearance a
      join core.match m on m.match_id = a.match_id
      join core.team t on t.team_id = a.team_id
      join core.competition c on c.competition_id = m.competition_id
      join core.season s on s.season_id = m.season_id
     where m.home_goals_ft is not null
     group by a.player_id, a.team_id, t.canonical_name,
              c.code, s.label, s.start_year
),
from_appearance_linked as (
    select i.api_id as player_id,
           a.team_id,
           a.team,
           a.competition_code,
           a.season,
           a.start_year,
           a.appearances,
           a.starts,
           a.minutes,
           a.goals,
           a.assists,
           a.shots,
           a.shots_on_target,
           a.tackles,
           a.interceptions,
           a.yellows,
           a.reds,
           a.fouls,
           a.source
      from from_appearance a
      join identity_map i on i.fbref_id = a.player_id and i.team_id = a.team_id
     where i.api_id <> a.player_id
),
from_api as (
    select ps.player_id,
           ps.team_id,
           t.canonical_name as team,
           c.code as competition_code,
           s.label as season,
           s.start_year,
           ps.appearances,
           ps.starts,
           ps.minutes,
           ps.goals,
           ps.assists,
           ps.shots,
           ps.shots_on_target,
           ps.tackles,
           ps.interceptions,
           ps.yellows,
           ps.reds,
           ps.fouls,
           'api'::text as source
      from core.player_season ps
      join core.team t on t.team_id = ps.team_id
      join core.competition c on c.competition_id = ps.competition_id
      join core.season s on s.season_id = ps.season_id
),
event_by_match as (
    select e.match_id,
           e.player_id,
           e.team_id,
           count(*) filter (
               where e.kind = 'goal'
                 and coalesce(e.detail, '') <> 'Own Goal'
           ) as goals,
           count(*) filter (
               where e.kind = 'card'
                 and e.detail ilike '%yellow%'
                 and e.detail not ilike '%second%'
           ) as yellows,
           count(*) filter (
               where e.kind = 'card'
                 and (e.detail ilike '%red%' or e.detail ilike '%second%')
           ) as reds
      from core.match_event e
     where e.player_id is not null
     group by e.match_id, e.player_id, e.team_id
),
assist_by_match as (
    select e.match_id,
           lp.player_id,
           lp.team_id,
           count(*) as assists
      from core.match_event e
      join core.match_lineup_player lp
        on lp.match_id = e.match_id
       and lp.team_id = e.team_id
       and core.norm_name(lp.player_name) = core.norm_name(e.assist_name)
     where e.kind = 'goal'
       and e.assist_name is not null
       and lp.player_id is not null
     group by e.match_id, lp.player_id, lp.team_id
),
from_events as (
    select lp.player_id,
           lp.team_id,
           t.canonical_name as team,
           c.code as competition_code,
           s.label as season,
           s.start_year,
           count(*) as appearances,
           count(*) filter (where lp.is_starter) as starts,
           (90 * count(*) filter (where lp.is_starter))::integer as minutes,
           coalesce(sum(ev.goals), 0)::integer as goals,
           coalesce(sum(ast.assists), 0)::integer as assists,
           null::integer as shots,
           null::integer as shots_on_target,
           null::integer as tackles,
           null::integer as interceptions,
           coalesce(sum(ev.yellows), 0)::integer as yellows,
           coalesce(sum(ev.reds), 0)::integer as reds,
           null::integer as fouls,
           'event'::text as source
      from core.match_lineup_player lp
      join core.match m on m.match_id = lp.match_id
      join core.team t on t.team_id = lp.team_id
      join core.competition c on c.competition_id = m.competition_id
      join core.season s on s.season_id = m.season_id
      left join event_by_match ev
             on ev.match_id = lp.match_id
            and ev.player_id = lp.player_id
            and ev.team_id = lp.team_id
      left join assist_by_match ast
             on ast.match_id = lp.match_id
            and ast.player_id = lp.player_id
            and ast.team_id = lp.team_id
     where lp.player_id is not null
       and m.home_goals_ft is not null
     group by lp.player_id, lp.team_id, t.canonical_name,
              c.code, s.label, s.start_year
)
select * from from_appearance
union all
select * from from_appearance_linked
union all
select a.* from from_api a
 where not exists (
        select 1 from from_appearance x
         where x.player_id = a.player_id
           and x.team_id = a.team_id
           and x.competition_code = a.competition_code
           and x.season = a.season
       )
   and not exists (
        select 1 from from_appearance_linked x
         where x.player_id = a.player_id
           and x.team_id = a.team_id
           and x.competition_code = a.competition_code
           and x.season = a.season
       )
union all
select e.* from from_events e
 where not exists (
        select 1 from from_appearance x
         where x.player_id = e.player_id
           and x.team_id = e.team_id
           and x.competition_code = e.competition_code
           and x.season = e.season
       )
   and not exists (
        select 1 from from_appearance_linked x
         where x.player_id = e.player_id
           and x.team_id = e.team_id
           and x.competition_code = e.competition_code
           and x.season = e.season
       )
   and not exists (
        select 1 from from_api x
         where x.player_id = e.player_id
           and x.team_id = e.team_id
           and x.competition_code = e.competition_code
           and x.season = e.season
       );

create unique index player_season_stat_key
  on public.player_season_stat (player_id, team_id, competition_code, season);
create index player_season_stat_player_idx
  on public.player_season_stat (player_id, start_year desc);
create index player_season_stat_team_idx
  on public.player_season_stat (team_id, start_year desc);

comment on materialized view public.player_season_stat is 'Per player, club, competition and season. FBref match sheets win where they exist; API-Football season totals fill the rest; events are the last fallback. Refreshed by footy build-features.';

create view public.team_key_player as
with scored as (
    select sm.team_id,
           sm.player_id,
           p.canonical_name as player_name,
           p.photo_url,
           sm.position,
           sm.shirt_number,
           coalesce(sum(st.appearances), 0)::integer as appearances,
           coalesce(sum(st.starts), 0)::integer as starts,
           coalesce(sum(st.minutes), 0)::integer as minutes,
           coalesce(sum(st.goals), 0)::integer as goals,
           coalesce(sum(st.assists), 0)::integer as assists,
           coalesce(sum(st.goals), 0) * 3.0
             + coalesce(sum(st.assists), 0) * 2.0
             + coalesce(sum(st.minutes), 0) / 90.0 as score
      from core.squad_member sm
      join core.player p on p.player_id = sm.player_id
      left join public.player_season_stat st
             on st.player_id = sm.player_id
            and st.team_id = sm.team_id
            and st.start_year >= extract(year from current_date)::int - 2
     group by sm.team_id, sm.player_id, p.canonical_name, p.photo_url,
              sm.position, sm.shirt_number
)
select team_id,
       player_id,
       player_name,
       photo_url,
       position,
       shirt_number,
       appearances,
       starts,
       minutes,
       goals,
       assists,
       rank() over (
           partition by team_id
           order by score desc, minutes desc, player_name
       ) as rank
  from scored
 where score > 0
    or appearances > 0;

comment on view public.team_key_player is 'Current squad ranked by what they have done for this club in the last two seasons.';

grant select on public.player_season_stat, public.team_key_player
  to anon, authenticated;
