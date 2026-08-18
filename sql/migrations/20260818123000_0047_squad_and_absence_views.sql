-- ============================================================
-- Publish squads and match absences.
--
-- public.squad is the roster a team page shows: one row per player,
-- with the shirt number and position, and a flag saying whether he is
-- currently unavailable for his club's next fixture.
--
-- That flag is the useful part and it is derived rather than stored,
-- because availability is reported per fixture and a "currently
-- injured" column would be a second version of the same fact, free to
-- disagree with the first.
--
-- public.match_absence is the same data from the other direction: who
-- misses this match. A page showing an upcoming fixture wants exactly
-- that and nothing else.
-- ============================================================

create or replace view public.match_absence as
select a.match_id,
       a.team_id,
       t.canonical_name as team,
       a.team_id = m.home_team_id as is_home,
       a.player_name,
       a.status,
       a.reason,
       p.photo_url
  from core.match_absence a
  join core.match m using (match_id)
  join core.team t on t.team_id = a.team_id
  left join core.player p on p.player_id = a.player_id;

comment on view public.match_absence is 'Who misses a given match and why. status is out or doubtful, and reason is the provider''s own words rather than a bucket of ours.';

create or replace view public.squad as
with next_fixture as (
    -- One upcoming match per club, which is what "currently unavailable" can
    -- honestly mean. Absences only exist for fixtures within a few days, so for
    -- most of the week this correctly resolves to nothing.
    select distinct on (t.team_id) t.team_id, m.match_id
      from core.team t
      join core.match m on t.team_id in (m.home_team_id, m.away_team_id)
     where m.home_goals_ft is null
       and m.kickoff_date >= current_date
     order by t.team_id, m.kickoff_date
)
select sm.team_id,
       t.canonical_name as team,
       sm.player_id,
       p.canonical_name as player_name,
       p.photo_url,
       sm.shirt_number,
       sm.position,
       sm.age,
       ab.status as absence_status,
       ab.reason as absence_reason
  from core.squad_member sm
  join core.team t on t.team_id = sm.team_id
  join core.player p on p.player_id = sm.player_id
  left join next_fixture nf on nf.team_id = sm.team_id
  left join core.match_absence ab on ab.match_id = nf.match_id
                                 and ab.team_id = sm.team_id
                                 -- Joined on name because the absence feed and the
                                 -- squad feed agree on spelling: both come from the
                                 -- same provider. player_id would be stricter but
                                 -- is null whenever a player was seen missing before
                                 -- he was ever seen in a squad.
                                 and core.norm_name(ab.player_name)
                                   = core.norm_name(p.canonical_name);

comment on view public.squad is 'A club''s current roster with availability for its next fixture. The squad is what the provider reports today, not a season history: a player sold in January is gone rather than listed as departed.';

grant select on public.squad, public.match_absence to anon, authenticated;
