-- ============================================================
-- Merge two more clubs that two sources named differently.
--
-- The Belgian calendar came from API-Football and the results from
-- football-data.co.uk, and they disagree about two names: 'Lommel
-- United' against 'Lommel SK', and 'Waasland-Beveren' against
-- 'Beveren'. Each pair is one club, so each real match was stored
-- twice — once against the calendar's identity and once against the
-- result's — with the same date and the same score.
--
-- Nothing failed. The natural key held, because the two rows had
-- genuinely different away teams as far as the database could tell.
-- The only symptom was a leakage test noticing a club with two
-- matches on one day, which is the third time an identity split has
-- surfaced through a side effect rather than an error.
--
-- The name mapping in teams.py now covers both, so a future load
-- resolves them to one club. This clears what is already stored: the
-- duplicate match is deleted rather than re-pointed, because
-- re-pointing it would collide with the row that is being kept.
-- ============================================================

create temporary table _dupe (keep_id int, drop_id int) on commit drop;

insert into _dupe
select k.team_id, d.team_id
  from core.team k
  join core.team d on d.canonical_name = case k.canonical_name
        when 'Waasland-Beveren' then 'Beveren'
        when 'Lommel United'    then 'Lommel SK'
      end
 where k.canonical_name in ('Waasland-Beveren', 'Lommel United');

do $$
declare n int;
begin
  select count(*) into n from _dupe;
  if n <> 2 then
    raise exception 'expected 2 duplicate pairs, found %', n;
  end if;
end $$;

-- Matches that exist for both identities: the same fixture twice. Keep the one
-- pointing at the surviving club and drop the other.
create temporary table _drop_match on commit drop as
select bad.match_id
  from core.match bad
  join _dupe d on d.drop_id in (bad.home_team_id, bad.away_team_id)
 where exists (
        select 1 from core.match good
         where good.season_id = bad.season_id
           and good.kickoff_date = bad.kickoff_date
           and good.match_id <> bad.match_id
           and (case when bad.home_team_id = d.drop_id then d.keep_id
                     else bad.home_team_id end) = good.home_team_id
           and (case when bad.away_team_id = d.drop_id then d.keep_id
                     else bad.away_team_id end) = good.away_team_id
       );

delete from core.match_team_stat s using _drop_match d where s.match_id = d.match_id;
delete from core.match_source ms using _drop_match d where ms.match_id = d.match_id;
delete from features.team_match f using _drop_match d where f.match_id = d.match_id;
delete from features.match f using _drop_match d where f.match_id = d.match_id;
delete from ml.prediction p using _drop_match d where p.match_id = d.match_id;
delete from core.match m using _drop_match d where m.match_id = d.match_id;

-- Anything the dropped identity still holds is a fixture the surviving one does
-- not have, so re-point rather than delete.
update core.match m set home_team_id = d.keep_id
  from _dupe d where m.home_team_id = d.drop_id;
update core.match m set away_team_id = d.keep_id
  from _dupe d where m.away_team_id = d.drop_id;
update core.match_team_stat s set team_id = d.keep_id
  from _dupe d where s.team_id = d.drop_id;
update core.match_team_stat s set opponent_team_id = d.keep_id
  from _dupe d where s.opponent_team_id = d.drop_id;
delete from features.team_match f using _dupe d
 where f.team_id = d.drop_id or f.opponent_team_id = d.drop_id;
delete from core.team_rating r using _dupe d where r.team_id = d.drop_id;

-- The alias has to move, not be deleted: it is what makes the next load resolve
-- this spelling to the surviving club.
update core.team_alias ta set team_id = d.keep_id
  from _dupe d
 where ta.team_id = d.drop_id
   and not exists (
        select 1 from core.team_alias other
         where other.team_id = d.keep_id
           and other.source_id = ta.source_id
           and other.norm_name = ta.norm_name);
delete from core.team_alias ta using _dupe d where ta.team_id = d.drop_id;

delete from core.team t using _dupe d where t.team_id = d.drop_id;
