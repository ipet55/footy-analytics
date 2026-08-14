-- ============================================================
-- Add the Czech First League and Eliteserien.
--
-- Unlike the nine already here, these come from FBref rather than
-- football-data.co.uk, which has consequences worth recording
-- next to the rows themselves rather than in a document.
--
-- No odds. football-data.co.uk carries Eliteserien results and
-- closing prices but no match statistics, and does not carry the
-- Czech league at all. So these two leagues cannot be compared
-- against a bookmaker, and the app's "model against the market"
-- framing has no market to show for them.
--
-- No corners. FBref's per-match team endpoint offers schedule,
-- shooting, keeper and misc, which between them give goals, shots,
-- shots on target, fouls, cards, offsides and crosses — but corner
-- kicks appear only in season aggregates. Corners per team is one
-- of the shipped markets, so these leagues support strictly less
-- than the other nine.
--
-- Eliteserien runs March to December, so a season is one calendar
-- year and end_year equals start_year. Every other competition here
-- spans two. Labels differ to match: '2024' rather than '2024/25'.
-- ============================================================

insert into core.competition (code, name, country, tier, type) values
  ('CZE-1L', 'Czech First League', 'Czechia', 1, 'league'),
  ('NOR-EL', 'Eliteserien',        'Norway',  1, 'league')
on conflict (code) do nothing;

-- Czech: August to May, like the rest.
insert into core.season (competition_id, start_year, end_year, label)
select c.competition_id, y.start_year, y.start_year + 1,
       y.start_year || '/' || right((y.start_year + 1)::text, 2)
  from core.competition c
 cross join generate_series(2014, 2026) as y(start_year)
 where c.code = 'CZE-1L'
on conflict (competition_id, start_year) do nothing;

-- Norway: a season is a calendar year.
insert into core.season (competition_id, start_year, end_year, label)
select c.competition_id, y.start_year, y.start_year, y.start_year::text
  from core.competition c
 cross join generate_series(2014, 2026) as y(start_year)
 where c.code = 'NOR-EL'
on conflict (competition_id, start_year) do nothing;
