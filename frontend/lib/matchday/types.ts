// Matchday API contract types (docs/MATCHDAY_API.md); fields the backend may omit are optional or nullable.

export type Lang = "en" | "es" | "hi";
export type SideKey = "home" | "away";
/** Index into `[home, away]` arrays. */
export type SideIdx = 0 | 1;
export type Role = "GK" | "DEF" | "MID" | "ATT";
export type KitPattern = "solid" | "stripes" | "hoops" | "tricolor";
export type Pattern = "balanced" | "settled" | "high_tempo" | "end_to_end" | "stop_start" | "siege";
export const PATTERNS: Pattern[] = ["balanced", "settled", "high_tempo", "end_to_end", "stop_start", "siege"];

export interface TeamColors {
  primary: string;
  secondary: string;
  ink: string;
  pattern: KitPattern;
}

export interface MetaTeam {
  team_id: string;
  side: SideKey;
  name: string;
  short: string;
  name_hi?: string | null;
  short_hi?: string | null;
  colors?: TeamColors | null;
}

export interface MetaPeriod {
  period: number;
  label: string;
  start_ms: number;
  duration_ms: number;
  base_minute: number;
}

export interface MetaPlayer {
  player_id: string;
  team_id: string;
  side: SideKey;
  name: string;
  short: string;
  name_hi?: string | null;
  short_hi?: string | null;
  number: number | null;
  position: string | null;
  role: Role;
  starter: boolean;
}

export interface MatchMeta {
  match_id: string;
  competition: string;
  stage?: string | null;
  date: string;
  stadium?: string | null;
  home: MetaTeam;
  away: MetaTeam;
  periods: MetaPeriod[];
  duration_ms: number;
  players: MetaPlayer[];
  has_tracking: boolean;
  tracking_hz?: number | null;
  /** Client-only: built from /v1/matches because /matchday/meta was unavailable. */
  fallback?: boolean;
}

export interface FlowComp {
  turnovers: number;
  duels: number;
  transitions: number;
  long_share: number;
  avg_seq: number;
}

export interface Flow {
  chaos: number;
  control: [number, number];
  comp: FlowComp;
  tempo: number;
  bip: number;
  stops: number;
  tilt: number;
  pattern: Pattern;
  poss_share: [number, number];
  pass_acc: [number | null, number | null];
  siege_team: SideIdx | null;
}

export interface ShapeStat {
  length: number | null;
  width: number | null;
  area: number | null;
  def: number | null;
  mid: number | null;
  att: number | null;
  gap_dm: number | null;
  gap_ma: number | null;
  def_w: number | null;
  mid_w: number | null;
  att_w: number | null;
}

export interface SeriesPoint {
  t_ms: number;
  clock: string;
  score: [number, number];
  win: [number, number, number] | null;
  flow: Flow | null;
  shape: [ShapeStat | null, ShapeStat | null] | null;
}

export interface SeriesResp {
  step_ms: number;
  points: SeriesPoint[];
}

export type MomentKind = "goal" | "chance" | "card" | "sub" | "flow" | "shape" | "speed" | "pass" | "milestone";
export type MomentFacts = Record<string, number | string | boolean | null | undefined>;

export interface Moment {
  id: string;
  t_ms: number;
  clock: string;
  kind: MomentKind | string;
  variant: string | null;
  side: SideIdx | null;
  team_id: string | null;
  player_id: string | null;
  player2_id: string | null;
  imp: number;
  f: MomentFacts;
}

export interface MomentsResp {
  moments: Moment[];
}

export interface PlayerAction {
  t_ms: number;
  clock: string;
  type: string;
  detail: string | null;
  ok: boolean | null;
}

export interface PlayerFocus {
  player_id: string;
  on_pitch: boolean;
  minutes: number;
  dist_km: number | null;
  top_kmh: number | null;
  sprints: number | null;
  touches: number;
  passes: number;
  passes_ok: number;
  pass_diff: number | null;
  shots: number;
  xg: number;
  goals: number;
  duels_won: number;
  heat: { cols: number; rows: number; counts: number[] } | null;
  actions: PlayerAction[];
}

export type Speaker = "pbp" | "colour";

export interface CommentaryLine {
  id: string;
  t_ms: number;
  clock: string;
  speaker: Speaker;
  text: string;
  excitement: number;
  priority: 1 | 2 | 3;
  kind: string;
  dur_ms: number;
  interrupts?: boolean;
  audio_url: string | null;
}

export interface CommentaryResp {
  lang: Lang;
  tts: "azure" | "none";
  lines: CommentaryLine[];
}

/** GET /v1/matches item. */
export interface MatchListItem {
  match_id: string;
  competition: string;
  season?: string;
  stage: string | null;
  date: string;
  home: { team_id: string; name: string };
  away: { team_id: string; name: string };
  featured?: boolean;
  completeness?: { continuous_tracking?: boolean; tracking?: unknown } | null;
}

/** GET /v1/matches/{id}/events item (fields the UI reads). */
export interface MatchEvent {
  event_id: string;
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
  is_goal: boolean;
  is_own_goal: boolean;
  is_shootout: boolean;
  card: string | null;
  source_sequence?: number;
  end_x_m?: number | null;
  end_y_m?: number | null;
  provider_xg?: number | null;
  recipient_id?: string | null;
  recipient_name?: string | null;
  has_freeze_frame?: boolean;
  /** Declared shape on Starting XI / Tactical Shift events. */
  formation?: string | null;
  is_key?: boolean;
}

/** Per-team stats in /state; missing fields render as "–". */
export interface TeamStats {
  goals?: number;
  shots?: number;
  shots_on_target?: number;
  provider_xg?: number;
  passes_attempted?: number;
  passes_completed?: number;
  pass_accuracy_pct?: number | null;
  possession_pct?: number | null;
  corners?: number;
  fouls?: number;
  yellow_cards?: number;
  red_cards?: number;
  tackles?: number;
  tackles_won?: number;
}

/** GET /v1/matches/{id}/state (fields the UI reads). */
export interface MatchState {
  replay_t_ms: number;
  period: number;
  clock_label: string;
  score: Record<string, number>;
  shootout: Record<string, number> | null;
  stats: Record<string, TeamStats>;
  ball: { x_m: number; y_m: number } | null;
  finished: boolean;
}

/** GET /v1/matches/{id}/tracking roster entry. */
export interface TrackingRosterEntry {
  idx: number;
  team_id: string;
  side: SideKey;
  jersey: string;
  player_id: string | null;
  name: string | null;
  position_group: string | null;
  started: boolean | null;
}

// ------------------------------------------------------------------ live viewing
/** GET /v1/matches/{id}/freeze-frame?at_ms: latest event freeze-frame (events-only matches). */
export interface FreezeFramePlayer { x_m: number; y_m: number; team_id: string | null; teammate?: boolean; actor?: boolean; keeper?: boolean }
export interface FreezeFrame { event_id: string; match_elapsed_ms: number; players: FreezeFramePlayer[]; visible_area: [number, number][] }

/** GET /v1/matches/{id}/predictions?at_ms (subset). 503 while the models are not scored. */
export interface Forecast { label?: string; probability: number | null; value?: number | null }
export type ForecastKey = "goal_next_10m" | "corner_next_2m" | "penalty_next_5m" | "win_phase" | "expected_goals_rest";
export interface Predictions {
  at_ms: number;
  model_version: string | null;
  phase: "regulation" | "extra time" | string | null;
  teams: Record<string, Partial<Record<ForecastKey, Forecast>>>;
  draw_phase: Forecast | null;
}

/** GET /v1/matches/{id}/tactical/windows?at_ms */
export interface TacticalWindowRef { window_id: string; label: string; start_ms: number; end_ms: number; available: boolean; in_progress: boolean }
/** GET /v1/matches/{id}/tactical?team&window&at_ms (only the metrics the live card shows). */
export interface TacticalMetrics {
  possession_pct?: number | null; links_per_sample?: number | null; lane_clearance_pct?: number | null;
  triangles_per_sample?: number | null; regains?: number | null; formation?: string | null; declared_formation?: string | null;
}
export interface TacticalWindow { team_id: string; window_id: string; label: string; metrics: TacticalMetrics }
/** GET /v1/matches/{id}/tactical/formations?at_ms */
export interface FormationSegment { team_id: string; start_ms: number; end_ms: number; formation: string | null; raw_formation?: string | null; confidence?: number }
export interface FormationsResp { segments: FormationSegment[] }

/** GET /v1/matches/{id}/insights?at_ms */
export interface InsightPlayerRef { player_id: string; name: string }
export type InsightSubject = null
  | { type: "player"; player_id: string; name: string; team_id: string; reasons?: string[] }
  | { type: "substitution"; team_id: string; options: { off: InsightPlayerRef; on: InsightPlayerRef | null }[] }
  | { type: "best_player"; team_id: string; situation: string; ranked: InsightPlayerRef[] };
export interface Insight {
  id: string; t_ms: number; clock_label: string; minute: string; category: string; kind: string; priority: 1 | 2 | 3;
  team_id: string | null; title: string; detail: string; seek_ms: number | null; subject: InsightSubject;
}
export interface InsightList { at_ms: number; insights: Insight[] }
/** POST /v1/matches/{id}/insights/{insight_id}/ai */
export interface MomentCard { headline: string; what_is_happening: string; main_risk: string; one_action: string; confidence: string }
export interface AiTakeResp { card: MomentCard | null; raw?: string; model?: string | null }
