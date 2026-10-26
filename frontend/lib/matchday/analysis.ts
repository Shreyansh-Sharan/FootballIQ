// Fetchers and polling hooks for the analysis tabs; `at_ms` is the replay clock floored to a bucket.
// Chat, explainer and AI-take state live in per-match module stores so they survive tab switches.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { API_URL } from "../api";
import { HttpError, type Status } from "./api";
import { CLOCK, useClock } from "./clock";
import { onHandoff, type CoachSection } from "./handoff";

// ------------------------------------------------------------------ wire types
export interface FormRow {
  match_id: string; date: string; stage: string | null; competition?: string; opponent: string; opponent_id?: string;
  venue: string; score: string; pens: string | null; result: "W" | "D" | "L"; goals_for?: number; goals_against?: number;
}
export interface HistorySummary { played: number; won: number; drawn: number; lost: number; goals_for: number; goals_against: number }
export interface History {
  cutoff_date: string; cutoff_rule: string; coverage: string;
  teams: Record<string, { team_id: string; name: string; form: FormRow[]; summary: HistorySummary }>;
  head_to_head: FormRow[];
}
export interface TeamProfile {
  matches: number; for: Record<string, number | null>; against: Record<string, number | null>;
  key_players: { player_id: string; name: string | null; matches: number; goals: number; xg: number; shots: number; def_actions: number; yellows: number }[];
  yellow_carriers: { player_id: string; name: string | null; yellows: number; matches: number }[];
}
export interface PrematchProfile { status: string; teams: Record<string, TeamProfile>; tournament_average?: Record<string, number>; teams_in_reference?: number; note?: string }

export interface TacticalWindowRef { window_id: string; label: string; start_ms: number; end_ms: number; available: boolean; in_progress: boolean }
export interface TacticalMetrics {
  possession_pct: number | null; links_per_sample: number | null; lane_clearance_pct: number | null;
  triangles_per_sample: number | null; quads_per_sample: number | null; pentagons_per_sample: number | null;
  width_in_possession_m: number | null; depth_in_possession_m: number | null;
  width_out_of_possession_m: number | null; depth_out_of_possession_m: number | null;
  regains: number | null; formation: string | null; declared_formation: string | null; samples: number; possession_samples: number;
  possession_pct_statsbomb: number | null; possession_agree_statsbomb_pct: number | null; start_ms: number; end_ms: number;
  viable_triangles_per_sample?: number | null; viable_quads_per_sample?: number | null; viable_pentagons_per_sample?: number | null;
  best_motif_score_mean?: number | null;
}
export interface NetNode { player_id: string; x_m: number; y_m: number; passes: number }
export interface TacticalWindow {
  team_id: string; window_id: string; label: string; metrics: TacticalMetrics;
  network: { nodes: NetNode[]; edges: { from: string; to: string; passes: number }[] };
  heatmap: { cx: number; cy: number; samples: number }[];
  regains: { zx: number; zy: number; regains: number }[];
  definitions: Record<string, string>;
}
export interface TimelineRow {
  window_id: string; label: string; team_id: string; start_ms: number; end_ms: number; formation: string | null; declared_formation: string | null;
  possession_pct: number | null; possession_pct_statsbomb: number | null; possession_agree_statsbomb_pct: number | null;
  width_in_possession_m: number | null; depth_in_possession_m: number | null;
}
export interface FormationSegment { team_id: string; start_ms: number; end_ms: number; raw_formation: string | null; confidence: number; formation: string | null }
export interface FormationSwitch { team_id: string; at_ms: number; from_formation: string; to_formation: string }
export interface Formations { segments: FormationSegment[]; switches: FormationSwitch[]; method: string }
export interface PhysicalRow {
  team_id: string; side: "home" | "away"; jersey: string; player_id: string | null; name: string | null; position_group: string | null;
  distance_km: number; hsr_km: number; sprint_km: number; top_speed_kmh: number; minutes_tracked: number; observed_pct: number | null; on_pitch: boolean;
}
export interface PhysicalResp { hsr_threshold_mps?: number; sprint_threshold_mps?: number; source?: string; players: PhysicalRow[] }

export type PredMode = "strict" | "retrospective";
export interface Forecast { label: string; probability: number | null; low: number | null; high: number | null; value: number | null; horizon_s: number | null; drivers: { feature: string; contribution: number }[] }
export type ForecastKey = "goal_next_10m" | "corner_next_2m" | "penalty_next_5m" | "win_phase" | "expected_goals_rest";
export interface Predictions {
  match_id: string; at_ms: number; feature_cutoff_ms: number | null; model_version: string | null; model_cutoff?: string | null;
  mode?: PredMode; mode_note?: string | null;
  prematch?: Record<string, { elo_for: number | null; elo_against: number | null; elo_diff: number | null; form_ppg_for: number | null; form_gd_for: number | null; rated_games_min: number | null }>;
  phase: "regulation" | "extra time" | null; phase_remaining_s: number | null;
  teams: Record<string, Partial<Record<ForecastKey, Forecast>>>;
  draw_phase: Forecast | null; notes: string[];
}
export interface PredSeries {
  win: Record<string, { t_ms: number; p: number }[]>; draw: { t_ms: number; p: number }[];
  xg: Record<string, { ours: number; statsbomb: number; points: { t_ms: number; ours: number; statsbomb: number; goal: boolean }[] }>;
}
export interface TeamValues {
  xg: number; xg_statsbomb: number; shots: number; goals: number; passes: number; passes_completed: number;
  pass_completion_pct: number | null; xpass_pct: number | null; completion_above_expected_pct: number | null; xt_added: number;
}
export interface ModelValues {
  model_version: string | null; teams: Record<string, TeamValues>;
  top_xt_players: { team_id: string; player_id: string; name: string | null; xt_added: number; actions: number }[];
}
export interface ModelCards {
  model_version: string | null; versions: string[]; cutoff: string | null; priors: string; test_competitions: string[]; test: string;
  mode?: PredMode; mode_note?: string | null;
  models: { name: string; kind: string; horizon_s: number | null; train_rows: number; train_matches: number; train_window: [string, string]; features: string[] }[];
  metrics: Record<string, Record<string, number>>;
  calibration: Record<string, { mean_pred: number; obs_rate: number; n: number }[]>;
}

export interface BallFlight {
  available: boolean; reason?: string; curve_measurable?: boolean; curve_reason?: string | null; estimated?: boolean; note?: string | null;
  curve_deg?: number | null; bend?: "left" | "right" | "straight" | null; swerve_m?: number | null;
  speed_kmh?: number | null; launch_deg?: number | null; peak_height_m?: number | null; height_at_line_m?: number | null;
  flight_ms?: number; distance_m?: number; samples?: number; observed_pct?: number; confidence?: "high" | "medium" | "low";
  path?: [number, number, number, number | null, number][];
}
export interface ShotRow {
  event_id: string; match_elapsed_ms: number; clock_label: string; period: number; team_id: string | null; player_id: string | null;
  player_name: string | null; type: string | null; outcome: string | null; is_goal: boolean; on_target: boolean; blocked: boolean;
  under_pressure: boolean; play_pattern: string | null; x_m: number; y_m: number; end_x_m: number | null; end_y_m: number | null;
  distance_m: number; angle_deg: number; centrality_deg: number; zone: string; placement: string | null;
  xg: number | null; xg_lo: number | null; xg_hi: number | null; xg_statsbomb: number | null; difficulty: string | null;
  has_360: boolean; defenders_in_cone: number | null; nearest_defender_m: number | null; keeper_off_line_m: number | null;
  flight?: BallFlight;
}
export interface ShotTeam {
  shots: number; on_target: number; blocked: number; goals: number; accuracy_pct: number | null; conversion_pct: number | null; xg: number | null;
  xg_per_shot: number | null; goals_minus_xg: number | null; avg_distance_m: number | null; avg_angle_deg: number | null; big_chances: number;
  under_pressure_pct: number | null; zones: Record<string, number>;
}
export interface ShotsResp { at_ms: number; model_version: string | null; shots: ShotRow[]; teams: Record<string, ShotTeam> }

export interface AgentToolCall { name: string; arguments: Record<string, unknown>; ok: boolean }
interface AgentRun { thread_id: string; model: string | null; at_ms: number; replay_clock: string; tool_calls: AgentToolCall[]; seconds: number }
export interface AgentAnswer extends AgentRun { answer: string }
export interface MomentCard {
  headline: string; what_is_happening: string; main_risk: string; one_action: string; confidence: "high" | "medium" | "low";
  evidence: { source: string; detail: string }[];
}
export interface AgentExplain extends AgentRun { card: MomentCard | null; raw: string }
export interface AgentStatus { configured: boolean; model?: string; agents: Record<string, { name: string; id: string }> }

export type InsightCategory = "event" | "momentum" | "pressing" | "model" | "tactical" | "physical" | "player" | "discipline" | "set_piece";
export type Situation = "penalty" | "corner" | "free_kick" | "counter" | "defend";
export interface BestRow { player_id: string; name: string; jersey: number | null; role: string; score: number; why: string[] }
export interface SubOption {
  off: { player_id: string; name: string; role: string; minutes: number; flags: string[] };
  on: { player_id: string; name: string; role: string; history: Record<string, number | null> } | null;
  urgency: "high" | "medium"; score: number; why_off: string[]; why_on: string[];
}
export interface Insight {
  id: string; t_ms: number; clock_label: string; minute: string; category: InsightCategory | string; kind: string; priority: 1 | 2 | 3;
  team_id: string | null; title: string; detail: string; evidence: string[]; player: string | null; seek_ms: number | null; source: string;
  subject: null
    | { type: "player"; player_id: string; name: string; team_id: string; role: string; flags: string[]; reasons: string[]; stats: Record<string, number | null> }
    | { type: "substitution"; team_id: string; context: string; remaining: number; options: SubOption[] }
    | { type: "best_player"; team_id: string; situation: Situation; ranked: BestRow[] };
}
export interface InsightList { at_ms: number; replay_clock: string; insights: Insight[]; sources: string[]; partial: boolean }
export interface CoachSources { history: string; model_values: boolean; physical: boolean; positions: boolean }
export interface PlayerRow {
  player_id: string; name: string; team_id: string; jersey: number | null; on_pitch: boolean; minutes: number; role: string; role_source: string;
  booked: boolean; sent_off: boolean; stats: Record<string, number | null>; impact: number; impact_per15: number;
  recent_per15: number | null; earlier_per15: number | null; flags: string[]; reasons: string[];
  physical: Record<string, number | null> | null; history: Record<string, number | null> | null;
}
export interface PlayersResp { replay_clock: string; teams: Record<string, PlayerRow[]>; sources: CoachSources }
export interface SubsResp { team_id: string; remaining: number; made: number; context: string; options: SubOption[]; note: string | null; sources: CoachSources }
export interface BestResp { team_id: string; situation: Situation; ranked: BestRow[]; basis: string; sources: CoachSources }

// ------------------------------------------------------------------ fetchers
async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!r.ok) throw new HttpError(r.status, path);
  return r.json() as Promise<T>;
}
async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
  if (!r.ok) throw new HttpError(r.status, path);
  return r.json() as Promise<T>;
}
const enc = encodeURIComponent;
const mm = (id: string) => `/v1/matches/${enc(id)}`;
const at_ = (v: number) => Math.max(0, Math.floor(v));
const modeQ = (mode: PredMode) => (mode === "strict" ? "" : `&mode=${mode}`);

export const anApi = {
  history: (id: string) => getJSON<History>(`${mm(id)}/history`),
  prematch: (id: string) => getJSON<PrematchProfile>(`${mm(id)}/prematch/profile`),
  windows: (id: string, at: number) => getJSON<{ windows: TacticalWindowRef[] }>(`${mm(id)}/tactical/windows?at_ms=${at_(at)}`),
  window: (id: string, team: string, win: string, at: number) => getJSON<TacticalWindow>(`${mm(id)}/tactical?team=${enc(team)}&window=${enc(win)}&at_ms=${at_(at)}`),
  timeline: (id: string, at: number) => getJSON<{ windows: TimelineRow[] }>(`${mm(id)}/tactical/timeline?at_ms=${at_(at)}`),
  formations: (id: string, at: number) => getJSON<Formations>(`${mm(id)}/tactical/formations?at_ms=${at_(at)}`),
  physical: (id: string, at: number) => getJSON<PhysicalResp>(`${mm(id)}/physical?at_ms=${at_(at)}`),
  predictions: (id: string, at: number, mode: PredMode = "strict") => getJSON<Predictions>(`${mm(id)}/predictions?at_ms=${at_(at)}${modeQ(mode)}`),
  predSeries: (id: string, at: number, mode: PredMode = "strict") => getJSON<PredSeries>(`${mm(id)}/predictions/series?at_ms=${at_(at)}${modeQ(mode)}`),
  modelValues: (id: string, at: number, mode: PredMode = "strict") => getJSON<ModelValues>(`${mm(id)}/model-values?at_ms=${at_(at)}${modeQ(mode)}`),
  models: (version: string | null, mode: PredMode = "strict") => getJSON<ModelCards>(`/v1/models?${version ? `version=${enc(version)}` : ""}${modeQ(mode)}`),
  shots: (id: string, at: number) => getJSON<ShotsResp>(`${mm(id)}/shots?at_ms=${at_(at)}`),
  flight: (id: string, ev: string, at: number) => getJSON<{ event_id: string } & BallFlight>(`${mm(id)}/shots/${enc(ev)}/flight?at_ms=${at_(at)}`),
  agents: () => getJSON<AgentStatus>("/v1/agents"),
  ask: (id: string, at: number, question: string, threadId: string | null) =>
    postJSON<AgentAnswer>(`${mm(id)}/agents/ask`, { question, at_ms: at_(at), thread_id: threadId }),
  explain: (id: string, at: number) => postJSON<AgentExplain>(`${mm(id)}/agents/explain`, { at_ms: at_(at) }),
  insights: (id: string, at: number) => getJSON<InsightList>(`${mm(id)}/insights?at_ms=${at_(at)}`),
  insightAi: (id: string, insightId: string) => postJSON<AgentExplain & { insight_id: string }>(`${mm(id)}/insights/${enc(insightId)}/ai`, {}),
  players: (id: string, at: number, team: string) => getJSON<PlayersResp>(`${mm(id)}/players?at_ms=${at_(at)}&team=${enc(team)}`),
  subs: (id: string, at: number, team: string) => getJSON<SubsResp>(`${mm(id)}/players/substitutions?at_ms=${at_(at)}&team=${enc(team)}`),
  best: (id: string, at: number, team: string, situation: Situation) =>
    getJSON<BestResp>(`${mm(id)}/players/best?at_ms=${at_(at)}&team=${enc(team)}&situation=${situation}`),
};

/** 404 / 501 / 503: not available (yet) for this match. */
export const isUnavailable = (e: unknown) => e instanceof HttpError && (e.status === 404 || e.status === 501 || e.status === 503);
const errStatus = (e: unknown): Status => (isUnavailable(e) ? "missing" : "error");

// ------------------------------------------------------------------ polling hooks
export interface Polled<T> { data: T | null; status: Status; at: number | null }

/** Polls `fetcher(at)` with `at` = clock floored to `step` (or `atOf`, clamped to the clock); hides data later than the clock. */
export function useBucketed<T>(key: string | null, fetcher: (at: number) => Promise<T>, o: { step?: number; atOf?: (t: number) => number; interval?: number } = {}): Polled<T> {
  const [st, setSt] = useState<{ data: T | null; status: Status; at: number | null; key: string | null }>({ data: null, status: "loading", at: null, key: null });
  const f = useRef(fetcher);
  f.current = fetcher;
  const opts = useRef(o);
  opts.current = o;
  useEffect(() => {
    setSt({ data: null, status: "loading", at: null, key });
    if (!key) return;
    let alive = true;
    let inFlight = false;
    let lastAt = -1;
    let retryAt = 0;
    let ok = false;
    const tick = async () => {
      if (!alive || inFlight || !CLOCK.ready || performance.now() < retryAt) return;
      const t = Math.max(0, Math.floor(CLOCK.t));
      const step = opts.current.step ?? 15000;
      const want = opts.current.atOf ? opts.current.atOf(t) : Math.floor(t / step) * step;
      const at = Math.max(0, Math.min(t, Math.floor(want)));
      if (at === lastAt) return;
      inFlight = true;
      try {
        const d = await f.current(at);
        if (!alive) return;
        lastAt = at;
        ok = true;
        setSt({ data: d, status: "ready", at, key });
      } catch (e) {
        if (!alive) return;
        retryAt = performance.now() + (isUnavailable(e) ? 15000 : 5000);
        if (!ok) setSt({ data: null, status: errStatus(e), at: null, key });
      } finally {
        inFlight = false;
      }
    };
    void tick();
    const id = setInterval(tick, opts.current.interval ?? 500);
    const off = CLOCK.onSeek(() => void tick());
    return () => {
      alive = false;
      clearInterval(id);
      off();
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const clock = useClock();
  const mine = st.key === key;
  const visible = mine && st.at != null && st.at <= clock.t + 1 ? st.data : null;
  const status: Status = !mine ? "loading" : visible ? "ready" : st.status === "ready" ? "loading" : st.status;
  return { data: visible, status, at: visible ? st.at : null };
}

/** One fetch per key; retries after 5 s (15 s when unavailable). */
export function useOnce<T>(key: string | null, fetcher: () => Promise<T>): { data: T | null; status: Status } {
  const [st, setSt] = useState<{ data: T | null; status: Status; key: string | null }>({ data: null, status: "loading", key: null });
  const f = useRef(fetcher);
  f.current = fetcher;
  useEffect(() => {
    setSt({ data: null, status: "loading", key });
    if (!key) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const load = () => f.current().then(
      (d) => alive && setSt({ data: d, status: "ready", key }),
      (e) => {
        if (!alive) return;
        setSt({ data: null, status: errStatus(e), key });
        timer = setTimeout(load, isUnavailable(e) ? 15000 : 5000);
      },
    );
    void load();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [key]);
  return st.key === key ? { data: st.data, status: st.status } : { data: null, status: "loading" };
}

export const useHistory = (matchId: string | null) => useOnce<History>(matchId ? `h|${matchId}` : null, () => anApi.history(matchId!));

/** Polls every 10 s (15 s after an error) until the server-built profile is ready or failed. */
export function usePrematchProfile(matchId: string | null): { data: PrematchProfile | null; status: Status } {
  const [st, setSt] = useState<{ data: PrematchProfile | null; status: Status; id: string | null }>({ data: null, status: "loading", id: null });
  useEffect(() => {
    setSt({ data: null, status: "loading", id: matchId });
    if (!matchId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const load = () => anApi.prematch(matchId).then(
      (p) => {
        if (!alive) return;
        setSt({ data: p, status: "ready", id: matchId });
        if (p.status !== "ready" && p.status !== "failed") timer = setTimeout(load, 10000);
      },
      (e) => {
        if (!alive) return;
        setSt((s) => ({ data: s.data, status: s.data ? "ready" : errStatus(e), id: matchId }));
        timer = setTimeout(load, 15000);
      },
    );
    void load();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [matchId]);
  return st.id === matchId ? { data: st.data, status: st.status } : { data: null, status: "loading" };
}

export function useTacticalWindows(matchId: string | null) {
  const windows = useBucketed(matchId ? `tw|${matchId}` : null, (at) => anApi.windows(matchId!, at), { step: 30000 });
  const timeline = useBucketed(matchId ? `tt|${matchId}` : null, (at) => anApi.timeline(matchId!, at), { step: 30000 });
  const formations = useBucketed(matchId ? `tf|${matchId}` : null, (at) => anApi.formations(matchId!, at), { step: 60000 });
  return { windows, timeline, formations };
}

/** One team/window board, fetched at the window end once the clock has passed it. */
export function useTacticalWindow(matchId: string | null, teamId: string, win: TacticalWindowRef | undefined, t: number): { data: TacticalWindow | null; status: Status } {
  const done = !!win && win.available && win.end_ms <= t;
  const key = matchId && done ? `${matchId}|${teamId}|${win!.window_id}` : null;
  const endMs = win?.end_ms ?? 0;
  const winId = win?.window_id ?? "";
  return useOnce<TacticalWindow>(key, () => anApi.window(matchId!, teamId, winId, endMs));
}

export const usePhysical = (matchId: string | null, enabled = true) =>
  useBucketed(matchId && enabled ? `ph|${matchId}` : null, (at) => anApi.physical(matchId!, at), { step: 5000 });

// Shared across mounts; cleared on error.
let agentStatusCache: Promise<AgentStatus> | null = null;
export function useAgentStatus(): { data: AgentStatus | null; status: Status } {
  const [st, setSt] = useState<{ data: AgentStatus | null; status: Status }>({ data: null, status: "loading" });
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const load = () => {
      agentStatusCache = agentStatusCache ?? anApi.agents();
      agentStatusCache.then(
        (d) => alive && setSt({ data: d, status: "ready" }),
        (e) => {
          agentStatusCache = null;
          if (!alive) return;
          setSt({ data: null, status: errStatus(e) });
          timer = setTimeout(load, 15000);
        },
      );
    };
    load();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, []);
  return st;
}

// ------------------------------------------------------------------ module stores
function store<S>(init: S) {
  let s = init;
  const subs = new Set<() => void>();
  return {
    get: () => s,
    set: (next: S | ((p: S) => S)) => {
      s = typeof next === "function" ? (next as (p: S) => S)(s) : next;
      subs.forEach((f) => f());
    },
    subscribe: (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; },
  };
}
function useStore<S>(st: ReturnType<typeof store<S>>): S {
  return useSyncExternalStore(st.subscribe, st.get, st.get);
}

// ---- insights + AI takes
/** Insights at or before the clock, polled in 10 s buckets. */
export function useInsights(matchId: string | null): { list: InsightList | null; insights: Insight[]; status: Status } {
  const r = useBucketed<InsightList>(matchId ? `ins|${matchId}` : null, (at) => anApi.insights(matchId!, at), { step: 10000 });
  const clock = useClock();
  const t = clock.t;
  const insights = useMemo(() => (r.data?.insights ?? []).filter((i) => i.t_ms <= t).sort((a, b) => a.t_ms - b.t_ms), [r.data, t]);
  return { list: r.data, insights, status: r.status };
}

/** Insights the clock just crossed while playing (not ones a seek skipped), newest first; for toasts. */
export function useFreshInsights(insights: Insight[], opts: { minPriority?: 1 | 2 | 3; windowMs?: number; max?: number } = {}): { fresh: Insight[]; dismiss: (id: string) => void } {
  const { minPriority = 2, windowMs = 45000, max = 3 } = opts;
  const clock = useClock();
  const t = clock.t;
  const [fresh, setFresh] = useState<Insight[]>([]);
  const seen = useRef(new Set<string>());
  const lastT = useRef<number | null>(null);
  useEffect(() => {
    const prev = lastT.current;
    lastT.current = t;
    const jumped = prev == null || t < prev || t - prev > 60000;
    const cands = insights.filter((i) => !seen.current.has(i.id));
    cands.forEach((i) => seen.current.add(i.id));
    if (jumped) { setFresh((f) => f.filter((i) => i.t_ms <= t)); return; }
    const pop = cands.filter((i) => t - i.t_ms <= windowMs && i.priority <= minPriority).reverse();
    if (pop.length) setFresh((f) => [...pop, ...f.filter((i) => i.t_ms <= t)].slice(0, max));
  }, [t, insights, minPriority, windowMs, max]);
  const dismiss = useCallback((id: string) => setFresh((f) => f.filter((i) => i.id !== id)), []);
  return { fresh, dismiss };
}

export interface AiTake { state: "loading" | "done" | "error"; data?: AgentExplain & { insight_id?: string } }
const aiStore = store<{ matchId: string | null; takes: Record<string, AiTake>; queue: string[]; busy: boolean }>({ matchId: null, takes: {}, queue: [], busy: false });

function pumpAi() {
  const s = aiStore.get();
  if (s.busy || !s.matchId || !s.queue.length) return;
  const [id, ...rest] = s.queue;
  const matchId = s.matchId;
  aiStore.set({ ...s, queue: rest, busy: true, takes: { ...s.takes, [id]: { state: "loading" } } });
  anApi.insightAi(matchId, id).then(
    (data) => { if (aiStore.get().matchId === matchId) aiStore.set((p) => ({ ...p, takes: { ...p.takes, [id]: { state: "done", data } } })); },
    () => { if (aiStore.get().matchId === matchId) aiStore.set((p) => ({ ...p, takes: { ...p.takes, [id]: { state: "error" } } })); },
  ).finally(() => {
    if (aiStore.get().matchId === matchId) aiStore.set((p) => ({ ...p, busy: false }));
    pumpAi();
  });
}

/** AI takes on insights: one request at a time, cached per insight id and shared across panels. */
export function useAiTake(matchId: string | null): { takes: Record<string, AiTake>; request: (insightId: string) => void } {
  const s = useStore(aiStore);
  useEffect(() => {
    if (matchId && aiStore.get().matchId !== matchId) aiStore.set({ matchId, takes: {}, queue: [], busy: false });
  }, [matchId]);
  const request = useCallback((insightId: string) => {
    if (!matchId) return;
    const cur = aiStore.get();
    if (cur.matchId !== matchId) aiStore.set({ matchId, takes: {}, queue: [], busy: false });
    const now = aiStore.get();
    const have = now.takes[insightId];
    if ((have && have.state !== "error") || now.queue.includes(insightId)) return;
    aiStore.set({ ...now, queue: [...now.queue, insightId] });
    pumpAi();
  }, [matchId]);
  return { takes: s.matchId === matchId ? s.takes : {}, request };
}

// ---- Strategist chat
export interface Turn { id: number; q: string; askedAt: number; a?: AgentAnswer; error?: "unavailable" | "failed" }
const chatStore = store<{ matchId: string | null; turns: Turn[]; thread: string | null; busy: boolean }>({ matchId: null, turns: [], thread: null, busy: false });
let turnSeq = 0;

export function useChat(matchId: string | null) {
  const s = useStore(chatStore);
  useEffect(() => {
    if (matchId && chatStore.get().matchId !== matchId) chatStore.set({ matchId, turns: [], thread: null, busy: false });
  }, [matchId]);
  const mine = s.matchId === matchId;
  const ask = useCallback(async (question: string) => {
    const text = question.trim();
    if (!matchId || !text) return;
    let cur = chatStore.get();
    if (cur.matchId !== matchId) { chatStore.set({ matchId, turns: [], thread: null, busy: false }); cur = chatStore.get(); }
    if (cur.busy) return;
    const at = Math.floor(CLOCK.t);
    const id = ++turnSeq;
    chatStore.set({ ...cur, busy: true, turns: [...cur.turns, { id, q: text, askedAt: at }] });
    try {
      const a = await anApi.ask(matchId, at, text, cur.thread);
      if (chatStore.get().matchId !== matchId) return;
      chatStore.set((p) => ({ ...p, thread: a.thread_id ?? p.thread, turns: p.turns.map((x) => (x.id === id ? { ...x, a } : x)) }));
    } catch (e) {
      if (chatStore.get().matchId !== matchId) return;
      chatStore.set((p) => ({ ...p, turns: p.turns.map((x) => (x.id === id ? { ...x, error: isUnavailable(e) ? "unavailable" : "failed" } : x)) }));
    } finally {
      if (chatStore.get().matchId === matchId) chatStore.set((p) => ({ ...p, busy: false }));
    }
  }, [matchId]);
  const reset = useCallback(() => { if (matchId) chatStore.set({ matchId, turns: [], thread: null, busy: false }); }, [matchId]);
  return { turns: mine ? s.turns : [], thread: mine ? s.thread : null, busy: mine && s.busy, ask, reset };
}

// ---- Moment Explainer
const explainStore = store<{ matchId: string | null; res: AgentExplain | null; error: "unavailable" | "failed" | null; busy: boolean; askedAt: number | null }>(
  { matchId: null, res: null, error: null, busy: false, askedAt: null });
let pendingExplain = false;
let pendingCoach: { teamSide: 0 | 1 | null; playerId: string | null } | null = null;
if (typeof window !== "undefined") {
  // Handoffs can arrive before the target tab mounts.
  onHandoff((h) => {
    if (h.type === "explain") pendingExplain = true;
    if (h.type === "coach") pendingCoach = { teamSide: h.teamSide ?? null, playerId: h.playerId ?? null };
  });
}
/** Consumes a pending "explain this moment" handoff. */
export function takePendingExplain(): boolean { const p = pendingExplain; pendingExplain = false; return p; }
/** Consumes a pending coach handoff (null when none). */
export function takePendingCoach(): { teamSide: 0 | 1 | null; playerId: string | null } | null { const p = pendingCoach; pendingCoach = null; return p; }

export function useExplainer(matchId: string | null) {
  const s = useStore(explainStore);
  useEffect(() => {
    if (matchId && explainStore.get().matchId !== matchId) explainStore.set({ matchId, res: null, error: null, busy: false, askedAt: null });
  }, [matchId]);
  const mine = s.matchId === matchId;
  const run = useCallback(async () => {
    if (!matchId) return;
    if (explainStore.get().matchId !== matchId) explainStore.set({ matchId, res: null, error: null, busy: false, askedAt: null });
    if (explainStore.get().busy) return;
    const at = Math.floor(CLOCK.t);
    explainStore.set((p) => ({ ...p, busy: true, error: null, askedAt: at }));
    try {
      const res = await anApi.explain(matchId, at);
      if (explainStore.get().matchId === matchId) explainStore.set((p) => ({ ...p, res, busy: false }));
    } catch (e) {
      if (explainStore.get().matchId === matchId) explainStore.set((p) => ({ ...p, error: isUnavailable(e) ? "unavailable" : "failed", busy: false }));
    }
  }, [matchId]);
  return { res: mine ? s.res : null, error: mine ? s.error : null, busy: mine && s.busy, askedAt: mine ? s.askedAt : null, run };
}

export type { CoachSection };
