-- ============================================================
-- Merge the clubs the calendar load duplicated.
--
-- Loading 2026/27 fixtures from API-Football into leagues whose
-- history comes from football-data.co.uk created fifteen new teams.
-- Some are genuinely promoted. Ten are clubs we already held under
-- a different spelling, because the two sources disagree about how
-- much of a name to write: 'Mechelen' against 'KV Mechelen',
-- 'Zwolle' against 'PEC Zwolle'.
--
-- A split identity is the worst outcome available here. It does not
-- fail; it silently halves a club's history, so the model rates the
-- duplicate off no matches at all while the real record sits under
-- the other id. That is what produced a 1X2 probability of zero.
--
-- Re-pointing the alias is also the prevention: seed_teams resolves
-- on the provider's numeric id first, so once the id points at the
-- right club, no later load can duplicate it again.
--
-- Two look like different clubs and are not. Waasland-Beveren was
-- renamed SK Beveren in 2021, and Erzurum BB is the same club as
-- Erzurumspor. Both are merged deliberately rather than by fuzzy
-- match.
--
-- One looks like a match and is not: Académico de Viseu is a
-- different club from Académica de Coimbra, so it stays separate
-- alongside the genuinely promoted Lommel, Amed and Çorum.
-- ============================================================

create temporary table _merge (duplicate_name text, keep_name text) on commit drop;

insert into _merge values
  ('KV Mechelen',          'Mechelen'),
  ('KVC Westerlo',         'Westerlo'),
  ('OH Leuven',            'Oud-Heverlee Leuven'),
  ('SK Beveren',           'Waasland-Beveren'),
  ('ADO Den Haag',         'Den Haag'),
  ('Fortuna Sittard',      'For Sittard'),
  ('PEC Zwolle',           'Zwolle'),
  ('Gaziantep FK',         'Gaziantep'),
  ('Gençlerbirliği S.K.',  'Genclerbirligi'),
  ('Erzurumspor FK',       'Erzurum BB'),
  ('Göztepe',              'Goztep');

create temporary table _pairs on commit drop as
select d.team_id as duplicate_id, k.team_id as keep_id,
       m.duplicate_name, m.keep_name
  from _merge m
  join core.team d on d.canonical_name = m.duplicate_name
  join core.team k on k.canonical_name = m.keep_name
 where d.team_id <> k.team_id;

-- Fixtures first: they are the only thing referencing the duplicates, having
-- been created by the same load.
update core.match m
   set home_team_id = p.keep_id
  from _pairs p
 where m.home_team_id = p.duplicate_id;

update core.match m
   set away_team_id = p.keep_id
  from _pairs p
 where m.away_team_id = p.duplicate_id;

-- Statistic rows exist for the handful of 2026/27 matches already played, which
-- the same load wrote goals for. Both sides of each row have to move: a stat row
-- names its own team and its opponent.
update core.match_team_stat s
   set team_id = p.keep_id
  from _pairs p
 where s.team_id = p.duplicate_id;

update core.match_team_stat s
   set opponent_team_id = p.keep_id
  from _pairs p
 where s.opponent_team_id = p.duplicate_id;

-- The feature layer is derived and will be rebuilt, but the rows have to stop
-- referencing a team that is about to disappear.
delete from features.team_match f
 using _pairs p
 where f.team_id = p.duplicate_id or f.opponent_team_id = p.duplicate_id;

-- Then the alias, which is what stops this happening again.
update core.team_alias ta
   set team_id = p.keep_id
  from _pairs p
 where ta.team_id = p.duplicate_id;

delete from core.team t
 using _pairs p
 where t.team_id = p.duplicate_id;
