-- ============================================================
-- Put the referee on the fixture.
--
-- core.match has carried referee_id since the FBref backfill, and it
-- is the strongest single driver in the card models — strong enough
-- that the count models shrink referee effects to stop the rare
-- official's noise leaking through. The app has never shown it.
--
-- Added to public.fixture rather than a view of its own, because every
-- page that would display it is already reading this row.
--
-- Appended after has_predictions rather than placed beside the venue
-- where it belongs, because 'create or replace view' can only add
-- columns at the end. Dropping and recreating would put every view
-- built on this one at risk for the sake of column order that nothing
-- reads positionally.
-- ============================================================

create or replace view public.fixture as
select m.match_id,
       c.code as competition_code,
       c.name as competition_name,
       s.label as season,
       m.matchday,
       m.kickoff_date,
       m.kickoff_utc,
       m.status,
       m.home_team_id,
       h.canonical_name as home_team,
       coalesce(h.short_name, h.canonical_name) as home_team_short,
       m.away_team_id,
       a.canonical_name as away_team,
       coalesce(a.short_name, a.canonical_name) as away_team_short,
       m.home_goals_ft,
       m.away_goals_ft,
       m.venue_name,
       exists (
         select 1
           from ml.prediction p
           join ml.market_competition mc on mc.market_code = p.market_code
                                        and mc.competition_id = m.competition_id
          where p.match_id = m.match_id and mc.status = 'shipping'
       ) as has_predictions,
       r.canonical_name as referee
  from core.match m
  join core.competition c on c.competition_id = m.competition_id
  join core.season s on s.season_id = m.season_id
  join core.team h on h.team_id = m.home_team_id
  join core.team a on a.team_id = m.away_team_id
  left join core.referee r on r.referee_id = m.referee_id;

grant select on public.fixture to anon, authenticated;
