-- ============================================================
-- Bookmaker registry.
--
-- football-data.co.uk publishes two kinds of price: real bookmaker
-- quotes, and its own consensus (average / maximum across ~20 books).
-- Both are valuable, but averaging them together is wrong - the
-- 'maximum' row is by construction the best price and would drag any
-- average upward. Classifying them here means a view can exclude
-- aggregates with a join instead of every query remembering to.
-- ============================================================
create table core.bookmaker (
  bookmaker    text primary key,
  display_name text not null,
  kind         text not null check (kind in ('sportsbook','exchange','aggregate')),
  is_sharp     boolean not null default false,
  notes        text
);

insert into core.bookmaker (bookmaker, display_name, kind, is_sharp, notes) values
  ('Pinnacle',           'Pinnacle',            'sportsbook', true,  'Low margin, high limits, accepts winners. Its closing line is the reference market estimate and is present for all 12 seasons.'),
  ('Betfair Exchange',   'Betfair Exchange',    'exchange',   true,  'Peer-to-peer. Prices are pre-commission, so effective return is ~2-5% lower.'),
  ('Bet365',             'Bet365',              'sportsbook', false, null),
  ('bwin',               'bwin',                'sportsbook', false, null),
  ('William Hill',       'William Hill',        'sportsbook', false, null),
  ('VC Bet',             'VC Bet',              'sportsbook', false, 'Rebranded to BetVictor; the VC* columns stop after 2023/24.'),
  ('Interwetten',        'Interwetten',         'sportsbook', false, null),
  ('Ladbrokes',          'Ladbrokes',           'sportsbook', false, null),
  ('Stan James',         'Stan James',          'sportsbook', false, 'Only 2014/15.'),
  ('Betfair Sportsbook', 'Betfair Sportsbook',  'sportsbook', false, 'Column prefix changed from BF* to BFD* in 2025/26.'),
  ('1xBet',              '1xBet',               'sportsbook', false, null),
  ('BetMGM',             'BetMGM',              'sportsbook', false, null),
  ('BetVictor',          'BetVictor',           'sportsbook', false, null),
  ('Coolbet',            'Coolbet',             'sportsbook', false, null),
  ('_average',           'Market average',      'aggregate',  false, 'Provider-computed mean across every book it tracks (~20). Wider and more stable than an average over the books we parse individually.'),
  ('_maximum',           'Best available price','aggregate',  false, 'Provider-computed max across every book it tracks. Use for expected-value calculations, never for probability estimation.');

alter table core.odds
  add constraint odds_bookmaker_fk foreign key (bookmaker) references core.bookmaker;

comment on table core.bookmaker is 'Classifies every price source. kind=aggregate rows are provider-computed summaries, not quotes, and must be excluded from any average over books.';

-- ============================================================
-- The 1X2 market, one row per (match, snapshot).
--
-- Replaces the earlier version, which averaged over whatever
-- bookmakers happened to be in the file - that made the consensus
-- silently change character in 2019/20 when the set of books shifted.
-- This version prefers the provider's own wide consensus and falls
-- back to computing one, recording which it used.
-- ============================================================
drop view if exists core.market_1x2;

create view core.market_1x2 as
with real_books as (
  select o.match_id, o.snapshot,
         count(distinct o.bookmaker)                as book_count,
         avg(o.price) filter (where o.outcome = 'H') as avg_h,
         avg(o.price) filter (where o.outcome = 'D') as avg_d,
         avg(o.price) filter (where o.outcome = 'A') as avg_a,
         max(o.price) filter (where o.outcome = 'H') as max_h,
         max(o.price) filter (where o.outcome = 'D') as max_d,
         max(o.price) filter (where o.outcome = 'A') as max_a,
         stddev_samp(o.price) filter (where o.outcome = 'H') as sd_h
    from core.odds o
    join core.bookmaker b on b.bookmaker = o.bookmaker
   where o.market = '1X2' and b.kind <> 'aggregate'
   group by o.match_id, o.snapshot
),
named as (
  select match_id, snapshot,
         max(price) filter (where bookmaker = '_average'  and outcome = 'H') as site_avg_h,
         max(price) filter (where bookmaker = '_average'  and outcome = 'D') as site_avg_d,
         max(price) filter (where bookmaker = '_average'  and outcome = 'A') as site_avg_a,
         max(price) filter (where bookmaker = '_maximum'  and outcome = 'H') as site_max_h,
         max(price) filter (where bookmaker = '_maximum'  and outcome = 'D') as site_max_d,
         max(price) filter (where bookmaker = '_maximum'  and outcome = 'A') as site_max_a,
         max(price) filter (where bookmaker = 'Pinnacle'  and outcome = 'H') as pin_h,
         max(price) filter (where bookmaker = 'Pinnacle'  and outcome = 'D') as pin_d,
         max(price) filter (where bookmaker = 'Pinnacle'  and outcome = 'A') as pin_a
    from core.odds
   where market = '1X2'
   group by match_id, snapshot
),
joined as (
  select coalesce(r.match_id, n.match_id) as match_id,
         coalesce(r.snapshot, n.snapshot) as snapshot,
         coalesce(r.book_count, 0)        as book_count,
         r.sd_h                           as spread_home,
         case when n.site_avg_h is not null then 'site_average' else 'computed' end as consensus_source,
         coalesce(n.site_avg_h, r.avg_h)  as cons_h,
         coalesce(n.site_avg_d, r.avg_d)  as cons_d,
         coalesce(n.site_avg_a, r.avg_a)  as cons_a,
         coalesce(n.site_max_h, r.max_h)  as best_h,
         coalesce(n.site_max_d, r.max_d)  as best_d,
         coalesce(n.site_max_a, r.max_a)  as best_a,
         n.pin_h, n.pin_d, n.pin_a
    from real_books r
    full join named n on n.match_id = r.match_id and n.snapshot = r.snapshot
)
select match_id,
       snapshot,
       book_count,
       consensus_source,
       round(cons_h::numeric, 3) as consensus_home,
       round(cons_d::numeric, 3) as consensus_draw,
       round(cons_a::numeric, 3) as consensus_away,
       round(best_h::numeric, 3) as best_home,
       round(best_d::numeric, 3) as best_draw,
       round(best_a::numeric, 3) as best_away,
       pin_h as pinnacle_home,
       pin_d as pinnacle_draw,
       pin_a as pinnacle_away,
       round(spread_home::numeric, 4) as spread_home,
       round((1/cons_h + 1/cons_d + 1/cons_a)::numeric, 4) as overround,
       round(((1/cons_h) / (1/cons_h + 1/cons_d + 1/cons_a))::numeric, 5) as p_home,
       round(((1/cons_d) / (1/cons_h + 1/cons_d + 1/cons_a))::numeric, 5) as p_draw,
       round(((1/cons_a) / (1/cons_h + 1/cons_d + 1/cons_a))::numeric, 5) as p_away
  from joined
 where cons_h is not null and cons_d is not null and cons_a is not null;

comment on view core.market_1x2 is 'One row per (match, snapshot). p_home/p_draw/p_away are de-vigged by proportional normalisation - adequate as a baseline, though it slightly understates the draw. Swap in Shin de-vigging later if draw calibration matters. best_* is the highest price available and is what expected value must be computed against, not the consensus.';

-- ============================================================
-- Over/Under 2.5 goals - the second most liquid market and the
-- natural target for a Poisson goal model.
-- ============================================================
create view core.market_ou25 as
with p as (
  select match_id, snapshot,
         max(price) filter (where bookmaker = '_average' and outcome = 'Over')  as avg_over,
         max(price) filter (where bookmaker = '_average' and outcome = 'Under') as avg_under,
         max(price) filter (where bookmaker = '_maximum' and outcome = 'Over')  as best_over,
         max(price) filter (where bookmaker = '_maximum' and outcome = 'Under') as best_under,
         max(price) filter (where bookmaker = 'Pinnacle' and outcome = 'Over')  as pin_over,
         max(price) filter (where bookmaker = 'Pinnacle' and outcome = 'Under') as pin_under
    from core.odds
   where market = 'OU' and line = 2.5
   group by match_id, snapshot
)
select match_id, snapshot,
       avg_over as consensus_over, avg_under as consensus_under,
       best_over, best_under,
       pin_over as pinnacle_over, pin_under as pinnacle_under,
       round((1/coalesce(avg_over, pin_over) + 1/coalesce(avg_under, pin_under))::numeric, 4) as overround,
       round(((1/coalesce(avg_over, pin_over)) /
              (1/coalesce(avg_over, pin_over) + 1/coalesce(avg_under, pin_under)))::numeric, 5) as p_over
  from p
 where coalesce(avg_over, pin_over) is not null
   and coalesce(avg_under, pin_under) is not null;

-- ============================================================
-- Correct the coverage table: verified against the 60 downloaded
-- files, football-data.co.uk carries no offsides or woodwork data
-- in the 2014+ era, and no possession or passes at all.
-- ============================================================
delete from core.stat_coverage
 where source_id = (select source_id from core.source where code = 'football_data_uk')
   and stat_column = 'shots_woodwork';

update core.stat_coverage
   set from_season = 2014,
       note = note || ' | verified present in all 12 seasons 2014/15-2025/26'
 where source_id = (select source_id from core.source where code = 'football_data_uk');

insert into core.stat_coverage (source_id, stat_column, from_season, note)
select s.source_id, v.col, 2014, v.note
  from (values
    ('fouls_drawn', 'derived: equals the opponent HF/AF value, exact not estimated'),
    ('goals',       'FTHG/FTAG, plus 1H/2H split from HTHG/HTAG')
  ) as v(col, note)
  join core.source s on s.code = 'football_data_uk'
 on conflict (source_id, stat_column) do nothing;
