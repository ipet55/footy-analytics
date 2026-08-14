-- ============================================================
-- Decide publication per competition, not once for all of them.
--
-- ml.market.status carried one verdict per market for every
-- competition. That was true enough while there were five leagues
-- validated together, and became wrong the moment there were
-- fourteen: shipping per-team shots globally would have published
-- Portugal at 9.3% and Turkey at 8.2% reliability error, both worse
-- than the errors that keep cards unpublished. Eight competitions
-- have been sitting loaded and measured but unshowable because the
-- registry could not say "yes here, not there".
--
-- ml.market keeps the market definition and a headline status,
-- which stays useful as a summary. ml.market_competition holds the
-- decision that the views actually enforce.
--
-- The default is deliberately restrictive. A missing row means not
-- published, so a newly added competition shows nothing until
-- somebody measures it, rather than inheriting a verdict earned on
-- different data.
--
-- Seeding is by measured evidence only:
--
--   The original five keep exactly what they had. Their evidence is
--   where the global verdicts came from, so this is a no-op for
--   them by construction — the app serves the same markets after
--   this migration as before.
--
--   Netherlands, Portugal and Turkey ship 1X2, because they close
--   81%, 84% and 71% of the base-rate-to-market gap against real
--   closing odds, which is inside the 76-84% the established five
--   manage. They ship fouls totals, positive in all three with
--   reliability of 7.5%, 3.6% and 5.6%. Per-team corners and shots
--   are taken one league at a time on their own calibration.
--
--   Belgium ships 1X2 on the same basis, closing 79%.
--
--   Bulgaria, the Czech league and Eliteserien ship nothing. The
--   goals model transfers well, at 6.7-9.7% over a base rate, but
--   there are no odds to check it against and no calibration
--   measured, and their count markets rest on 315 to 704 matches.
--
--   The UEFA competitions ship nothing and cannot: attack and
--   defence are centred within a competition, so no fixture between
--   clubs from different leagues can be priced at all yet.
-- ============================================================

create table ml.market_competition (
  market_code    text     not null references ml.market,
  competition_id smallint not null references core.competition,
  status         text     not null,
  notes          text,
  decided_at     timestamptz not null default now(),
  primary key (market_code, competition_id),
  constraint market_competition_status_check
    check (status = any (array['shipping', 'held', 'rejected']))
);

comment on table ml.market_competition is 'Whether a market may be published in one competition. Absence means no: a competition shows nothing until its own evidence exists, rather than inheriting a verdict earned elsewhere.';
comment on column ml.market_competition.status is 'shipping = validated walk-forward in this competition. held = ranks fixtures but the percentages are not publishable here. rejected = measured here and found to carry nothing.';

-- The original five: preserve today's behaviour exactly.
insert into ml.market_competition (market_code, competition_id, status, notes)
select m.market_code, c.competition_id, m.status,
       'Inherited from the global verdict, which was measured on these five.'
  from ml.market m
 cross join core.competition c
 where c.code in ('ENG-PL', 'ESP-LL', 'ITA-SA', 'GER-BL', 'FRA-L1');

-- Goals markets where the model was checked against real closing odds and
-- closes a share of the gap in line with the established five.
insert into ml.market_competition (market_code, competition_id, status, notes)
select m.market_code, c.competition_id, 'shipping',
       'Closes a share of the base-rate-to-market gap inside the range the '
       || 'original five manage, measured against de-vigged closing odds.'
  from ml.market m
 cross join core.competition c
 where m.stat = 'goals'
   and m.status = 'shipping'
   and c.code in ('NED-ED', 'POR-PL', 'TUR-SL', 'BEL-PL');

-- Fouls totals: positive in all three with reliability inside the standard.
insert into ml.market_competition (market_code, competition_id, status, notes)
select 'fouls_total', c.competition_id, 'shipping',
       'Positive against the rolling benchmark with worst reliability bucket '
       || 'inside 8%.'
  from core.competition c
 where c.code in ('NED-ED', 'POR-PL', 'TUR-SL');

-- Per-team corners and shots, one league at a time on its own calibration.
insert into ml.market_competition (market_code, competition_id, status, notes)
values
  ('corners_home', (select competition_id from core.competition where code='NED-ED'),
   'shipping', '6.2% gain, worst bucket 6.8%.'),
  ('corners_home', (select competition_id from core.competition where code='TUR-SL'),
   'shipping', '1.6% gain, worst bucket 5.8%. Thin but calibrated.'),
  ('corners_home', (select competition_id from core.competition where code='POR-PL'),
   'held', '10.3% gain but worst bucket 9.7%, outside the standard.'),
  ('shots_home',   (select competition_id from core.competition where code='NED-ED'),
   'shipping', '14.2% gain, worst bucket 4.6%.'),
  ('shots_home',   (select competition_id from core.competition where code='POR-PL'),
   'held', '17.9% gain, the largest anywhere, but worst bucket 9.3%.'),
  ('shots_home',   (select competition_id from core.competition where code='TUR-SL'),
   'held', '6.8% gain, worst bucket 8.2%, just outside.');

-- Everything measured and found wanting, recorded so it is not retried blind.
insert into ml.market_competition (market_code, competition_id, status, notes)
select 'cards_total', c.competition_id, 'held',
       'Roughly zero gain. No referees loaded for this competition, and the '
       || 'referee term is what carries cards where anything does.'
  from core.competition c
 where c.code in ('NED-ED', 'POR-PL', 'TUR-SL');
