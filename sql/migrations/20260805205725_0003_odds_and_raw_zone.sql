-- ============================================================
-- Odds. Long format: one row per bookmaker/market/outcome/snapshot.
-- These are both a feature AND the benchmark the model is judged
-- against, so they are first-class, not an afterthought.
-- ============================================================
create table core.odds (
  odds_id     bigint generated always as identity primary key,
  match_id    bigint   not null references core.match on delete cascade,
  source_id   smallint not null references core.source,
  bookmaker   text     not null,
  market      text     not null check (market in ('1X2','OU','AH','BTTS','CS','DC')),
  outcome     text     not null,
  line        numeric(4,2),
  price       numeric(8,3) not null check (price > 1.0),
  snapshot    text     not null check (snapshot in ('opening','closing','live')),
  captured_at timestamptz
);

-- coalesce() lets the 1X2 rows (null line) participate in uniqueness
create unique index odds_uq on core.odds (
  match_id, source_id, bookmaker, market, outcome, coalesce(line, -999), snapshot
);
create index odds_match_market_idx on core.odds (match_id, market, snapshot);

comment on column core.odds.snapshot is 'opening = at market open, closing = final pre-kickoff. Closing odds are the sharpest market estimate and the benchmark for model evaluation.';
comment on column core.odds.line is 'Handicap or over/under line (2.5, -0.5). Null for 1X2.';

-- ============================================================
-- Market consensus with the bookmaker margin removed.
-- This is the baseline every model must beat.
-- ============================================================
create or replace view core.market_1x2 as
with agg as (
  select
    match_id,
    snapshot,
    count(distinct bookmaker)                        as bookmakers,
    avg(price) filter (where outcome = 'H')          as avg_home,
    avg(price) filter (where outcome = 'D')          as avg_draw,
    avg(price) filter (where outcome = 'A')          as avg_away,
    max(price) filter (where outcome = 'H')          as max_home,
    max(price) filter (where outcome = 'D')          as max_draw,
    max(price) filter (where outcome = 'A')          as max_away
  from core.odds
  where market = '1X2'
  group by match_id, snapshot
)
select
  match_id,
  snapshot,
  bookmakers,
  avg_home, avg_draw, avg_away,
  max_home, max_draw, max_away,
  round((1/avg_home + 1/avg_draw + 1/avg_away)::numeric, 4) as overround,
  round(((1/avg_home) / (1/avg_home + 1/avg_draw + 1/avg_away))::numeric, 5) as p_home,
  round(((1/avg_draw) / (1/avg_home + 1/avg_draw + 1/avg_away))::numeric, 5) as p_draw,
  round(((1/avg_away) / (1/avg_home + 1/avg_draw + 1/avg_away))::numeric, 5) as p_away
from agg
where avg_home is not null and avg_draw is not null and avg_away is not null;

comment on view core.market_1x2 is 'De-vigged market probabilities using proportional normalisation. Adequate as a baseline; Shin or logarithmic de-vigging can be layered on later if draw bias matters.';

-- ============================================================
-- Raw landing zone. Immutable. When parsing logic changes in
-- month four, reprocess from here instead of re-fetching.
-- ============================================================
create table raw.ingest_run (
  run_id      bigint generated always as identity primary key,
  source_id   smallint not null references core.source,
  entity      text not null,
  status      text not null default 'running' check (status in ('running','success','failed','partial')),
  params      jsonb,
  rows_read   integer,
  rows_written integer,
  error       text,
  started_at  timestamptz not null default now(),
  finished_at timestamptz
);
create index ingest_run_source_idx on raw.ingest_run (source_id, entity, started_at desc);

create table raw.payload (
  payload_id   bigint generated always as identity primary key,
  run_id       bigint references raw.ingest_run on delete set null,
  source_id    smallint not null references core.source,
  entity       text not null,
  natural_key  text,
  content_hash text not null,
  payload      jsonb not null,
  fetched_at   timestamptz not null default now(),
  processed_at timestamptz
);
create index payload_lookup_idx on raw.payload (source_id, entity, natural_key);
create index payload_unprocessed_idx on raw.payload (source_id, entity) where processed_at is null;

-- Re-fetching byte-identical content is a no-op rather than a duplicate
create unique index payload_dedupe_uq on raw.payload (source_id, entity, natural_key, content_hash);
