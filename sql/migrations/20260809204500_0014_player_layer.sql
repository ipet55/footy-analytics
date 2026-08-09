-- ============================================================
-- Players and appearances.
--
-- Every model so far knows only which badges are on the pitch:
-- Chelsea with Palmer and Chelsea without him are the same team
-- to it. This is the layer that lets a model tell them apart,
-- and the one honest candidate left for the gap to the closing
-- line, now that the feature blend and per-team home advantage
-- have both been measured and rejected.
--
-- Deliberately an appearance table rather than a squad table.
-- Who was available is not recorded anywhere reliable after the
-- fact; who actually played is. Availability gets inferred from
-- absence from the sheet, which is weaker but is not a guess
-- dressed up as a record.
-- ============================================================

insert into core.source (code, name, kind, is_licensed, notes)
values ('fbref', 'FBref (Sports Reference)', 'scrape', false,
        'Match pages give lineups and per-player match stats. Rate limited to '
        'one request per seven seconds by their published policy. Research use '
        'only: Sports Reference terms forbid redistribution.')
on conflict (code) do nothing;

-- ============================================================
-- Player identity.
--
-- Matched on normalised name, the same mechanism as teams, and
-- with the same failure mode made loud rather than silent: a
-- name that will not resolve goes to core.unresolved_alias
-- instead of being invented.
--
-- No alias table yet, because there is exactly one source. The
-- moment a second one lands, names like "Son Heung-min" and
-- "Heung-Min Son" will need core.player_alias, mirroring
-- core.team_alias. source_player_key is here to make that
-- migration possible without re-scraping.
-- ============================================================
create table core.player (
  player_id      integer generated always as identity primary key,
  canonical_name text not null,
  norm_name      text generated always as (core.norm_name(canonical_name)) stored,
  birth_country  text,
  first_seen_on  date,
  last_seen_on   date,
  unique (norm_name)
);
comment on table core.player is 'One row per human. Identity is the normalised name; see core.player_source for provider keys.';

create table core.player_source (
  player_id       integer  not null references core.player(player_id) on delete cascade,
  source_id       smallint not null references core.source(source_id),
  source_player_key text   not null,
  primary key (source_id, source_player_key)
);
comment on table core.player_source is 'Provider-side identifiers, so a rename upstream does not fork a player into two rows.';

-- ============================================================
-- Appearances.
--
-- Grain is one row per player per match. minutes = 0 is a real
-- and useful row: an unused substitute was fit and in the squad,
-- which is evidence of availability that a missing row is not.
-- ============================================================
create table core.appearance (
  match_id            bigint   not null references core.match(match_id) on delete cascade,
  player_id           integer  not null references core.player(player_id),
  team_id             integer  not null references core.team(team_id),
  is_starter          boolean  not null,
  position            text,
  shirt_number        smallint,
  -- Extra time and stoppage push a few appearances past 90.
  minutes             smallint not null check (minutes between 0 and 130),
  goals               smallint,
  assists             smallint,
  shots               smallint,
  shots_on_target     smallint,
  penalties_scored    smallint,
  penalties_attempted smallint,
  yellows             smallint,
  reds                smallint,
  fouls_committed     smallint,
  fouls_drawn         smallint,
  tackles_won         smallint,
  interceptions       smallint,
  crosses             smallint,
  offsides            smallint,
  own_goals           smallint,
  primary key (match_id, player_id)
);
comment on table core.appearance is 'One row per player per match, including unused substitutes at minutes = 0.';
comment on column core.appearance.minutes is 'Zero means named in the squad but did not play, which is evidence of availability. A missing row means not in the squad at all.';

-- Feature building walks a player's history backwards from a
-- kickoff, so player-then-match is the access path that matters.
create index appearance_player_match_idx on core.appearance (player_id, match_id);
create index appearance_team_match_idx   on core.appearance (team_id, match_id);

-- ============================================================
-- Which matches actually have a sheet.
--
-- Without this, "no appearances for this match" is ambiguous
-- between not scraped and genuinely empty, and a feature built
-- on the difference would quietly treat gaps as weak squads.
-- ============================================================
create table core.lineup_coverage (
  match_id     bigint    not null primary key references core.match(match_id) on delete cascade,
  source_id    smallint  not null references core.source(source_id),
  scraped_at   timestamptz not null default now(),
  n_players    smallint  not null,
  is_complete  boolean   not null
);
comment on table core.lineup_coverage is 'Marks a match as scraped. is_complete is false when the sheet was short, e.g. missing substitutes.';
comment on column core.lineup_coverage.is_complete is 'A full sheet is roughly 28-40 players across both teams; anything less is flagged rather than silently trusted.';
