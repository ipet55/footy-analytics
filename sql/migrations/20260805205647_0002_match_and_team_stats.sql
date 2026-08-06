create or replace function core.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

create table core.referee (
  referee_id     integer generated always as identity primary key,
  canonical_name text not null,
  country        text
);
create unique index referee_norm_name_uq on core.referee (core.norm_name(canonical_name));

-- ============================================================
-- One row per match, provider-agnostic.
-- ============================================================
create table core.match (
  match_id       bigint generated always as identity primary key,
  competition_id smallint not null references core.competition,
  season_id      integer  not null references core.season,
  matchday       smallint,
  kickoff_date   date not null,
  kickoff_utc    timestamptz,
  status         text not null default 'scheduled'
                 check (status in ('scheduled','live','finished','postponed','cancelled','awarded')),
  home_team_id   integer not null references core.team,
  away_team_id   integer not null references core.team,
  home_goals_ft  smallint check (home_goals_ft >= 0),
  away_goals_ft  smallint check (away_goals_ft >= 0),
  home_goals_ht  smallint check (home_goals_ht >= 0),
  away_goals_ht  smallint check (away_goals_ht >= 0),
  result         char(1) generated always as (
                   case
                     when home_goals_ft is null or away_goals_ft is null then null
                     when home_goals_ft > away_goals_ft then 'H'
                     when home_goals_ft < away_goals_ft then 'A'
                     else 'D'
                   end
                 ) stored,
  total_goals    smallint generated always as (home_goals_ft + away_goals_ft) stored,
  referee_id     integer references core.referee,
  venue_name     text,
  attendance     integer,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint match_teams_differ check (home_team_id <> away_team_id)
);

-- Natural key: in a round-robin league a given ordered pair meets
-- exactly once per season. This is what makes re-running an
-- ingester idempotent instead of duplicating fixtures. Would need
-- widening if two-legged cup ties are ever added.
create unique index match_natural_key_uq
  on core.match (season_id, home_team_id, away_team_id);

create index match_kickoff_idx       on core.match (kickoff_date);
create index match_season_round_idx   on core.match (season_id, matchday);
create index match_home_team_idx      on core.match (home_team_id, kickoff_date desc);
create index match_away_team_idx      on core.match (away_team_id, kickoff_date desc);
create index match_status_idx         on core.match (status) where status in ('scheduled','live');

create trigger match_touch before update on core.match
  for each row execute function core.touch_updated_at();

-- ============================================================
-- Which provider ID corresponds to this match, per source.
-- The match-level twin of core.team_alias.
-- ============================================================
create table core.match_source (
  match_id        bigint   not null references core.match on delete cascade,
  source_id       smallint not null references core.source,
  source_match_id text,
  source_url      text,
  ingested_at     timestamptz not null default now(),
  primary key (match_id, source_id)
);
create unique index match_source_provider_uq
  on core.match_source (source_id, source_match_id)
  where source_match_id is not null;

-- ============================================================
-- Team stats: one row per (match, team, period).
-- Replaces the old match_stats_full / _first_half / _second_half
-- and lineup_home / lineup_away split. is_home is a column, so
-- "this team's home form" is a filter rather than a UNION.
-- ============================================================
create table core.match_team_stat (
  match_id         bigint   not null references core.match on delete cascade,
  team_id          integer  not null references core.team,
  period           text     not null default 'FT' check (period in ('FT','1H','2H')),
  is_home          boolean  not null,
  opponent_team_id integer  not null references core.team,

  goals            smallint,
  goals_conceded   smallint,
  shots            smallint,
  shots_on_target  smallint,
  shots_off_target smallint,
  shots_blocked    smallint,
  shots_inside_box smallint,
  corners          smallint,
  offsides         smallint,
  fouls_committed  smallint,
  yellow_cards     smallint,
  red_cards        smallint,
  possession_pct   numeric(5,2) check (possession_pct between 0 and 100),
  passes           integer,
  passes_accurate  integer,
  saves            smallint,
  tackles          smallint,
  interceptions    smallint,

  -- advanced (Understat / FBref)
  xg               numeric(6,3),
  npxg             numeric(6,3),
  deep_completions smallint,
  ppda             numeric(6,2),

  source_id        smallint references core.source,
  updated_at       timestamptz not null default now(),
  primary key (match_id, team_id, period)
);

create index mts_team_period_idx on core.match_team_stat (team_id, period);
create index mts_xg_idx on core.match_team_stat (team_id) where xg is not null;

create trigger mts_touch before update on core.match_team_stat
  for each row execute function core.touch_updated_at();

comment on table core.match_team_stat is 'Long format: home/away is the is_home column, full-time vs halves is the period column. xGA for a team is the opponent row''s xg - do not duplicate it here.';
comment on index core.match_natural_key_uq is 'Idempotency key for ingestion. Would need widening for two-legged cup ties.';
