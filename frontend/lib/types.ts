export interface Team {
  team_id: string;
  name: string;
}

export interface Period {
  period: number;
  label: string;
  start_match_ms: number;
  duration_ms: number;
}

export interface Player {
  player_id: string;
  team_id: string;
  name: string;
  nickname: string | null;
  jersey_number: number | null;
  starter: boolean;
}

export interface Overview {
  canonical_match_id: string;
  competition: string;
  season: string;
  stage: string | null;
  kickoff_source: string;
  stadium: string | null;
  home: Team;
  away: Team;
  periods: Period[];
  duration_ms: number;
  players: Player[];
  attribution: string | null;
  source_ids: Record<string, number | string>;
}

export interface ReplayEvent {
  event_id: string;
  source_sequence: number;
  period: number;
  match_elapsed_ms: number;
  clock_label: string;
  team_id: string | null;
  player_id: string | null;
  player_name: string | null;
  type: string;
  subtype: string | null;
  outcome: string | null;
  x_m: number | null;
  y_m: number | null;
  end_x_m: number | null;
  end_y_m: number | null;
  is_goal: boolean;
  is_own_goal: boolean;
  is_shootout: boolean;
  provider_xg: number | null;
  card: string | null;
  recipient_id?: string | null;
  recipient_name: string | null;
  formation?: string | null;
  under_pressure?: boolean;
  has_freeze_frame: boolean;
  is_key: boolean;
}

export interface TeamStats {
  goals: number;
  shootout_goals: number;
  shots: number;
  shots_on_target: number;
  provider_xg: number;
  passes_attempted: number;
  passes_completed: number;
  corners: number;
  fouls: number;
  yellow_cards: number;
  red_cards: number;
  tackles: number;
  tackles_won: number;
  possession_pct: number | null;
  pass_accuracy_pct: number | null;
  tackle_success_pct: number | null;
}

export interface ReplayState {
  match_id: string;
  replay_t_ms: number;
  period: number;
  period_label: string;
  clock_label: string;
  score: Record<string, number>;
  shootout: Record<string, number> | null;
  stats: Record<string, TeamStats>;
  events_visible: number;
  ball: { x_m: number; y_m: number; observed: boolean; source: string } | null;
  finished: boolean;
}

export interface FreezeFrame {
  event_id: string;
  match_elapsed_ms: number;
  players: { x_m: number; y_m: number; team_id: string; teammate: boolean; actor: boolean; keeper: boolean }[];
  visible_area: number[][];
  source: string;
}
