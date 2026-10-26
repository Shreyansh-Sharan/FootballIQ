import type { Overview } from "./types";
import type { WireFrame } from "./trackingBuffer";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface MatchSummary {
  match_id: string;
  competition: string;
  season: string;
  stage: string | null;
  date: string;
  home: { team_id: string; name: string };
  away: { team_id: string; name: string };
  completeness: {
    events: number | null;
    event_snapshots_360: number | null;
    continuous_tracking: boolean;
    tracking: { provider: string; method: string; pff_game_id?: number; periods: number; frames: number; hz?: number;
      direction_agrees_with_metadata?: boolean; coverage_mean?: number | null } | null;
  };
}

export interface FormRow {
  match_id: string;
  date: string;
  stage: string | null;
  opponent: string;
  venue: string;
  score: string;
  pens: string | null;
  result: "W" | "D" | "L";
}

export interface History {
  cutoff_date: string;
  cutoff_rule: string;
  coverage: string;
  teams: Record<string, { team_id: string; name: string; form: FormRow[]; summary: Record<string, number> }>;
  head_to_head: FormRow[];
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API_URL}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export const api = {
  matches: () => get<MatchSummary[]>("/v1/matches"),
  overview: (id: string) => get<Overview & { tracking: unknown }>(`/v1/matches/${encodeURIComponent(id)}/overview`),
  history: (id: string) => get<History>(`/v1/matches/${encodeURIComponent(id)}/history`),
  freezeFrame: (id: string, at: number) => get<{ freeze_frame: import("./types").FreezeFrame | null }>(`/v1/matches/${encodeURIComponent(id)}/freeze-frame?at_ms=${Math.floor(at)}`),
  frames: (id: string, fromMs: number, toMs: number, max = 600) =>
    get<{ frames: WireFrame[] }>(
      `/v1/matches/${encodeURIComponent(id)}/frames?from_ms=${fromMs}&to_ms=${toMs}&max_frames=${max}`,
    ),
};

export const FINAL_ID = "2022-12-18_argentina_france";

// ---- tactical / physical
export interface TacticalWindowRef { window_id: string; label: string; start_ms: number; end_ms: number; available: boolean; in_progress: boolean }
export interface TacticalMetrics {
  possession_pct: number | null; links_per_sample: number | null; lane_clearance_pct: number | null;
  triangles_per_sample: number | null; quads_per_sample: number | null; pentagons_per_sample: number | null;
  width_in_possession_m: number | null; depth_in_possession_m: number | null;
  width_out_of_possession_m: number | null; depth_out_of_possession_m: number | null;
  regains: number | null; formation: string | null; declared_formation: string | null; samples: number; possession_samples: number;
  possession_pct_statsbomb: number | null; possession_pct_pff: number | null;
  possession_agree_statsbomb_pct: number | null; possession_agree_pff_pct: number | null; start_ms: number; end_ms: number;
  viable_triangles_per_sample?: number | null; viable_quads_per_sample?: number | null; viable_pentagons_per_sample?: number | null;
  best_motif_score_mean?: number | null;
}
export interface TacticalWindow {
  team_id: string; window_id: string; label: string; metrics: TacticalMetrics;
  network: { nodes: { player_id: string; x_m: number; y_m: number; passes: number }[]; edges: { from: string; to: string; passes: number }[] };
  heatmap: { cx: number; cy: number; samples: number }[];
  regains: { zx: number; zy: number; regains: number }[];
  definitions: Record<string, string>;
}
export interface TimelineRow { window_id: string; label: string; team_id: string; start_ms: number; end_ms: number; formation: string | null; declared_formation: string | null; possession_pct: number | null; possession_pct_statsbomb: number | null; possession_agree_statsbomb_pct: number | null; width_in_possession_m: number | null; depth_in_possession_m: number | null }
export interface PhysicalRow { team_id: string; side: "home" | "away"; jersey: string; player_id: string | null; name: string | null; position_group: string | null; distance_km: number; hsr_km: number; sprint_km: number; top_speed_kmh: number; minutes_tracked: number; observed_pct: number | null; on_pitch: boolean }

const enc = encodeURIComponent;
export const tacticalApi = {
  windows: (id: string, at: number) => get<{ windows: TacticalWindowRef[] }>(`/v1/matches/${enc(id)}/tactical/windows?at_ms=${Math.floor(at)}`),
  window: (id: string, team: string, win: string, at: number) => get<TacticalWindow>(`/v1/matches/${enc(id)}/tactical?team=${enc(team)}&window=${enc(win)}&at_ms=${Math.floor(at)}`),
  timeline: (id: string, at: number) => get<{ windows: TimelineRow[] }>(`/v1/matches/${enc(id)}/tactical/timeline?at_ms=${Math.floor(at)}`),
  formations: (id: string, at: number) => get<{ segments: { team_id: string; start_ms: number; end_ms: number; raw_formation: string | null; confidence: number; formation: string | null }[]; switches: { team_id: string; at_ms: number; from_formation: string; to_formation: string }[]; method: string }>(`/v1/matches/${enc(id)}/tactical/formations?at_ms=${Math.floor(at)}`),
  physical: (id: string, at: number) => get<{ players: PhysicalRow[] }>(`/v1/matches/${enc(id)}/physical?at_ms=${Math.floor(at)}`),
};

// ---- model outputs
export interface Forecast { label: string; probability: number | null; low: number | null; high: number | null; value: number | null; horizon_s: number | null; drivers: { feature: string; contribution: number }[] }
export interface Predictions {
  match_id: string; at_ms: number; feature_cutoff_ms: number | null; model_version: string | null; model_cutoff?: string | null;
  mode?: PredMode; mode_note?: string | null;
  prematch?: Record<string, { elo_for: number | null; elo_against: number | null; elo_diff: number | null; form_ppg_for: number | null; form_gd_for: number | null; rated_games_min: number | null }>;
  phase: "regulation" | "extra time" | null; phase_remaining_s: number | null;
  teams: Record<string, Partial<Record<"goal_next_10m" | "corner_next_2m" | "penalty_next_5m" | "win_phase" | "expected_goals_rest", Forecast>>>;
  draw_phase: Forecast | null; notes: string[];
}
export interface PredSeries {
  win: Record<string, { t_ms: number; p: number }[]>; draw: { t_ms: number; p: number }[];
  xg: Record<string, { ours: number; statsbomb: number; points: { t_ms: number; ours: number; statsbomb: number; goal: boolean }[] }>;
}
export interface TeamValues { xg: number; xg_statsbomb: number; shots: number; goals: number; passes: number; passes_completed: number; pass_completion_pct: number | null; xpass_pct: number | null; completion_above_expected_pct: number | null; xt_added: number }
export interface ModelValues {
  model_version: string | null; teams: Record<string, TeamValues>;
  shots: { event_id: string; match_elapsed_ms: number; team_id: string; player_name: string | null; xg: number; xg_lo: number; xg_hi: number; xg_statsbomb: number | null; is_goal: boolean }[];
  top_xt_players: { team_id: string; player_id: string; name: string | null; xt_added: number; actions: number }[];
}
export interface ModelCards {
  model_version: string | null; versions: string[]; cutoff: string | null; priors: string; test_competitions: string[]; test: string;
  mode?: PredMode; mode_note?: string | null;
  models: { name: string; kind: string; horizon_s: number | null; train_rows: number; train_matches: number; train_window: [string, string]; features: string[]; mlflow_registered: boolean }[];
  metrics: Record<string, Record<string, number>>;
  calibration: Record<string, { mean_pred: number; obs_rate: number; n: number }[]>;
}
/** strict: chronological forecast (only what was knowable); retrospective: labelled cross-fit. */
export type PredMode = "strict" | "retrospective";
const mq = (mode: PredMode) => (mode === "strict" ? "" : `&mode=${mode}`);
export const predApi = {
  latest: (id: string, at: number, mode: PredMode = "strict") => get<Predictions>(`/v1/matches/${enc(id)}/predictions?at_ms=${Math.floor(at)}${mq(mode)}`),
  series: (id: string, at: number, mode: PredMode = "strict") => get<PredSeries>(`/v1/matches/${enc(id)}/predictions/series?at_ms=${Math.floor(at)}${mq(mode)}`),
  values: (id: string, at: number, mode: PredMode = "strict") => get<ModelValues>(`/v1/matches/${enc(id)}/model-values?at_ms=${Math.floor(at)}${mq(mode)}`),
  models: (version?: string | null, mode: PredMode = "strict") =>
    get<ModelCards>(`/v1/models?${version ? `version=${enc(version)}` : ""}${mq(mode)}`),
};

// ---- shots
export interface BallFlight {
  available: boolean; reason?: string; curve_measurable?: boolean; curve_reason?: string | null; estimated?: boolean; note?: string | null;
  curve_deg?: number | null; bend?: "left" | "right" | "straight" | null; swerve_m?: number | null;
  speed_kmh?: number | null; launch_deg?: number | null; peak_height_m?: number | null; height_at_line_m?: number | null;
  lateral_at_line_m?: number | null; flight_ms?: number; distance_m?: number; samples?: number; observed_pct?: number;
  fit_residual_m?: number; confidence?: "high" | "medium" | "low"; reached_goal_line?: boolean; source?: string;
  path?: [number, number, number, number | null, number][];
}
export interface ShotRow {
  event_id: string; match_elapsed_ms: number; clock_label: string; period: number; team_id: string | null; player_id: string | null;
  player_name: string | null; type: string | null; outcome: string | null; is_goal: boolean; on_target: boolean; blocked: boolean;
  under_pressure: boolean; play_pattern: string | null; x_m: number; y_m: number; end_x_m: number | null; end_y_m: number | null;
  distance_m: number; angle_deg: number; centrality_deg: number; depth_m: number; lateral_m: number; zone: string; placement: string | null;
  xg: number | null; xg_lo: number | null; xg_hi: number | null; xg_statsbomb: number | null; difficulty: string | null;
  has_360: boolean; defenders_in_cone: number | null; nearest_defender_m: number | null; keeper_off_line_m: number | null; keeper_in_cone: boolean | null;
  flight?: BallFlight;
}
export interface ShotTeam {
  shots: number; on_target: number; blocked: number; goals: number; accuracy_pct: number | null; conversion_pct: number | null; xg: number | null;
  xg_per_shot: number | null; goals_minus_xg: number | null; avg_distance_m: number | null; avg_angle_deg: number | null; big_chances: number;
  under_pressure_pct: number | null; zones: Record<"six-yard box" | "penalty area" | "outside the box", number>;
}
export interface Shots { match_id: string; at_ms: number; model_version: string | null; shots: ShotRow[]; teams: Record<string, ShotTeam> }
export const shotsApi = {
  list: (id: string, at: number) => get<Shots>(`/v1/matches/${enc(id)}/shots?at_ms=${Math.floor(at)}`),
  flight: (id: string, ev: string, at: number) => get<{ event_id: string } & BallFlight>(`/v1/matches/${enc(id)}/shots/${enc(ev)}/flight?at_ms=${Math.floor(at)}`),
};

// ---- agents (Match Strategist, Moment Explainer)
async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    let detail = `${r.status}`;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.json();
}
export interface AgentToolCall { name: string; arguments: Record<string, unknown>; ok: boolean; chars: number }
interface AgentRun { thread_id: string; run_id: string; agent_id: string; model: string | null; at_ms: number; replay_clock: string; tool_calls: AgentToolCall[]; seconds: number }
export interface AgentAnswer extends AgentRun { answer: string }
export interface MomentCard {
  headline: string; what_is_happening: string; main_risk: string; one_action: string; confidence: "high" | "medium" | "low";
  evidence: { source: string; detail: string }[];
}
export interface AgentExplain extends AgentRun { card: MomentCard | null; raw: string }
export interface AgentStatus { configured: boolean; endpoint?: string; model?: string; agents: Record<string, { name: string; id: string }> }
export const agentApi = {
  status: () => get<AgentStatus>("/v1/agents"),
  ask: (id: string, at: number, question: string, threadId?: string | null) =>
    post<AgentAnswer>(`/v1/matches/${enc(id)}/agents/ask`, { question, at_ms: Math.floor(at), thread_id: threadId ?? null }),
  explain: (id: string, at: number) => post<AgentExplain>(`/v1/matches/${enc(id)}/agents/explain`, { at_ms: Math.floor(at) }),
};

// ---- insights + coach analytics
export type InsightCategory = "event" | "momentum" | "pressing" | "model" | "tactical" | "physical" | "player" | "discipline" | "set_piece";
export interface BestRow { player_id: string; name: string; jersey: number | null; role: string; score: number; why: string[] }
export interface SubOption {
  off: { player_id: string; name: string; role: string; minutes: number; flags: string[] };
  on: { player_id: string; name: string; role: string; history: Record<string, number> } | null;
  urgency: "high" | "medium"; score: number; why_off: string[]; why_on: string[];
}
export interface Insight {
  id: string; t_ms: number; clock_label: string; minute: string; category: InsightCategory; kind: string; priority: 1 | 2 | 3;
  team_id: string | null; title: string; detail: string; evidence: string[]; player: string | null; seek_ms: number; source: string;
  subject: null
    | { type: "player"; player_id: string; name: string; team_id: string; role: string; flags: string[]; reasons: string[]; stats: Record<string, number | null> }
    | { type: "substitution"; team_id: string; context: string; remaining: number; options: SubOption[] }
    | { type: "best_player"; team_id: string; situation: Situation; ranked: BestRow[] };
}
export interface InsightList { match_id: string; at_ms: number; replay_clock: string; insights: Insight[]; sources: string[]; partial: boolean }
export type Situation = "penalty" | "corner" | "free_kick" | "counter" | "defend";
export interface PlayerRow {
  player_id: string; name: string; team_id: string; jersey: number | null; on_pitch: boolean; minutes: number; role: string; role_source: string;
  booked: boolean; sent_off: boolean; stats: Record<string, number | null>; impact: number; impact_per15: number;
  recent_per15: number | null; earlier_per15: number | null; flags: string[]; reasons: string[];
  physical: Record<string, number | null> | null; history: Record<string, number | null> | null;
}
export interface CoachSources { history: string; model_values: boolean; physical: boolean; positions: boolean }
export interface PlayersResp { replay_clock: string; teams: Record<string, PlayerRow[]>; sources: CoachSources }
export interface SubsResp { team_id: string; remaining: number; made: number; context: string; options: SubOption[]; note: string | null; replay_clock: string; sources: CoachSources }
export interface BestResp { team_id: string; situation: Situation; ranked: BestRow[]; basis: string; replay_clock: string; sources: CoachSources }
export interface TeamProfile {
  matches: number; for: Record<string, number | null>; against: Record<string, number | null>;
  key_players: { player_id: string; name: string | null; matches: number; goals: number; xg: number; shots: number; def_actions: number; yellows: number }[];
  yellow_carriers: { player_id: string; name: string | null; yellows: number; matches: number }[];
}
export interface PrematchProfile { status: string; teams: Record<string, TeamProfile>; tournament_average?: Record<string, number>; teams_in_reference?: number; note?: string }
export const coachApi = {
  insights: (id: string, at: number) => get<InsightList>(`/v1/matches/${enc(id)}/insights?at_ms=${Math.floor(at)}`),
  insightAi: (id: string, insightId: string) => post<AgentExplain & { insight_id: string }>(`/v1/matches/${enc(id)}/insights/${enc(insightId)}/ai`, {}),
  players: (id: string, at: number, team?: string) => get<PlayersResp>(`/v1/matches/${enc(id)}/players?at_ms=${Math.floor(at)}${team ? `&team=${enc(team)}` : ""}`),
  subs: (id: string, at: number, team: string) => get<SubsResp>(`/v1/matches/${enc(id)}/players/substitutions?at_ms=${Math.floor(at)}&team=${enc(team)}`),
  best: (id: string, at: number, team: string, situation: Situation) =>
    get<BestResp>(`/v1/matches/${enc(id)}/players/best?at_ms=${Math.floor(at)}&team=${enc(team)}&situation=${situation}`),
  prematch: (id: string) => get<PrematchProfile>(`/v1/matches/${enc(id)}/prematch/profile`),
};
