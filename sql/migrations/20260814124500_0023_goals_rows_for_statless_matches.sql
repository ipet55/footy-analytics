-- ============================================================
-- Give every played match a team-stat row carrying its goals.
--
-- core.team_match, which the whole feature layer is built from, is
-- driven by core.match_team_stat. A match with no row there is
-- invisible to it — so when API-Football supplies a score but no
-- statistics, which happens for about a fifth of the competitions
-- added today, a team's "last five matches" quietly skips the
-- fixture and its form is computed from the wrong games.
--
-- That is worse than a gap in corners. Goals are known for every
-- played match from core.match, so losing them because a provider
-- did not publish a shot count is avoidable.
--
-- 2,605 matches are affected, all of them in the five competitions
-- loaded from API-Football. Only goals are written; every other
-- column stays null, which the count models already handle by
-- filtering on the statistic they need being present.
-- ============================================================

insert into core.match_team_stat (
    match_id, team_id, period, is_home, opponent_team_id,
    goals, goals_conceded, source_id
)
select m.match_id, t.team_id, 'FT', t.is_home, t.opponent_id,
       t.goals, t.conceded, src.source_id
  from core.match m
 cross join core.source src
 cross join lateral (values
        (m.home_team_id, true,  m.away_team_id, m.home_goals_ft, m.away_goals_ft),
        (m.away_team_id, false, m.home_team_id, m.away_goals_ft, m.home_goals_ft)
     ) as t(team_id, is_home, opponent_id, goals, conceded)
 where src.code = 'api_football'
   and m.home_goals_ft is not null
   and not exists (
        select 1 from core.match_team_stat s
         where s.match_id = m.match_id and s.period = 'FT')
on conflict (match_id, team_id, period) do nothing;
