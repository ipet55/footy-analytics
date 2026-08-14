-- ============================================================
-- Remove matches loaded into the wrong competition.
--
-- football-data.co.uk answered the 2026-27 E0 URL with English
-- National League fixtures and the SP1 URL with Portuguese ones.
-- Both are valid CSVs and both parsed cleanly, so twelve National
-- League matches were written into the Premier League and nine
-- Portuguese ones into La Liga, along with the clubs to play them.
--
-- Nothing failed. The only visible symptom was a leakage test
-- noticing that some club had two matches on the same day, which is
-- what happens when Benfica appears in La Liga while also appearing
-- in Liga Portugal.
--
-- Identified by the clubs rather than by the dates: the wrong-league
-- matches are exactly those whose home team has no history in that
-- competition before 2026-27. A real promoted club is caught by the
-- same rule, so the delete is restricted to the two competitions and
-- the one season known to be affected.
--
-- The download step now validates the file's own `Div` column against
-- the division requested, so this cannot recur through that path.
-- ============================================================

create temporary table _wrong on commit drop as
select m.match_id, c.code as competition, t.canonical_name as club
  from core.match m
  join core.competition c using (competition_id)
  join core.season s using (season_id)
  join core.team t on t.team_id = m.home_team_id
 where s.start_year = 2026
   and c.code in ('ENG-PL', 'ESP-LL')
   -- Played only. A scheduled fixture cannot have come from the wrong file, and
   -- without this the rule also catches every legitimately promoted club's
   -- upcoming season — which is what the guard below caught it doing.
   and m.home_goals_ft is not null
   and not exists (
        select 1
          from core.match earlier
          join core.season es on es.season_id = earlier.season_id
         where earlier.competition_id = m.competition_id
           and es.start_year < 2026
           and t.team_id in (earlier.home_team_id, earlier.away_team_id)
       );

do $$
declare n int;
begin
  select count(*) into n from _wrong;
  raise notice 'removing % matches loaded into the wrong competition', n;
  if n > 40 then
    -- 21 are expected. Many more would mean the rule is catching real fixtures.
    raise exception 'refusing to delete % matches; the rule is too broad', n;
  end if;
end $$;

delete from core.match_team_stat s using _wrong w where s.match_id = w.match_id;
delete from core.match_source ms using _wrong w where ms.match_id = w.match_id;
delete from features.team_match f using _wrong w where f.match_id = w.match_id;
delete from features.match f using _wrong w where f.match_id = w.match_id;
delete from ml.prediction p using _wrong w where p.match_id = w.match_id;
delete from core.match m using _wrong w where m.match_id = w.match_id;

-- The clubs those matches invented: English National League sides with no match
-- left anywhere. Portuguese clubs are not touched, because they exist properly in
-- Liga Portugal — only their La Liga fixtures were wrong.
delete from core.team_alias ta
 where ta.team_id in (
        select t.team_id from core.team t
         where t.country = 'England'
           and not exists (
                select 1 from core.match m
                 where t.team_id in (m.home_team_id, m.away_team_id))
       );

delete from core.team t
 where t.country = 'England'
   and not exists (
        select 1 from core.match m
         where t.team_id in (m.home_team_id, m.away_team_id));
