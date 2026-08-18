-- ============================================================
-- Transfers in and out.
--
-- Clubs on both sides are stored twice over: as a team_id when we know
-- the club, and always as the provider's name. Most moves involve a
-- club outside these fourteen competitions — Arsenal loan players to
-- Crawley Town and sell them to Penafiel — and a transfer with a blank
-- destination is worse than useless on a page. The id is for joining,
-- the name is for reading.
--
-- `kind` is kept exactly as sent, including when the provider puts a
-- fee there. Its vocabulary is Loan, Free, Transfer, N/A, Free agent,
-- Return from loan, Back from Loan — and sometimes '€ 12M'. Two
-- spellings of returning from a loan is a fair warning against
-- normalising this into categories of our own.
--
-- The natural key includes the date, and duplicate reports of one move
-- are collapsed before they arrive, in the source function. The feed
-- republishes a transfer the next day, so Bruno Guimarães joining
-- Arsenal is reported on both 6 and 7 August, and a team page would
-- otherwise list every summer signing twice.
-- ============================================================

create table core.transfer (
  transfer_id  bigint generated always as identity primary key,
  player_id    integer not null references core.player on delete cascade,
  moved_on     date    not null,
  from_team_id integer references core.team,
  from_name    text,
  to_team_id   integer references core.team,
  to_name      text,
  kind         text,
  source_id    smallint not null references core.source,
  updated_at   timestamptz not null default now(),
  unique (player_id, moved_on, from_name, to_name)
);

create index transfer_to_idx   on core.transfer (to_team_id, moved_on desc);
create index transfer_from_idx on core.transfer (from_team_id, moved_on desc);

comment on table core.transfer is 'Moves in and out, as the provider reports them. Clubs outside these competitions have a name and no id, which is most of them.';
comment on column core.transfer.kind is 'The provider''s own word, unnormalised: Loan, Free, Transfer, N/A, Free agent, and two different spellings of returning from a loan. Occasionally a fee instead. Bucketing an open vocabulary this ragged would mostly produce wrong buckets.';
