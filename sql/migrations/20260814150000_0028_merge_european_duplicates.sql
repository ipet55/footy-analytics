-- ============================================================
-- Merge the clubs the UEFA load duplicated into their domestic selves.
--
-- Loading the Champions and Europa Leagues created 394 clubs with no
-- country, which is what the loader writes when a competition spans
-- them. Most are genuinely new to us — European football has a long
-- tail. Ten are not: they are clubs we already held, under the name
-- UEFA uses rather than the one football-data.co.uk does. 'FC Porto'
-- against 'Porto'. 'SC Braga' against 'Sp Braga'. 'Başakşehir'
-- against 'Buyuksehyr'.
--
-- They mattered because the 2026/27 calendar load then resolved on
-- the provider's numeric id, found the alias the UEFA load had made,
-- and attached a whole domestic season to the near-empty identity.
-- Porto's 408 matches sat under one id while its fixtures pointed at
-- another with a handful.
--
-- The visible symptom was a goals model with parameters pinned at
-- the optimiser's bound: attack of -3.00 for Vitória SC, which
-- prices a real club at essentially no chance of scoring. A club
-- with one match carries almost no weight after time decay, so its
-- parameter is barely constrained by data and drifts until it hits
-- the bound. Portugal published 'over 2.5 away goals' at 0.0036%.
--
-- Merged by id rather than by name. The names are exactly what is
-- unreliable here, and a fuzzy match proposed 'Portimonense' for
-- Sporting CP and 'Santa Clara' for Vitória SC. Both would have been
-- silent and wrong.
--
-- The remaining 384 have no domestic fixtures and touch only the two
-- UEFA competitions, which publish nothing. Left alone deliberately:
-- merging them needs the same care per club, and none of them is
-- currently affecting a served number.
-- ============================================================

create temporary table _pairs (duplicate_id int, keep_id int) on commit drop;

insert into _pairs values
  (612, 375),  -- Club Brugge KV      -> Club Brugge
  (682, 391),  -- Standard Liege      -> Standard
  (728, 392),  -- Union St. Gilloise  -> St. Gilloise
  (901, 395),  -- Zulte Waregem       -> Waregem
  (771, 357),  -- NEC Nijmegen        -> Nijmegen
  (618, 420),  -- FC Porto            -> Porto
  (620, 425),  -- Sporting CP         -> Sp Lisbon
  (736, 424),  -- SC Braga            -> Sp Braga
  (830, 413),  -- Vitória SC          -> Guimaraes
  (668, 440);  -- Başakşehir          -> Buyuksehyr

-- Guard against a typo in the list above turning into silent data loss.
do $$
declare bad int;
begin
  select count(*) into bad
    from _pairs p
   where not exists (select 1 from core.team t where t.team_id = p.duplicate_id)
      or not exists (select 1 from core.team t where t.team_id = p.keep_id);
  if bad > 0 then
    raise exception 'merge list references % missing team ids', bad;
  end if;
end $$;

-- A fixture the duplicate already shares with its own target would collide on
-- the natural key. There are none today; refuse rather than lose one if that
-- ever changes.
do $$
declare clashes int;
begin
  select count(*) into clashes
    from core.match a
    join _pairs p on a.home_team_id = p.duplicate_id
    join core.match b on b.season_id = a.season_id
                     and b.home_team_id = p.keep_id
                     and b.away_team_id = a.away_team_id
                     and b.stage = a.stage;
  if clashes > 0 then
    raise exception 'merging would collide on % existing fixtures', clashes;
  end if;
end $$;

update core.match m set home_team_id = p.keep_id
  from _pairs p where m.home_team_id = p.duplicate_id;

update core.match m set away_team_id = p.keep_id
  from _pairs p where m.away_team_id = p.duplicate_id;

update core.match_team_stat s set team_id = p.keep_id
  from _pairs p where s.team_id = p.duplicate_id;

update core.match_team_stat s set opponent_team_id = p.keep_id
  from _pairs p where s.opponent_team_id = p.duplicate_id;

delete from features.team_match f
 using _pairs p
 where f.team_id = p.duplicate_id or f.opponent_team_id = p.duplicate_id;

delete from core.team_rating r using _pairs p where r.team_id = p.duplicate_id;

update core.team_alias ta set team_id = p.keep_id
  from _pairs p where ta.team_id = p.duplicate_id;

delete from core.team t using _pairs p where t.team_id = p.duplicate_id;
