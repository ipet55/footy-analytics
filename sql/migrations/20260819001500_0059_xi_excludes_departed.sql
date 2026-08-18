-- ============================================================
-- Do not project a player who has left, and attach the stats
-- that were stored under a different identity.
--
-- Expected XI ranked A. Griezmann in Atlético's eleven for the
-- opening weekend of 2026/27 because he started eight of their
-- last ten sheets, in May. He moved to Orlando City on 30 June.
-- The squad already knew that; the projection did not look at
-- the squad. A club with a loaded roster now only projects
-- people still on it. A club with no roster is left alone, so
-- a newly covered side is not emptied by a missing list.
--
-- Player pages had the same class of hole. J. Álvarez's La Liga
-- sheets were stored as the name 'J. Alvarez' with a null
-- player_id, so the season aggregate dropped them and the page
-- showed only Champions League. The same human's FBref history
-- (Julián Álvarez, 17 league goals in 2024/25) lived under a
-- second id. Both are repaired here: unresolved sheet names are
-- pointed at the current squad member, and FBref totals are
-- copied onto the API-Football id when last name, first initial
-- and club agree and the match is unique.
-- ============================================================

-- Persist the name resolution so every later reader benefits, not
-- only the season aggregate. Restricted to a single squad member
-- with that normalised name, so two namesakes on one roster stay
-- unresolved rather than being assigned at random.
update core.match_lineup_player lp
   set player_id = hit.player_id
  from (
        select team_id, norm, player_id
          from (
                select sm.team_id,
                       core.norm_name(p.canonical_name) as norm,
                       sm.player_id,
                       count(*) over (
                           partition by sm.team_id, core.norm_name(p.canonical_name)
                       ) as n
                  from core.squad_member sm
                  join core.player p on p.player_id = sm.player_id
               ) x
         where n = 1
       ) hit
 where lp.player_id is null
   and lp.team_id = hit.team_id
   and core.norm_name(lp.player_name) = hit.norm;

update core.match_event e
   set player_id = hit.player_id
  from (
        select team_id, norm, player_id
          from (
                select sm.team_id,
                       core.norm_name(p.canonical_name) as norm,
                       sm.player_id,
                       count(*) over (
                           partition by sm.team_id, core.norm_name(p.canonical_name)
                       ) as n
                  from core.squad_member sm
                  join core.player p on p.player_id = sm.player_id
               ) x
         where n = 1
       ) hit
 where e.player_id is null
   and e.player_name is not null
   and e.team_id = hit.team_id
   and core.norm_name(e.player_name) = hit.norm;

update core.match_absence a
   set player_id = hit.player_id
  from (
        select team_id, norm, player_id
          from (
                select sm.team_id,
                       core.norm_name(p.canonical_name) as norm,
                       sm.player_id,
                       count(*) over (
                           partition by sm.team_id, core.norm_name(p.canonical_name)
                       ) as n
                  from core.squad_member sm
                  join core.player p on p.player_id = sm.player_id
               ) x
         where n = 1
       ) hit
 where a.player_id is null
   and a.team_id = hit.team_id
   and core.norm_name(a.player_name) = hit.norm;

create or replace view public.expected_xi as
with candidate as (
    select m.match_id,
           s.team_id,
           s.team_id = m.home_team_id as is_home,
           s.player_name,
           s.position,
           s.shirt_number,
           s.starts,
           s.named,
           ab.status as absence_status,
           ab.reason as absence_reason,
           s.player_id,
           pl.photo_url,
           row_number() over (
               partition by m.match_id, s.team_id,
                            coalesce(s.position = 'G', false)
               order by s.starts desc, s.named desc, s.player_name
           ) as rank_in_group
      from core.match m
      join public.team_recent_starts s
        on s.team_id in (m.home_team_id, m.away_team_id)
      left join core.match_absence ab
             on ab.match_id = m.match_id
            and ab.team_id = s.team_id
            and core.norm_name(ab.player_name) = core.norm_name(s.player_name)
      left join core.player pl on pl.player_id = s.player_id
     where m.home_goals_ft is null
       and m.status = 'scheduled'
       and m.kickoff_date between current_date - 1 and current_date + 14
       and (ab.status is null or ab.status <> 'out')
       -- A loaded squad is the authority on who is still at the club.
       -- Griezmann started eight of the last ten and still would, if
       -- this clause were not here.
       and (
            not exists (
                select 1 from core.squad_member sm where sm.team_id = s.team_id
            )
            or exists (
                select 1
                  from core.squad_member sm
                  join core.player p on p.player_id = sm.player_id
                 where sm.team_id = s.team_id
                   and (
                        sm.player_id = s.player_id
                        or core.norm_name(p.canonical_name)
                         = core.norm_name(s.player_name)
                   )
            )
       )
)
select match_id,
       team_id,
       is_home,
       player_name,
       position,
       shirt_number,
       starts,
       named,
       absence_status,
       absence_reason,
       case
         when coalesce(position = 'G', false) then rank_in_group = 1
         else rank_in_group <= 10
       end as expected_to_start,
       player_id,
       photo_url
  from candidate
 where (coalesce(position = 'G', false) and rank_in_group <= 2)
    or (not coalesce(position = 'G', false) and rank_in_group <= 18);

comment on view public.expected_xi is 'Who is likeliest to start: recent sheets, minus anyone reported out and anyone no longer on the squad. A guess until the confirmed sheet appears.';

grant select on public.expected_xi to anon, authenticated;

-- Rebuild the season aggregate with the resolved ids and the extra
-- appearance columns (tackles, interceptions). team_key_player sits
-- on top of the MV, so it has to be dropped first.
drop view if exists public.team_key_player;
drop materialized view if exists public.player_season_stat;

create materialized view public.player_season_stat as
with identity_map as (
    -- FBref id → API-Football id, only when last name, first initial
    -- and club agree and the pair is unique. Julián Álvarez and
    -- J. Álvarez at Atlético match; two J. Álvarez on one roster
    -- would not.
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
select e.* from from_events e
 where not exists (
        select 1 from from_appearance a
         where a.player_id = e.player_id
           and a.team_id = e.team_id
           and a.competition_code = e.competition_code
           and a.season = e.season
       )
   and not exists (
        select 1 from from_appearance_linked a
         where a.player_id = e.player_id
           and a.team_id = e.team_id
           and a.competition_code = e.competition_code
           and a.season = e.season
       );

create unique index player_season_stat_key
  on public.player_season_stat (player_id, team_id, competition_code, season);
create index player_season_stat_player_idx
  on public.player_season_stat (player_id, start_year desc);
create index player_season_stat_team_idx
  on public.player_season_stat (team_id, start_year desc);

comment on materialized view public.player_season_stat is 'Per player, club, competition and season. Appearance rows win where both sources exist; FBref totals are also copied onto the matching API-Football id. Refreshed by footy build-features.';

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
