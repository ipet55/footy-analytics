-- ============================================================
-- Squads, and who is missing each match.
--
-- Both need players to exist as entities, and the existing player
-- table cannot hold them as it stands. core.player has a global unique
-- index on the normalised name, which was workable while every player
-- came from one source that writes full names. It stops being workable
-- the moment a second source arrives writing abbreviated ones.
--
-- The evidence for how separate these two name spaces are: of 88,523
-- names on the team sheets loaded from API-Football, 2,563 resolve to
-- an existing player. FBref says 'Bukayo Saka' and API-Football says
-- 'B. Saka'. Matching them is a real piece of work and is not attempted
-- here; pretending it had been done is how the club table ended up with
-- twenty-two teams holding half a history each.
--
-- So the two populations are kept deliberately separate and honestly
-- labelled, with `origin` saying where a player came from. FBref's
-- name-uniqueness survives as a partial index over its own rows, which
-- keeps its loader working unchanged in behaviour. API-Football players
-- are keyed by provider id through core.player_source, which is what
-- that table was created for and has been empty ever since.
--
-- The consequence worth stating: a squad list will not yet join to
-- per-player match statistics. That is a known gap with a known fix
-- (match the two name spaces once, store the result), not an oversight.
-- ============================================================

alter table core.player add column origin text not null default 'fbref';
alter table core.player add column photo_url text;

comment on column core.player.origin is 'Which source first created this row. Two populations coexist and are not yet linked: FBref players carry full names and per-match statistics, API-Football players carry provider ids, squads and availability.';

alter table core.player drop constraint player_norm_name_key;

-- FBref resolves players by name and has no ids, so its rows keep the
-- uniqueness its loader relies on. Restricting the index to them means a second
-- source can hold an abbreviation of the same name without a collision.
create unique index player_name_uq_fbref
  on core.player (norm_name) where origin = 'fbref';

create index player_norm_name_idx on core.player (norm_name);

create table core.squad_member (
  team_id      integer not null references core.team,
  player_id    integer not null references core.player on delete cascade,
  shirt_number smallint,
  position     text,
  age          smallint,
  source_id    smallint not null references core.source,
  updated_at   timestamptz not null default now(),
  primary key (team_id, player_id)
);

create index squad_member_team_idx on core.squad_member (team_id, position);

comment on table core.squad_member is 'The current squad, as the provider reports it. Not a season history: a player who left in January is simply absent, because the endpoint describes today. Refreshed rather than accumulated.';

create table core.match_absence (
  match_id    bigint  not null references core.match on delete cascade,
  team_id     integer not null references core.team,
  player_name text    not null,
  player_id   integer references core.player on delete set null,
  status      text    not null,
  reason      text,
  source_id   smallint not null references core.source,
  updated_at  timestamptz not null default now(),
  primary key (match_id, team_id, player_name),
  constraint match_absence_status_check check (status in ('out', 'doubtful'))
);

create index match_absence_match_idx on core.match_absence (match_id);

comment on table core.match_absence is 'Who misses a specific match and why. Scoped to the fixture rather than to a date range, because that is how the source reports it and because it is the honest shape: a player is doubtful for a match, not doubtful in general.';
comment on column core.match_absence.status is 'out is the provider''s "Missing Fixture" and doubtful is its "Questionable". Kept as two values rather than one flag because a doubtful player still shapes a team sheet, and collapsing them would overstate what is known.';
comment on column core.match_absence.reason is 'The provider''s own words — Knee Injury, Muscle Injury, Red Card, Inactive. Left unnormalised because the vocabulary is open and a wrong bucket is worse than a raw string.';
