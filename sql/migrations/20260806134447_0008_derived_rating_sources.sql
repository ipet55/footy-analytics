-- ============================================================
-- Ratings we compute ourselves from results already in the
-- database, rather than fetch.
--
-- Two advantages over an external feed. The parameters (K factor,
-- home advantage, between-season regression) become things the
-- model can tune and score, instead of constants somebody else
-- chose. And there is no API to be rate limited by.
--
-- The limitation: these ratings only see the five domestic
-- leagues, so they cannot compare a Premier League side to a
-- La Liga side. That only matters for cross-league fixtures,
-- which is what the clubelo ratings are kept for.
-- ============================================================

-- A source that is computed rather than ingested is a genuinely
-- different kind, so record it as one.
alter table core.source drop constraint source_kind_check;
alter table core.source add constraint source_kind_check
  check (kind = any (array['csv', 'api', 'scrape', 'dataset', 'rss', 'derived']));

comment on column core.source.kind is 'How the data arrives. "derived" means computed from data already in this database rather than fetched from anywhere.';

insert into core.source (code, name, kind, notes) values
  ('elo_goals', 'Derived Elo (goals)', 'derived',
   'Elo computed from full-time results in core.match. Goal-difference weighted K factor, home advantage, regression to the mean between seasons.'),
  ('elo_xg', 'Derived Elo (expected goals)', 'derived',
   'Same algorithm as elo_goals but driven by expected goals rather than goals. Should react faster to genuine changes in team quality because it is not waiting on finishing variance.')
on conflict (code) do update
  set name = excluded.name, kind = excluded.kind, notes = excluded.notes;
