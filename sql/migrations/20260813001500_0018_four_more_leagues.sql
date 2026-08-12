-- ============================================================
-- Add the Eredivisie, Belgian Pro League, Liga Portugal and
-- Süper Lig.
--
-- These four were chosen ahead of the rest of the request because
-- football-data.co.uk publishes the same column set for them as for
-- the current five: shots, shots on target, corners, fouls, cards,
-- and Pinnacle closing odds. Every existing model and every market
-- therefore applies unchanged, and the only thing missing against
-- E0 is the referee column — which is already backfilled from FBref
-- for the current leagues and can be for these.
--
-- What is deliberately not here, and why:
--
--   Eliteserien has results and closing odds only, with no shots,
--   corners, fouls or cards, so it can support the goals markets and
--   none of the count markets. It is a different shape of load.
--
--   The Czech and Bulgarian top flights are not published by
--   football-data.co.uk in any file. They need FBref, which means no
--   odds and so no market benchmark.
--
--   The Champions and Europa Leagues are not a loading problem but a
--   modelling one. Attack and defence ratings are centred within a
--   competition, so an English rating and a German rating are not on
--   a common scale and the model cannot price Arsenal against Bayern
--   at all. That needs either a joint fit across leagues or a
--   cross-league rating, and ClubElo — already loaded, 250k rating
--   periods — is the obvious candidate.
--
-- Seasons run 2014/15 to 2026/27 to match the existing five. 2014 is
-- where Understat's xG begins; it is not used by any shipping model,
-- but keeping one history window across all competitions means a
-- backtest never silently compares different spans.
-- ============================================================

insert into core.competition (code, name, country, tier, type) values
  ('NED-ED', 'Eredivisie',          'Netherlands', 1, 'league'),
  ('BEL-PL', 'Belgian Pro League',  'Belgium',     1, 'league'),
  ('POR-PL', 'Liga Portugal',       'Portugal',    1, 'league'),
  ('TUR-SL', 'Süper Lig',           'Turkey',      1, 'league')
on conflict (code) do nothing;

insert into core.season (competition_id, start_year, end_year, label)
select c.competition_id,
       y.start_year,
       y.start_year + 1,
       y.start_year || '/' || right((y.start_year + 1)::text, 2)
  from core.competition c
 cross join generate_series(2014, 2026) as y(start_year)
 where c.code in ('NED-ED', 'BEL-PL', 'POR-PL', 'TUR-SL')
on conflict (competition_id, start_year) do nothing;
