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

/** How often a team actually went over a line, counted from matches played.
 *  History, not prediction: it does not adjust for the opponent. */
export type TeamSeasonSummary = {
  team_id: number;
  team: string;
  competition_code: string;
  season: string;
  start_year: number;
  measure: string;
  line: number;
  matches: number;
  over_count: number;
  over_rate: number;
  mean_value: number;
};

export type TeamSeasonVenue = {
  team_id: number;
  team: string;
  competition_code: string;
  season: string;
  venue: "home" | "away";
  matches: number;
  goals_for: number;
  goals_against: number;
  corners_for: number;
  corners_against: number;
  shots_for: number;
  cards: number;
  fouls: number;
  scored_rate: number;
  conceded_rate: number;
  points_per_game: number;
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
