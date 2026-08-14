export type Fixture = {
  match_id: number;
  competition_code: string;
  competition_name: string;
  season: string;
  matchday: number | null;
  kickoff_date: string;
  kickoff_utc: string | null;
  status: string;
  home_team_id: number;
  home_team: string;
  home_team_short: string;
  away_team_id: number;
  away_team: string;
  away_team_short: string;
  home_goals_ft: number | null;
  away_goals_ft: number | null;
  venue_name: string | null;
  has_predictions: boolean;
};

export type Prediction = {
  match_id: number;
  market_code: string;
  line: number | null;
  selection: string;
  probability: number;
  predicted_at: string;
  is_stored: boolean;
  observed: number | null;
  hit: boolean | null;
};

export type MarketPrice = {
  match_id: number;
  market_code: string;
  line: number | null;
  selection: string;
  probability: number;
};

export type Market = {
  market_code: string;
  competition_code: string;
  stat: string;
  scope: string;
  kind: string;
  label: string;
  notes: string | null;
};

export type Venue = "overall" | "home" | "away";

/** Per-match averages and the opponent comparison, split by venue. History
 *  rather than prediction: it adjusts for nothing. */
export type TeamSeasonMeasure = {
  team_id: number;
  team: string;
  competition_code: string;
  season: string;
  start_year: number;
  measure: string;
  venue: Venue;
  matches: number;
  total: number;
  per_match: number;
  points_per_game: number;
  beat_opponent_rate: number | null;
};

/** How often a team went over a line, split by venue. */
export type TeamSeasonLine = {
  team_id: number;
  team: string;
  competition_code: string;
  season: string;
  start_year: number;
  measure: string;
  venue: Venue;
  line: number;
  matches: number;
  over_count: number;
  over_rate: number;
};

/** What happened in a played match, both sides on one row. Columns are null where
 *  the competition has no such data — never zero. */
export type MatchStat = {
  match_id: number;
  home_shots: number | null;
  away_shots: number | null;
  home_shots_on_target: number | null;
  away_shots_on_target: number | null;
  home_shots_inside_box: number | null;
  away_shots_inside_box: number | null;
  home_corners: number | null;
  away_corners: number | null;
  home_fouls: number | null;
  away_fouls: number | null;
  home_yellows: number | null;
  away_yellows: number | null;
  home_reds: number | null;
  away_reds: number | null;
  home_offsides: number | null;
  away_offsides: number | null;
  home_possession: number | null;
  away_possession: number | null;
  home_passes: number | null;
  away_passes: number | null;
  home_passes_accurate: number | null;
  away_passes_accurate: number | null;
  home_saves: number | null;
  away_saves: number | null;
  home_xg: number | null;
  away_xg: number | null;
};

export type Team = {
  team_id: number;
  team: string;
  team_short: string;
  country: string | null;
  matches: number;
  latest_season: string;
  latest_start_year: number;
  competitions: string[];
};

export type TeamForm = {
  match_id: number;
  team_id: number;
  team: string;
  is_home: boolean;
  matches_before: number | null;
  ppg_5: number | null;
  ppg_10: number | null;
  gf_5: number | null;
  ga_5: number | null;
  gf_10: number | null;
  ga_10: number | null;
  xgf_10: number | null;
  xga_10: number | null;
  corners_f_10: number | null;
  corners_a_10: number | null;
  shots_f_10: number | null;
  shots_a_10: number | null;
  fouls_10: number | null;
  yellows_10: number | null;
  rest_days: number | null;
  season_matches: number | null;
  season_ppg: number | null;
};

export type HeadToHead = {
  match_id: number;
  h2h_matches: number | null;
  h2h_home_wins: number | null;
  h2h_draws: number | null;
  h2h_away_wins: number | null;
  h2h_avg_goals: number | null;
  h2h_avg_corners: number | null;
  rating_diff: number | null;
  difficulty_home: number | null;
  difficulty_away: number | null;
};

export const COMPETITIONS: Record<string, string> = {
  "ENG-PL": "Premier League",
  "ESP-LL": "La Liga",
  "GER-BL": "Bundesliga",
  "ITA-SA": "Serie A",
  "FRA-L1": "Ligue 1",
  "NED-ED": "Eredivisie",
  "POR-PL": "Liga Portugal",
  "TUR-SL": "Süper Lig",
  "BEL-PL": "Belgian Pro League",
  "BUL-1L": "Bulgaria First League",
  "CZE-1L": "Czech First League",
  "NOR-EL": "Eliteserien",
  "INT-UCL": "Champions League",
  "INT-UEL": "Europa League",
};
