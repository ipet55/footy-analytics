-- ============================================================
-- Clean slate: the previous tables were empty and modelled on
-- a single provider's JSON response shape rather than the game.
-- ============================================================
drop table if exists public.head_to_head_by_event cascade;
drop table if exists public.match_stats_first_half cascade;
drop table if exists public.match_stats_second_half cascade;
drop table if exists public.match_stats_full cascade;
drop table if exists public.lineup_home cascade;
drop table if exists public.lineup_away cascade;
drop table if exists public.league_standings cascade;
drop table if exists public.top_players cascade;
drop table if exists public.transfer_records cascade;
drop table if exists public.news_items cascade;
drop table if exists public.squad_players cascade;
drop table if exists public.fixtures cascade;
drop table if exists public.league_teams cascade;
drop table if exists public.league_seasons cascade;
drop table if exists public.leagues cascade;

-- ============================================================
-- Schemas. Only `public` is exposed through the Data API, so
-- raw/core/features/ml are reachable only via the service role.
-- ============================================================
create schema if not exists raw;
create schema if not exists core;
create schema if not exists features;
create schema if not exists ml;

comment on schema raw is 'Immutable landing zone. One table per source, payload as jsonb. Never edited, never deleted - reprocess from here when parsing logic changes.';
comment on schema core is 'Canonical source of truth. Provider-agnostic model of the game.';
comment on schema features is 'Point-in-time-correct ML features. Every row may only contain data that existed before its match kicked off.';
comment on schema ml is 'Model registry, predictions and realised outcomes for calibration tracking.';

create extension if not exists unaccent with schema extensions;

-- ============================================================
-- Name normalisation: the single most important function here.
-- 'Manchester Utd', 'Man. United', 'MANCHESTER UNITED' all
-- collapse to 'manchesterunited' so aliases can be matched.
-- ============================================================
create or replace function core.norm_name(p_text text)
returns text
language sql
immutable
strict
as $$
  select regexp_replace(lower(extensions.unaccent(p_text)), '[^a-z0-9]+', '', 'g');
$$;

-- ============================================================
-- Sources
-- ============================================================
create table core.source (
  source_id    smallint generated always as identity primary key,
  code         text not null unique,
  name         text not null,
  kind         text not null check (kind in ('csv','api','scrape','dataset','rss')),
  is_licensed  boolean not null default false,
  notes        text
);
comment on table core.source is 'Every provider we ingest from. is_licensed=false means research use only, not safe to republish commercially.';

-- ============================================================
-- Competitions and seasons
-- ============================================================
create table core.competition (
  competition_id smallint generated always as identity primary key,
  code           text not null unique,
  name           text not null,
  country        text,
  tier           smallint,
  type           text not null default 'league' check (type in ('league','cup','international')),
  created_at     timestamptz not null default now()
);

create table core.season (
  season_id      integer generated always as identity primary key,
  competition_id smallint not null references core.competition on delete cascade,
  start_year     smallint not null,
  end_year       smallint not null,
  label          text not null,
  is_current     boolean not null default false,
  unique (competition_id, start_year)
);
create index on core.season (competition_id, start_year desc);

-- ============================================================
-- Teams + the alias layer that makes multi-source joins possible
-- ============================================================
create table core.team (
  team_id        integer generated always as identity primary key,
  canonical_name text not null,
  short_name     text,
  country        text,
  founded        smallint,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create unique index team_norm_name_uq on core.team (core.norm_name(canonical_name));

create table core.team_alias (
  alias_id       bigint generated always as identity primary key,
  team_id        integer not null references core.team on delete cascade,
  source_id      smallint not null references core.source,
  source_team_id text,
  alias_name     text not null,
  norm_name      text generated always as (core.norm_name(alias_name)) stored,
  created_at     timestamptz not null default now()
);
create unique index team_alias_source_norm_uq on core.team_alias (source_id, norm_name);
create unique index team_alias_source_id_uq on core.team_alias (source_id, source_team_id) where source_team_id is not null;
create index team_alias_norm_idx on core.team_alias (norm_name);
comment on table core.team_alias is 'Maps every spelling and provider ID to one canonical team_id. Resolve names through here, never by string-matching in application code.';

-- ============================================================
-- Unresolved names. Ingestion writes here instead of dropping
-- rows silently - this table should be reviewed after each load.
-- ============================================================
create table core.unresolved_alias (
  unresolved_id bigint generated always as identity primary key,
  source_id     smallint not null references core.source,
  entity_type   text not null check (entity_type in ('team','player','competition')),
  raw_value     text not null,
  norm_value    text generated always as (core.norm_name(raw_value)) stored,
  context       jsonb,
  occurrences   integer not null default 1,
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  resolved_at   timestamptz,
  unique (source_id, entity_type, raw_value)
);
comment on table core.unresolved_alias is 'Ingestion never silently drops an unmatched name - it lands here for review.';

-- ============================================================
-- Resolver: one function every ingester calls.
-- ============================================================
create or replace function core.resolve_team(
  p_source_code text,
  p_name        text,
  p_source_id   text default null,
  p_context     jsonb default null
)
returns integer
language plpgsql
as $$
declare
  v_source_id smallint;
  v_team_id   integer;
begin
  select source_id into v_source_id from core.source where code = p_source_code;
  if v_source_id is null then
    raise exception 'Unknown source code: %', p_source_code;
  end if;

  -- prefer the provider's stable ID over the name
  if p_source_id is not null then
    select team_id into v_team_id
    from core.team_alias
    where source_id = v_source_id and source_team_id = p_source_id;
    if v_team_id is not null then
      return v_team_id;
    end if;
  end if;

  select team_id into v_team_id
  from core.team_alias
  where source_id = v_source_id and norm_name = core.norm_name(p_name);
  if v_team_id is not null then
    return v_team_id;
  end if;

  -- fall back to a canonical-name match, and learn the alias
  select t.team_id into v_team_id
  from core.team t
  where core.norm_name(t.canonical_name) = core.norm_name(p_name);
  if v_team_id is not null then
    insert into core.team_alias (team_id, source_id, source_team_id, alias_name)
    values (v_team_id, v_source_id, p_source_id, p_name)
    on conflict do nothing;
    return v_team_id;
  end if;

  insert into core.unresolved_alias (source_id, entity_type, raw_value, context)
  values (v_source_id, 'team', p_name, p_context)
  on conflict (source_id, entity_type, raw_value) do update
    set occurrences = core.unresolved_alias.occurrences + 1,
        last_seen_at = now();
  return null;
end;
$$;
comment on function core.resolve_team is 'Name/ID -> canonical team_id. Returns null and logs to unresolved_alias when no match, so bad joins surface loudly.';
