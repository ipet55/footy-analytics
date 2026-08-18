-- ============================================================
-- Collapse republished transfers, and publish the rest.
--
-- The source function now treats reports of the same move within a
-- fortnight as one, up from a week. A week caught Bruno Guimarães being
-- announced on consecutive days and missed Illan Meslier's free
-- transfer, reported on 29 June and again on 8 July. Rows already
-- stored under the old rule are collapsed here.
--
-- Safe because the key includes both clubs and the direction: for this
-- to merge two real events, a player would have to move from one named
-- club to another, the same way round, twice inside two weeks. Going
-- out on loan and returning is the opposite direction and survives.
--
-- public.transfer is written from the club's point of view rather than
-- the player's, because that is how it is read — a team page wants ins
-- and outs, not a list of edges. One row per club per move, so a
-- transfer between two clubs we hold appears once for each, correctly.
-- ============================================================

with ranked as (
    select transfer_id,
           row_number() over (
               partition by player_id, from_name, to_name,
                            -- Fortnightly buckets. Crude next to comparing every
                            -- pair, and enough: reports of one move land days
                            -- apart, not on a boundary either side of one.
                            (moved_on - date '2000-01-01') / 14
               order by moved_on desc
           ) as n
      from core.transfer
)
delete from core.transfer t
 using ranked r
 where t.transfer_id = r.transfer_id and r.n > 1;

create or replace view public.transfer as
select side.team_id,
       t.transfer_id,
       t.player_id,
       p.canonical_name as player_name,
       p.photo_url,
       t.moved_on,
       side.direction,
       -- The other club, whichever side we are looking from. Named rather than
       -- joined, because most moves involve clubs outside these competitions.
       case when side.direction = 'in' then t.from_name else t.to_name end as other_club,
       case when side.direction = 'in' then t.from_team_id else t.to_team_id end
         as other_team_id,
       t.kind
  from core.transfer t
  join core.player p on p.player_id = t.player_id
 cross join lateral (values
        (t.to_team_id,   'in'),
        (t.from_team_id, 'out')
   ) as side(team_id, direction)
 where side.team_id is not null;

comment on view public.transfer is 'Moves from a club''s point of view: one row per club per transfer, so a move between two clubs we hold appears once for each. The other club is a name rather than a join, because most of them play outside these competitions.';

grant select on public.transfer to anon, authenticated;
