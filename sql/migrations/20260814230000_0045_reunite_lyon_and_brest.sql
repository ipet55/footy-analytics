-- ============================================================
-- Two more, found by the coverage figure rather than by matching.
--
--   Lyon              (82 European matches)  is Olympique Lyonnais
--   Stade Brestois 29 (10 European matches)  is Brest
--
-- Both were missed by the fuzzy pass in 0044 and both would be missed
-- by a stricter one: 'Lyon' shares no token with 'Olympique Lyonnais'
-- and 'Stade Brestois 29' shares none with 'Brest'. No threshold finds
-- these, because the two names have almost nothing in common as text.
--
-- What did find them was the thing worth keeping: after 0044 every
-- league linked more than 95% of its fixtures to provider ids except
-- Ligue 1, which linked 239 of 306, and two clubs accounted for 68 of
-- the 67 gaps. Coverage is a better detector than similarity here
-- because it does not care why two records disagree, only that a
-- fixture failed to find its match — which is the actual symptom.
--
-- So the check that stays is the coverage one, in footy freshness. It
-- would have caught 0044 and 0045 without anyone thinking to look.
-- ============================================================

-- core.match_lineup_player references (match_id, team_id) on core.match_lineup, so
-- correcting a lineup's team orphaned its players and the merge failed halfway.
-- Cascade is what the relationship means: if the sheet belongs to a different club
-- than we thought, so do the players on it. 0044 escaped this only because none of
-- its twenty clubs happened to have a sheet loaded yet.
alter table core.match_lineup_player
  drop constraint match_lineup_player_match_id_team_id_fkey,
  add constraint match_lineup_player_match_id_team_id_fkey
    foreign key (match_id, team_id) references core.match_lineup
    on update cascade on delete cascade;

create temporary table _merge (dup integer, keep integer, label text);
insert into _merge values
  (579, 113, 'Lyon -> Olympique Lyonnais'),
  (756,  26, 'Stade Brestois 29 -> Brest');

do $$
declare
  bad integer;
begin
  select count(*) into bad
    from _merge m
   where not exists (select 1 from core.team t where t.team_id = m.dup)
      or not exists (select 1 from core.team t where t.team_id = m.keep);
  if bad > 0 then
    raise exception 'merge list references % missing team ids', bad;
  end if;

  select count(*) into bad
    from _merge m join core.team t on t.team_id = m.dup
   where t.country is not null;
  if bad > 0 then
    raise exception '% duplicates have a country; check the ids', bad;
  end if;

  select count(*) into bad
    from _merge m
    join core.match a on a.home_team_id = m.dup or a.away_team_id = m.dup
    join core.match b
      on b.competition_id = a.competition_id
     and b.season_id = a.season_id
     and b.stage = a.stage
     and ((a.home_team_id = m.dup and b.home_team_id = m.keep
           and b.away_team_id = a.away_team_id)
       or (a.away_team_id = m.dup and b.away_team_id = m.keep
           and b.home_team_id = a.home_team_id));
  if bad > 0 then
    raise exception '% fixtures exist under both identities; dedupe first', bad;
  end if;
end $$;

update core.match m set home_team_id = g.keep from _merge g where m.home_team_id = g.dup;
update core.match m set away_team_id = g.keep from _merge g where m.away_team_id = g.dup;

update core.match_team_stat s set team_id = g.keep
  from _merge g where s.team_id = g.dup;
update core.match_team_stat s set opponent_team_id = g.keep
  from _merge g where s.opponent_team_id = g.dup;

update core.match_event e set team_id = g.keep from _merge g where e.team_id = g.dup;
-- The players follow by cascade, so this is one statement rather than two.
update core.match_lineup l set team_id = g.keep from _merge g where l.team_id = g.dup;

delete from core.team_rating r using _merge g where r.team_id = g.dup;
delete from features.team_match f using _merge g where f.team_id = g.dup;
delete from features.team_match f using _merge g where f.opponent_team_id = g.dup;

update core.team_alias a set team_id = g.keep
  from _merge g
 where a.team_id = g.dup
   and not exists (
        select 1 from core.team_alias b
         where b.team_id = g.keep
           and b.source_id = a.source_id
           and b.source_team_id is not distinct from a.source_team_id
           and b.alias_name is not distinct from a.alias_name);

delete from core.team_alias a using _merge g where a.team_id = g.dup;
delete from core.team t using _merge g where t.team_id = g.dup;

drop table _merge;
