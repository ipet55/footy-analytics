-- ============================================================
-- Require an alias name to be unique only where the name is the key.
--
-- team_alias_source_norm_uq made (source_id, norm_name) unique for
-- every source. That is exactly right for a source we resolve by
-- name: two rows with the same normalised name would make the
-- lookup ambiguous and quietly attach results to whichever row the
-- planner reached first.
--
-- It is wrong for a source that numbers its clubs. API-Football
-- resolves through source_team_id, and distinct ids there can share
-- a name — the Champions League has two clubs normalising to
-- 'drita', which is what broke the 2020 load. Under the old rule
-- the second one could not be stored at all, so either a club went
-- missing or its fixtures failed to resolve.
--
-- The replacement applies the name rule only where source_team_id
-- is null, which is precisely the name-keyed sources: clubelo,
-- fbref and football_data_uk have no ids at all, and every one of
-- api_football's 234 aliases has one. Sources with ids keep their
-- own uniqueness through team_alias_source_id_uq, which is
-- untouched, so nothing loses a guarantee it was relying on.
-- ============================================================

drop index if exists core.team_alias_source_norm_uq;

create unique index team_alias_source_norm_uq
  on core.team_alias (source_id, norm_name)
  where source_team_id is null;

comment on index core.team_alias_source_norm_uq is 'Unambiguous name lookup for sources keyed by name. Sources that number their clubs are excluded: they resolve through source_team_id, and two of their clubs may legitimately share a name.';
