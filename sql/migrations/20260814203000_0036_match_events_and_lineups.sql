-- ============================================================
-- Minutes and team sheets.
--
-- Two things the app has never been able to show. When a goal was
-- scored, which is what every "goals by 15 minutes" chart is built
-- from; and who actually started, with the formation and the coach.
--
-- core.appearance already holds who played and what they did, so a
-- team sheet needs no new table for the players. What it needs is the
-- part that belongs to the team rather than the player — formation
-- and coach — which is core.match_lineup.
--
-- Events carry the player's name as text alongside a nullable
-- player_id. That is deliberate. core.player.norm_name is unique, so
-- two players who normalise to the same name cannot both exist, and
-- an event feed introduces thousands of names from leagues whose
-- squads were never loaded. Insisting on a resolved player_id would
-- mean either dropping events or inventing player rows to hold them.
-- The name is what a timeline displays; the id is a bonus when the
-- player is already known.
--
-- No unique key on (match, minute, player, type): a player can
-- genuinely be booked twice, score twice in a minute of added time,
-- and be substituted on and off. Idempotency comes from deleting a
-- match's events before reloading them, which is what the loader
-- does.
-- ============================================================

create table core.match_event (
  event_id      bigint generated always as identity primary key,
  match_id      bigint  not null references core.match on delete cascade,
  team_id       integer not null references core.team,
  minute        smallint not null,
  extra_minute  smallint,
  kind          text    not null,
  detail        text,
  player_name   text,
  player_id     integer references core.player,
  assist_name   text,
  source_id     smallint not null references core.source,
  created_at    timestamptz not null default now(),
  constraint match_event_minute_check check (minute between 0 and 130),
  constraint match_event_kind_check
    check (kind = any (array['goal', 'card', 'substitution', 'var', 'other']))
);

create index match_event_match_idx on core.match_event (match_id, minute);
create index match_event_kind_idx  on core.match_event (kind, minute);

comment on table core.match_event is 'What happened and when. The minute is what every timing analysis needs and no other table has: goals by quarter-hour, when a team first scores, when it first concedes.';
comment on column core.match_event.player_name is 'Kept as text because core.player.norm_name is unique and an event feed brings in names from squads that were never loaded. player_id is populated when the player is already known and left null otherwise, rather than dropping the event.';
comment on column core.match_event.extra_minute is 'Added time within the minute, so 90+4 is minute 90 with extra_minute 4. Kept separate so a bucket boundary at 90 does not swallow stoppage time.';

create table core.match_lineup (
  match_id    bigint  not null references core.match on delete cascade,
  team_id     integer not null references core.team,
  formation   text,
  coach_name  text,
  source_id   smallint not null references core.source,
  updated_at  timestamptz not null default now(),
  primary key (match_id, team_id)
);

comment on table core.match_lineup is 'The part of a team sheet that belongs to the team rather than a player: formation and coach. Who played is in core.appearance.';
