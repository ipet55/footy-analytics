-- ============================================================
-- Publish the match statistics already stored.
--
-- core.match_team_stat carries between six and sixteen figures per
-- team per match — shots, shots on target, corners, fouls, cards
-- everywhere, expected goals in the top five, possession and passes
-- wherever API-Football is the source — and the app shows none of
-- it. A match page has been a table of probabilities with no
-- evidence beside them.
--
-- One row per match, both sides on it, because that is how a reader
-- uses it: 14 shots against 9 means something, 14 shots alone does
-- not.
--
-- Null columns are left null rather than defaulted. A league with no
-- possession data should show nothing there, not zero, and the app
-- decides which rows to render from what is present.
-- ============================================================

create or replace view public.match_stat as
select m.match_id,
       h.shots            as home_shots,
       a.shots            as away_shots,
       h.shots_on_target  as home_shots_on_target,
       a.shots_on_target  as away_shots_on_target,
       h.shots_inside_box as home_shots_inside_box,
       a.shots_inside_box as away_shots_inside_box,
       h.corners          as home_corners,
       a.corners          as away_corners,
       h.fouls_committed  as home_fouls,
       a.fouls_committed  as away_fouls,
       h.yellow_cards     as home_yellows,
       a.yellow_cards     as away_yellows,
       h.red_cards        as home_reds,
       a.red_cards        as away_reds,
       h.offsides         as home_offsides,
       a.offsides         as away_offsides,
       h.possession_pct   as home_possession,
       a.possession_pct   as away_possession,
       h.passes           as home_passes,
       a.passes           as away_passes,
       h.passes_accurate  as home_passes_accurate,
       a.passes_accurate  as away_passes_accurate,
       h.saves            as home_saves,
       a.saves            as away_saves,
       h.xg               as home_xg,
       a.xg               as away_xg
  from core.match m
  join core.match_team_stat h on h.match_id = m.match_id
                             and h.team_id = m.home_team_id and h.period = 'FT'
  join core.match_team_stat a on a.match_id = m.match_id
                             and a.team_id = m.away_team_id and a.period = 'FT'
 where m.home_goals_ft is not null;

comment on view public.match_stat is 'What actually happened in a played match, both sides on one row. Columns are null where the competition has no such data rather than zero, so a reader is never shown a fabricated zero.';

grant select on public.match_stat to anon, authenticated;
