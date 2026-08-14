-- ============================================================
-- Who was named on the team sheet.
--
-- core.match_lineup holds the formation and the coach. This holds the
-- eleven and the bench, which is what a reader came for.
--
-- Names as text, with a nullable player_id, for the reason
-- core.match_event gives: core.player.norm_name is unique, and a
-- squad list from a league whose players were never loaded would
-- either collide with an existing name or require inventing rows to
-- hold it. A team sheet is useful on the page without every player
-- existing as an entity first, and inventing entities to satisfy a
-- display is how a player table fills with duplicates.
--
-- The natural key is (match, team, name). A squad cannot name the same
-- player twice, and keying on the name rather than the shirt number
-- means a corrected number updates the row instead of adding a second
-- one — which is the common correction between a provisional sheet and
-- a confirmed one.
-- ============================================================

create table core.match_lineup_player (
  match_id      bigint  not null,
  team_id       integer not null,
  player_name   text    not null,
  shirt_number  smallint,
  position      text,
  is_starter    boolean not null,
  player_id     integer references core.player,
  updated_at    timestamptz not null default now(),
  primary key (match_id, team_id, player_name),
  foreign key (match_id, team_id) references core.match_lineup on delete cascade
);

create index match_lineup_player_match_idx
  on core.match_lineup_player (match_id, is_starter);

comment on table core.match_lineup_player is 'The eleven and the bench. Names are text for the same reason core.match_event stores them that way: core.player.norm_name is unique and a squad list from a newly covered league cannot always be resolved to an existing player.';
comment on column core.match_lineup_player.position is 'The letter the feed gives — G, D, M, F — not a coordinate. Enough to group a sheet by line, which is what a reader scans for.';
