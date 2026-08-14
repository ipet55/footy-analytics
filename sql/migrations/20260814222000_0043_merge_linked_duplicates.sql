-- ============================================================
-- Two more duplicate clubs, caught before they cost anything.
--
-- Linking the 2025-26 calendars created five clubs. Three are real —
-- Torreense, RFC Liège and Patro Eisden are genuinely new to these
-- competitions. Two are the same club under a different spelling:
--
--   FC Volendam      is Volendam
--   Fatih Karagümrük is Karagumruk
--
-- Both were caught with zero matches attached, which is the whole
-- difference between this migration and 0027 and 0028. Those two ran
-- after the duplicates had already collected fixtures and statistics,
-- so they had to move rows out of five tables and dodge fixture
-- collisions. This one re-points an alias and deletes an empty row.
--
-- The names also go into teams.py, so the next load resolves them
-- instead of creating the same pair again. A merge that does not fix
-- the cause is a chore that repeats every season.
-- ============================================================

create temporary table _merge (dup integer, keep integer, label text);
insert into _merge values
  (1273, 365, 'FC Volendam -> Volendam'),
  (1275, 456, 'Fatih Karagümrük -> Karagumruk');

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

  -- The premise of the cheap path. If a duplicate has acquired matches then
  -- this migration is the wrong tool and 0028 is the pattern to copy.
  select count(*) into bad
    from _merge m
    join core.match x on x.home_team_id = m.dup or x.away_team_id = m.dup;
  if bad > 0 then
    raise exception '% matches already attached to a duplicate; merge properly', bad;
  end if;
end $$;

-- Point the provider's id at the club that owns the history.
update core.team_alias a
   set team_id = m.keep
  from _merge m
 where a.team_id = m.dup
   and not exists (
        select 1 from core.team_alias b
         where b.team_id = m.keep
           and b.source_id = a.source_id
           and b.source_team_id is not distinct from a.source_team_id);

delete from core.team_alias a using _merge m where a.team_id = m.dup;
delete from core.team t using _merge m where t.team_id = m.dup;

drop table _merge;
