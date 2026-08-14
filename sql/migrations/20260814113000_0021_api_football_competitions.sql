-- ============================================================
-- Add Bulgaria and the two UEFA club competitions.
--
-- These arrive from API-Football rather than football-data.co.uk
-- or FBref, which changes what they can and cannot support.
--
-- Better than FBref on statistics. API-Football's fixture
-- statistics carry corners, which no FBref endpoint exposes per
-- match, so these leagues get the full market set rather than the
-- reduced one the FBref path would have given. They also carry
-- possession, passes and expected goals, which is more than
-- football-data.co.uk publishes for the original five.
--
-- Worse on odds, permanently. API-Football keeps pre-match prices
-- for seven days and has no archive at any tier, so there is no
-- closing line to score these competitions against and no market
-- number to show beside the model. Prices can only be accumulated
-- from now on, by polling.
--
-- Season ranges follow what the provider actually has statistics
-- for, checked rather than assumed: Bulgaria from 2018, the UEFA
-- competitions from 2015. Seeding seasons we know are empty would
-- leave holes that look like failed loads.
--
-- The UEFA competitions are typed 'cup', which keeps them out of
-- public.competition — that view selects leagues only. They are not
-- servable yet regardless: attack and defence are centred within a
-- competition, so an English rating and a German one are not on a
-- common scale and no fixture between them can be priced until a
-- cross-league rating exists.
-- ============================================================

insert into core.competition (code, name, country, tier, type) values
  ('BUL-1L',  'First League',           'Bulgaria', 1,    'league'),
  ('INT-UCL', 'UEFA Champions League',  null,       null, 'cup'),
  ('INT-UEL', 'UEFA Europa League',     null,       null, 'cup')
on conflict (code) do nothing;

insert into core.season (competition_id, start_year, end_year, label)
select c.competition_id, y.start_year, y.start_year + 1,
       y.start_year || '/' || right((y.start_year + 1)::text, 2)
  from core.competition c
 cross join generate_series(2018, 2026) as y(start_year)
 where c.code = 'BUL-1L'
on conflict (competition_id, start_year) do nothing;

insert into core.season (competition_id, start_year, end_year, label)
select c.competition_id, y.start_year, y.start_year + 1,
       y.start_year || '/' || right((y.start_year + 1)::text, 2)
  from core.competition c
 cross join generate_series(2015, 2026) as y(start_year)
 where c.code in ('INT-UCL', 'INT-UEL')
on conflict (competition_id, start_year) do nothing;
