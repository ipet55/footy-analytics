-- ============================================================
-- Badges, flags and clickable players.
--
-- The app has names for clubs, leagues and footballers, and nothing
-- that lets a reader recognise them at a glance. API-Football already
-- numbers every club we cover, and its CDN serves a badge at a URL
-- derived from that number. No new load is needed: the alias we store
-- to join fixtures is the same id the image is keyed on.
--
-- Player photographs are already on core.player.photo_url. They were
-- never selected on the views a match page reads, so the pictures
-- existed in the database and could not be shown. The same is true of
-- player_id on the lineup and the expected eleven, which is why a
-- name on those lists could not become a link.
--
-- Country is already on core.competition. Putting it on the fixture
-- lets a flag sit next to the league name without a second request.
-- ============================================================

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
         select 1
           from ml.prediction p
           join ml.market_competition mc on mc.market_code = p.market_code
                                        and mc.competition_id = m.competition_id
          where p.match_id = m.match_id and mc.status = 'shipping'
       ) as has_predictions,
       r.canonical_name as referee,
       c.country as competition_country,
       (
         select 'https://media.api-sports.io/football/teams/'
                || ta.source_team_id || '.png'
           from core.team_alias ta
           join core.source src on src.source_id = ta.source_id
                               and src.code = 'api_football'
          where ta.team_id = h.team_id
            and ta.source_team_id is not null
          limit 1
       ) as home_logo_url,
       (
         select 'https://media.api-sports.io/football/teams/'
                || ta.source_team_id || '.png'
           from core.team_alias ta
           join core.source src on src.source_id = ta.source_id
                               and src.code = 'api_football'
          where ta.team_id = a.team_id
            and ta.source_team_id is not null
          limit 1
       ) as away_logo_url
  from core.match m
  join core.competition c on c.competition_id = m.competition_id
  join core.season s on s.season_id = m.season_id
  join core.team h on h.team_id = m.home_team_id
  join core.team a on a.team_id = m.away_team_id
  left join core.referee r on r.referee_id = m.referee_id;

comment on view public.fixture is 'One row per match, with names, the league country, and club badges where the provider has numbered the club.';

grant select on public.fixture to anon, authenticated;

-- public.team is materialised. Adding a column means dropping it;
-- nothing else is built on it, so the unique index is the only thing
-- that has to come back with it.
drop materialized view if exists public.team;

create materialized view public.team as
select t.team_id,
       t.canonical_name as team,
       coalesce(t.short_name, t.canonical_name) as team_short,
       t.country,
       (
         select 'https://media.api-sports.io/football/teams/'
                || ta.source_team_id || '.png'
           from core.team_alias ta
           join core.source src on src.source_id = ta.source_id
                               and src.code = 'api_football'
          where ta.team_id = t.team_id
            and ta.source_team_id is not null
          limit 1
       ) as logo_url,
       count(*) as matches,
       max(s.label) as latest_season,
       max(s.start_year) as latest_start_year,
       array_agg(distinct c.code order by c.code) as competitions
  from core.team t
  join core.match m on m.home_team_id = t.team_id or m.away_team_id = t.team_id
  join core.competition c on c.competition_id = m.competition_id
  join core.season s on s.season_id = m.season_id
 where m.home_goals_ft is not null
 group by t.team_id, t.canonical_name, t.short_name, t.country;

create unique index team_key on public.team (team_id);
create index team_name_idx on public.team (team);

comment on materialized view public.team is 'Every team with at least one played match, with a badge where the provider has numbered the club. Refreshed by footy build-features.';

grant select on public.team to anon, authenticated;

create or replace view public.match_absence as
select a.match_id,
       a.team_id,
       t.canonical_name as team,
       a.team_id = m.home_team_id as is_home,
       a.player_name,
       a.status,
       a.reason,
       p.photo_url,
       a.player_id
  from core.match_absence a
  join core.match m using (match_id)
  join core.team t on t.team_id = a.team_id
  left join core.player p on p.player_id = a.player_id;

comment on view public.match_absence is 'Who misses a given match and why. status is out or doubtful, and reason is the provider''s own words rather than a bucket of ours.';

grant select on public.match_absence to anon, authenticated;

create or replace view public.match_lineup as
select p.match_id,
       p.team_id,
       t.canonical_name as team,
       p.team_id = m.home_team_id as is_home,
       l.formation,
       l.coach_name,
       p.player_name,
       p.shirt_number,
       p.position,
       p.is_starter,
       p.player_id,
       pl.photo_url
  from core.match_lineup_player p
  join core.match_lineup l on l.match_id = p.match_id and l.team_id = p.team_id
  join core.match m on m.match_id = p.match_id
  join core.team t on t.team_id = p.team_id
  left join core.player pl on pl.player_id = p.player_id;

comment on view public.match_lineup is 'Team sheets: the eleven, the bench, the formation and the coach. player_id and photo_url are null when the name could not be resolved.';

grant select on public.match_lineup to anon, authenticated;

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

comment on view public.expected_xi is 'Who is likeliest to start, from the last ten team sheets minus anyone reported out. A guess, useful only until the confirmed sheet appears about an hour before kickoff.';

grant select on public.expected_xi to anon, authenticated;
