-- ============================================================
-- Widen the match natural key with a stage.
--
-- 0002 keyed a match on (season, home, away) and noted that it
-- "would need widening if two-legged cup ties are ever added".
-- The Belgian Pro League got there first: since 2023/24 it plays a
-- 240-match double round robin and then splits into championship,
-- Europa and relegation playoffs in which all sixteen clubs meet
-- opponents they have already played. Seventy-two pairings a season
-- collide with the old key, which is why Belgium loads to 2022/23
-- and stops.
--
-- 'regular' is the default and describes every match already
-- stored, so this is a widening rather than a change: the existing
-- 36,967 rows keep the identity they had, and any loader that does
-- not know about stages keeps working unchanged.
--
-- Text rather than an enum, and no check constraint, because the
-- vocabulary is not known yet. Belgium and Bulgaria need
-- 'playoff'; a cup needs round names; the Champions League needs a
-- group stage and knockout rounds. Pinning the values now would
-- mean a migration each time one is discovered.
-- ============================================================

alter table core.match
  add column if not exists stage text not null default 'regular';

comment on column core.match.stage is 'Which phase of the competition a match belongs to. ''regular'' for a round-robin league season, which is the default and covers most rows. Part of the natural key, so a pairing can meet more than once per season — Belgium''s playoffs, and cup ties later.';

drop index if exists core.match_natural_key_uq;

create unique index match_natural_key_uq
  on core.match (season_id, home_team_id, away_team_id, stage);

-- Reading a season's playoff phase should not scan the season.
create index if not exists match_season_stage_idx
  on core.match (season_id, stage)
  where stage <> 'regular';
