-- ============================================================
-- Sources genuinely disagree about some results, and the
-- disagreement is information rather than an error.
--
-- The known case in this dataset: Sassuolo beat Pescara 2-1 on
-- the pitch on 2016-08-28, then forfeited 0-3 for fielding an
-- ineligible player. football-data.co.uk records the awarded
-- result; Understat records the match as played. Bookmakers
-- settled on the on-pitch score, so for modelling against odds
-- the played result is the correct target, while the official
-- table needs the awarded one. Keep both.
-- ============================================================
create table core.result_dispute (
  match_id           bigint   not null references core.match on delete cascade,
  source_id          smallint not null references core.source,
  source_home_goals  smallint not null,
  source_away_goals  smallint not null,
  note               text,
  noted_at           timestamptz not null default now(),
  primary key (match_id, source_id)
);

comment on table core.result_dispute is 'Where a secondary source reports a different score from the one in core.match. Ingestion records these instead of failing, but a large number in one season means the join is wrong, not the data.';

-- ============================================================
-- Every statistic, for and against, in one row per team-match.
--
-- A team''s "corners against" is just the opponent''s corners, so
-- storing it would duplicate data that can disagree with itself.
-- This view does the self-join once so no query has to repeat it.
-- ============================================================
create view core.team_match as
select
  m.match_id,
  m.competition_id,
  m.season_id,
  m.kickoff_date,
  m.kickoff_utc,
  m.status,
  m.referee_id,
  s.team_id,
  s.opponent_team_id,
  s.is_home,
  s.period,
  case
    when s.goals > s.goals_conceded then 'W'
    when s.goals < s.goals_conceded then 'L'
    else 'D'
  end::char(1) as outcome,
  case
    when s.goals > s.goals_conceded then 3
    when s.goals = s.goals_conceded then 1
    else 0
  end as points,

  s.goals            as goals_for,
  s.goals_conceded   as goals_against,
  s.xg               as xg_for,
  o.xg               as xg_against,
  s.npxg             as npxg_for,
  o.npxg             as npxg_against,
  s.shots            as shots_for,
  o.shots            as shots_against,
  s.shots_on_target  as sot_for,
  o.shots_on_target  as sot_against,
  s.corners          as corners_for,
  o.corners          as corners_against,
  s.fouls_committed  as fouls_committed,
  s.fouls_drawn      as fouls_drawn,
  s.yellow_cards     as yellows_for,
  o.yellow_cards     as yellows_against,
  s.red_cards        as reds_for,
  o.red_cards        as reds_against,
  s.possession_pct,
  s.ppda,
  o.ppda             as ppda_against,
  s.deep_completions,
  o.deep_completions as deep_completions_against,
  s.expected_points,

  -- Totals drive the over/under markets directly.
  (s.corners + o.corners)                                 as corners_total,
  (s.goals + o.goals)                                     as goals_total,
  (s.yellow_cards + o.yellow_cards)                       as yellows_total,
  (s.yellow_cards + o.yellow_cards
   + 2 * (s.red_cards + o.red_cards))                     as card_points_total,
  (s.fouls_committed + o.fouls_committed)                 as fouls_total,
  (s.shots + o.shots)                                     as shots_total,
  (s.xg + o.xg)                                           as xg_total
from core.match_team_stat s
join core.match m on m.match_id = s.match_id
join core.match_team_stat o
  on o.match_id = s.match_id
 and o.period   = s.period
 and o.team_id  = s.opponent_team_id;

comment on view core.team_match is 'One row per team per match per period, with every statistic in for/against form. Use this rather than joining core.match_team_stat to itself.';
