-- ============================================================
-- Player pages, season stats, and the key-player list.
--
-- A squad list of names is not enough: clicking a player has to open
-- what he did, per competition, in the seasons we hold. Two sources
-- cover that, and they do not overlap cleanly.
--
-- core.appearance (FBref) has minutes, shots, fouls and the rest, for
-- the original five leagues. core.match_lineup_player plus
-- core.match_event (API-Football) has starts, goals and cards for
-- every competition we cover, including the ones FBref never reached.
--
-- Appearance wins where both exist: it is the richer row. The event
-- path fills the rest. Players the event feed never resolved to an
-- id are dropped rather than published under a name, because a page
-- keyed on player_id cannot show them and inventing a row for a
-- missing id is how this table would grow ghosts.
--
-- public.team_key_player is the current squad ranked by what they
-- have done for this club in the last two seasons. That is a
-- description, not a model feature: the page uses it to say who
-- matters, and the absence adjustment uses the same ranking to
-- decide whose unavailability is allowed to move a probability.
-- ============================================================

create materialized view public.player_season_stat as
with from_appearance as (
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
event_by_match as (
    select e.match_id,
           e.player_id,
           e.team_id,
           count(*) filter (
               where e.kind = 'goal'
                 and coalesce(e.detail, '') <> 'Own Goal'
           ) as goals,
           count(*) filter (
               where e.kind = 'goal'
                 and e.detail = 'Penalty'
           ) as penalties,
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
    -- The feed stores the assister as a name, not an id. Matched on the
    -- normalised name of a player who was in the same match's sheet, so a
    -- namesake on the other side cannot take the credit.
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
           -- The sheet has no minute count. A starter is credited with 90;
           -- a substitute is not guessed. That understates minutes for
           -- impact substitutes and is still better than inventing 20.
           (90 * count(*) filter (where lp.is_starter))::integer as minutes,
           coalesce(sum(ev.goals), 0)::integer as goals,
           coalesce(sum(ast.assists), 0)::integer as assists,
           null::integer as shots,
           null::integer as shots_on_target,
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
select e.* from from_events e
 where not exists (
        select 1 from from_appearance a
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

comment on materialized view public.player_season_stat is 'Per player, club, competition and season. Appearance rows win where both sources exist; event rows fill the competitions FBref does not cover. Refreshed by footy build-features.';

create view public.player as
select distinct on (p.player_id)
       p.player_id,
       p.canonical_name as player_name,
       p.photo_url,
       sm.team_id,
       t.canonical_name as team,
       (
         select 'https://media.api-sports.io/football/teams/'
                || ta.source_team_id || '.png'
           from core.team_alias ta
           join core.source src on src.source_id = ta.source_id
                               and src.code = 'api_football'
          where ta.team_id = sm.team_id
            and ta.source_team_id is not null
          limit 1
       ) as team_logo_url,
       sm.shirt_number,
       sm.position,
       sm.age
  from core.player p
  left join core.squad_member sm on sm.player_id = p.player_id
  left join core.team t on t.team_id = sm.team_id
 order by p.player_id, sm.team_id;

comment on view public.player is 'A footballer the app can open. Current club is the squad membership, which is empty for a player who has left or was only ever seen in a historical sheet.';

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
           -- Goals and assists first, then minutes, so a striker who plays
           -- less than a full-back still ranks above him when he is the
           -- reason the attack rating exists. The weights are a ranking
           -- rule, not a fitted coefficient.
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

comment on view public.team_key_player is 'Current squad ranked by what they have done for this club in the last two seasons. Rank 1-6 is who the team page calls key; the rest are here so a page can show more without a second definition.';

grant select on public.player_season_stat, public.player, public.team_key_player
  to anon, authenticated;
