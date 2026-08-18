-- ============================================================
-- Three promoted clubs, split in half on the day they were promoted.
--
--   Dep. A Coruna is Deportivo La Coruna
--   Santander     is Racing Santander
--   Corum         is Çorum FK
--
-- Same failure as the Belgian pair in 0034 and for the same reason:
-- football-data.co.uk and API-Football disagree about the name, each
-- wrote its own club, and each wrote its own copy of the same fixture.
-- Six matches where there should be three.
--
-- What caught it was neither a load error nor a name check. It was
-- `rest_days = 0` in the leakage tests — a team cannot play twice in a
-- day, so a rest of zero says two rows describe one match. That test
-- was written to catch feature bugs and has now found duplicate clubs
-- twice, which is worth more than the check it was written for.
--
-- Each pair is merged rather than deduplicated blindly, because the two
-- halves are not interchangeable. The API-Football row carries events,
-- team sheets and predictions; the football-data row carries the closing
-- odds and nothing else. Keeping either alone loses something, so the
-- odds move across and the emptier row goes.
-- ============================================================

create temporary table _dup_match (keep bigint, drop_ bigint, label text);
insert into _dup_match values
  (22088, 63726, 'Deportivo La Coruna v Elche'),
  (22221, 63724, 'Racing Santander v Villarreal'),
  (57549, 63780, 'Galatasaray v Corum');

create temporary table _dup_team (dup integer, keep integer, label text);
insert into _dup_team values
  (1309,  48, 'Dep. A Coruna -> Deportivo La Coruna'),
  (1354, 338, 'Santander -> Racing Santander'),
  (1307, 977, 'Corum -> Çorum FK');

do $$
declare
  bad integer;
begin
  select count(*) into bad from _dup_match m
   where not exists (select 1 from core.match x where x.match_id = m.keep)
      or not exists (select 1 from core.match x where x.match_id = m.drop_);
  if bad > 0 then
    raise exception '% match ids in the list do not exist', bad;
  end if;

  -- The premise: the row being dropped holds odds and nothing else of value.
  -- If it has grown events or predictions since this was written, stop.
  select count(*) into bad from _dup_match m
   where exists (select 1 from core.match_event e where e.match_id = m.drop_)
      or exists (select 1 from ml.prediction p where p.match_id = m.drop_);
  if bad > 0 then
    raise exception '% rows to be dropped now carry events or predictions', bad;
  end if;

  -- And the pairs must genuinely be the same fixture, not two real matches.
  select count(*) into bad from _dup_match m
    join core.match a on a.match_id = m.keep
    join core.match b on b.match_id = m.drop_
   where a.kickoff_date <> b.kickoff_date
      or a.competition_id <> b.competition_id
      or a.home_goals_ft is distinct from b.home_goals_ft;
  if bad > 0 then
    raise exception '% pairs disagree on date, competition or score', bad;
  end if;
end $$;

-- The odds are the only thing worth rescuing from the row being dropped.
update core.odds o set match_id = m.keep
  from _dup_match m
 where o.match_id = m.drop_
   -- No unique key on this table, so the duplicate guard is spelled out. The
   -- surviving match holds no odds at all today, but a re-run must not double them.
   and not exists (
        select 1 from core.odds x
         where x.match_id = m.keep
           and x.source_id = o.source_id
           and x.bookmaker is not distinct from o.bookmaker
           and x.market is not distinct from o.market
           and x.outcome is not distinct from o.outcome
           and x.line is not distinct from o.line
           and x.snapshot is not distinct from o.snapshot);

-- And its registration, so the next football-data load updates the surviving
-- row rather than recreating the one just deleted.
update core.match_source ms set match_id = m.keep
  from _dup_match m
 where ms.match_id = m.drop_
   and not exists (
        select 1 from core.match_source x
         where x.match_id = m.keep and x.source_id = ms.source_id);

delete from core.odds o using _dup_match m where o.match_id = m.drop_;
delete from core.match_source ms using _dup_match m where ms.match_id = m.drop_;
delete from core.match_team_stat s using _dup_match m where s.match_id = m.drop_;
delete from features.team_match f using _dup_match m where f.match_id = m.drop_;
delete from features.match f using _dup_match m where f.match_id = m.drop_;
delete from core.match x using _dup_match m where x.match_id = m.drop_;

-- Only now can the clubs merge: while both fixtures existed they would have
-- collided on the natural key the moment the teams became one.
update core.match x set home_team_id = g.keep from _dup_team g where x.home_team_id = g.dup;
update core.match x set away_team_id = g.keep from _dup_team g where x.away_team_id = g.dup;

update core.match_team_stat s set team_id = g.keep
  from _dup_team g where s.team_id = g.dup;
update core.match_team_stat s set opponent_team_id = g.keep
  from _dup_team g where s.opponent_team_id = g.dup;

update core.match_event e set team_id = g.keep from _dup_team g where e.team_id = g.dup;
update core.match_lineup l set team_id = g.keep from _dup_team g where l.team_id = g.dup;
update core.match_absence a set team_id = g.keep from _dup_team g where a.team_id = g.dup;

delete from core.squad_member sm using _dup_team g where sm.team_id = g.dup;
delete from core.team_rating r using _dup_team g where r.team_id = g.dup;
delete from features.team_match f using _dup_team g where f.team_id = g.dup;
delete from features.team_match f using _dup_team g where f.opponent_team_id = g.dup;

update core.team_alias a set team_id = g.keep
  from _dup_team g
 where a.team_id = g.dup
   and not exists (
        select 1 from core.team_alias b
         where b.team_id = g.keep
           and b.source_id = a.source_id
           and b.source_team_id is not distinct from a.source_team_id
           and b.alias_name is not distinct from a.alias_name);

delete from core.team_alias a using _dup_team g where a.team_id = g.dup;
delete from core.team t using _dup_team g where t.team_id = g.dup;

drop table _dup_match;
drop table _dup_team;
