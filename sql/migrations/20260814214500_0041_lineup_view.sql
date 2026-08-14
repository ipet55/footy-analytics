-- ============================================================
-- Publish team sheets.
--
-- One row per named player, with the formation and coach repeated on
-- each so a page needs a single request rather than one for the sheet
-- and another for the players.
--
-- The referee comes along too. It is already on core.match, backfilled
-- from FBref for every league, and it is the single most useful fact
-- about a card market that the app has never displayed.
-- ============================================================

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
       p.is_starter
  from core.match_lineup_player p
  join core.match_lineup l on l.match_id = p.match_id and l.team_id = p.team_id
  join core.match m on m.match_id = p.match_id
  join core.team t on t.team_id = p.team_id;

comment on view public.match_lineup is 'Team sheets: the eleven, the bench, the formation and the coach. Formation and coach repeat on every row so one request serves a page.';

grant select on public.match_lineup to anon, authenticated;
