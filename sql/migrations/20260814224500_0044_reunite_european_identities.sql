-- ============================================================
-- Twenty clubs whose European history was under a second identity.
--
-- Found by trying to link Premier League fixtures to their provider
-- ids and getting 210 of 380. Every club had an alias, so the failure
-- was not the naming — the alias pointed at 'Newcastle', and the
-- Premier League matches belong to 'Newcastle United'. Two clubs, one
-- team, created months apart by two loaders.
--
-- 723 matches move. Barcelona's 115 European appearances, Tottenham's
-- 93, Sevilla's 102, all of them detached from the league record that
-- explains them. Anything computed across competitions — a rating for a
-- Champions League tie, most obviously — was reading a club with no
-- domestic history against one with no European history and pricing
-- both as unknowns.
--
-- The list is hand-checked, not generated, and that is the point of
-- this migration. Fuzzy matching found 28 candidates at 0.80 or better
-- and 8 of them were different clubs entirely:
--
--   Rangers          is not Queens Park Rangers
--   Arsenal Tula     is not Arsenal
--   Cardiff MET      is not Cardiff City
--   Dinamo Brest     is not Brest
--   Aris             is not Artis
--   Atlantas         is not Atalanta
--   Spartak Trnava   is not Spartak Varna
--   Zilina           is not Zlin
--
-- Four of those scored a perfect 1.00, because the score rewards one
-- name being a subset of the other and 'Rangers' is a subset of 'Queens
-- Park Rangers'. That heuristic is fine for choosing between the twenty
-- clubs in one league, which is what it was written for. It is not fit
-- to decide identity across four thousand, and merging on it would have
-- given Queens Park Rangers a Champions League record.
--
-- Bohemians is excluded as well, for honest uncertainty rather than a
-- known mismatch: the European entry could be Bohemian FC of Dublin
-- rather than Bohemians 1905 of Prague, and one match is not worth
-- guessing over.
-- ============================================================

create temporary table _merge (dup integer, keep integer, label text);
insert into _merge values
  (960,  27, 'Brighton -> Brighton & Hove Albion'),
  (937,  64, 'Getafe -> Getafe CF'),
  (879,  60, 'SC Freiburg -> Freiburg'),
  (878,  57, '1. FC Koln -> FC Koln'),
  (873,  94, 'FSV Mainz 05 -> Mainz 05'),
  (833, 168, 'West Ham -> West Ham United'),
  (812,  15, 'FC Augsburg -> Augsburg'),
  (761,  66, 'Girona -> Girona FC'),
  (747, 106, 'Newcastle -> Newcastle United'),
  (700, 112, 'Marseille -> Olympique de Marseille'),
  (685,  80, 'Inter -> Inter Milan'),
  (675, 137, 'FC Schalke 04 -> Schalke 04'),
  (660,  75, '1899 Hoffenheim -> Hoffenheim'),
  (647, 164, 'Villarreal -> Villarreal CF'),
  (636,  87, 'Leicester -> Leicester City'),
  (634, 152, 'Tottenham -> Tottenham Hotspur'),
  (625, 159, 'Valencia -> Valencia CF'),
  (614,  56, 'Barcelona -> FC Barcelona'),
  (587, 140, 'Sevilla -> Sevilla FC'),
  (932, 169, 'Wolves -> Wolverhampton Wanderers');

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

  -- A club that kept a country was never one of the UEFA-load orphans, so a
  -- non-null country on the duplicate means the id is wrong and this would merge
  -- two real clubs.
  select count(*) into bad
    from _merge m join core.team t on t.team_id = m.dup
   where t.country is not null;
  if bad > 0 then
    raise exception '% duplicates have a country; check the ids', bad;
  end if;

  -- Verified as zero before writing this, and asserted because it is the one
  -- failure that would violate the natural key halfway through.
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

-- Matches first. Everything below hangs off them.
update core.match m set home_team_id = g.keep from _merge g where m.home_team_id = g.dup;
update core.match m set away_team_id = g.keep from _merge g where m.away_team_id = g.dup;

update core.match_team_stat s set team_id = g.keep
  from _merge g where s.team_id = g.dup;
update core.match_team_stat s set opponent_team_id = g.keep
  from _merge g where s.opponent_team_id = g.dup;

update core.match_event e set team_id = g.keep from _merge g where e.team_id = g.dup;
update core.match_lineup l set team_id = g.keep from _merge g where l.team_id = g.dup;
update core.match_lineup_player p set team_id = g.keep
  from _merge g where p.team_id = g.dup;

-- Ratings are keyed by (team, date) and both identities may hold a row for the
-- same day, so the duplicate's are dropped rather than moved. They are derived
-- and the next build recomputes them from the reunited history, which is the
-- point of the exercise.
delete from core.team_rating r using _merge g where r.team_id = g.dup;

-- Features likewise: derived, and stale the moment a match changes hands.
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
