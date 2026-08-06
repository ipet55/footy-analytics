-- ============================================================
-- Features, as they were knowable before kickoff.
--
-- The single rule this schema exists to enforce: a row describing
-- a match may only contain information that existed before that
-- match was played. Every rolling average therefore ends at the
-- previous fixture, never the current one.
--
-- Getting this wrong does not produce an error. It produces a
-- model that looks excellent in backtest and loses money in
-- production, which is far worse, so the columns are named for
-- the window they cover and a check script verifies the windows.
-- ============================================================

create table features.team_match (
  match_id            bigint   not null references core.match on delete cascade,
  team_id             integer  not null references core.team,
  opponent_team_id    integer  not null references core.team,
  competition_id      smallint not null references core.competition,
  season_id           integer  not null references core.season,
  kickoff_date        date     not null,
  as_of               timestamptz not null,
  is_home             boolean  not null,

  -- How much history backs the numbers below. Rows with few prior
  -- matches carry unreliable features and the model should know it.
  matches_before      smallint not null,

  -- Rolling form over the previous N matches at any venue.
  gf_5   numeric(6,3), ga_5   numeric(6,3),
  xgf_5  numeric(6,3), xga_5  numeric(6,3),
  ppg_5  numeric(6,3),
  corners_f_5 numeric(6,3), corners_a_5 numeric(6,3),
  shots_f_5   numeric(6,3), shots_a_5   numeric(6,3),
  fouls_5     numeric(6,3), yellows_5   numeric(6,3),

  gf_10  numeric(6,3), ga_10  numeric(6,3),
  xgf_10 numeric(6,3), xga_10 numeric(6,3),
  ppg_10 numeric(6,3),
  corners_f_10 numeric(6,3), corners_a_10 numeric(6,3),
  shots_f_10   numeric(6,3), shots_a_10   numeric(6,3),
  fouls_10     numeric(6,3), yellows_10   numeric(6,3),

  xgf_20 numeric(6,3), xga_20 numeric(6,3),

  -- The same, restricted to the venue this match is played at.
  -- Answers "how does this side perform at home" without splitting
  -- the model itself in two.
  gf_venue_10      numeric(6,3), ga_venue_10      numeric(6,3),
  xgf_venue_10     numeric(6,3), xga_venue_10     numeric(6,3),
  corners_f_venue_10 numeric(6,3), corners_a_venue_10 numeric(6,3),
  yellows_venue_10 numeric(6,3),

  -- Season to date, excluding this match.
  season_matches smallint,
  season_ppg     numeric(6,3),
  season_xgf     numeric(6,3),
  season_xga     numeric(6,3),

  -- Schedule. Congestion beyond the domestic league needs cup and
  -- European fixtures, which are not loaded yet, so this counts
  -- league rest only and will understate a midweek European trip.
  rest_days smallint,

  -- Pre-match strength. The rating in force on match day is the one
  -- produced by the previous match, so this cannot see the result.
  elo_xg     numeric(8,3),
  elo_goals  numeric(8,3),
  clubelo    numeric(8,3),

  primary key (match_id, team_id)
);

create index team_match_team_date_idx on features.team_match (team_id, kickoff_date);
create index team_match_asof_idx on features.team_match (as_of);

comment on table features.team_match is 'One row per team per match, holding only what was knowable before kickoff. Suffix _5, _10, _20 is the number of previous matches averaged; _venue_ restricts to the same home/away venue.';
comment on column features.team_match.as_of is 'The moment these features became final: kickoff. Anything learned after this must not appear in the row.';
comment on column features.team_match.rest_days is 'Days since this team last played a league match. Understates congestion until cup and European fixtures are loaded.';

-- ============================================================
-- Match-level features: things that belong to the fixture rather
-- than to one side of it.
-- ============================================================
create table features.match (
  match_id       bigint not null primary key references core.match on delete cascade,
  competition_id smallint not null references core.competition,
  season_id      integer  not null references core.season,
  kickoff_date   date     not null,
  as_of          timestamptz not null,

  -- Head to head, same competition only, before this match.
  h2h_matches      smallint,
  h2h_home_wins    smallint,
  h2h_draws        smallint,
  h2h_away_wins    smallint,
  h2h_avg_goals    numeric(6,3),
  h2h_avg_corners  numeric(6,3),

  -- Strength gap and the 1-5 difficulty rating derived from it.
  rating_diff      numeric(8,3),
  difficulty_home  smallint,
  difficulty_away  smallint,

  -- De-vigged closing market probabilities. Held here as the
  -- benchmark to beat and as an optional feature, never mixed into
  -- the odds-free model, which must stay able to disagree with it.
  market_p_home numeric(6,5),
  market_p_draw numeric(6,5),
  market_p_away numeric(6,5),

  constraint difficulty_home_range check (difficulty_home between 1 and 5),
  constraint difficulty_away_range check (difficulty_away between 1 and 5)
);

create index match_features_season_idx on features.match (season_id, kickoff_date);

comment on table features.match is 'Fixture-level features. Market probabilities are stored for benchmarking; a model intended to find value against the market must be trained without them.';
comment on column features.match.difficulty_home is '1 easiest to 5 hardest, from fixed rating-difference thresholds rather than quantiles, so the value never depends on matches that had not been played yet.';
