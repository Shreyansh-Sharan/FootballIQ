// Live-view helpers: overlay prefs, event captions and line-ups, the key message, insight toasts and PiP.
// Everything derived from events is cut at the replay clock.

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CLOCK } from "./clock";
import type { UIStrings } from "./i18n";
import { neutral } from "./neutral";
import type { Insight, MatchEvent, MatchMeta, MatchState, MetaPlayer, Predictions, SideIdx } from "./types";

// ------------------------------------------------------------------ overlays, presets, cameras
export interface Overlays {
  /** Unit lines with heights, widths and gaps. */
  shape: boolean;
  hull: boolean;
  dims: boolean;
  ref: boolean;
  names: boolean;
  speed: boolean;
  /** Ball trail. */
  trail: boolean;
  /** Player trails (3.6 s). */
  runs: boolean;
  /** Carrier's 4 nearest team-mates, open/blocked lanes, best triangles. */
  passing: boolean;
  press: boolean;
  /** Observed ball positions over the last 60 s. */
  heat: boolean;
  shots: boolean;
  /** Dashed polylines through each unit. */
  lines: boolean;
}
export const OVERLAY_KEYS: (keyof Overlays)[] = ["hull", "lines", "shape", "passing", "press", "runs", "heat", "shots", "dims", "ref", "names", "speed", "trail"];
export const NO_OVERLAYS: Overlays = {
  shape: false, hull: false, dims: false, ref: false, names: false, speed: false, trail: false, runs: false, passing: false, press: false, heat: false, shots: false, lines: false,
};
/** Need tracking; hidden on events-only matches. */
export const TRACKING_OVERLAYS: (keyof Overlays)[] = ["hull", "lines", "shape", "passing", "press", "runs", "heat", "dims", "ref", "names", "speed", "trail"];

export type PresetKey = "clean" | "shape" | "passing" | "pressing" | "threat";
export const PRESETS: [PresetKey, Partial<Overlays>][] = [
  ["clean", {}],
  ["shape", { hull: true, lines: true, shape: true, names: true }],
  ["passing", { passing: true, runs: true, trail: true, names: true }],
  ["pressing", { press: true, hull: true, names: true }],
  ["threat", { shots: true, heat: true, trail: true }],
];
export const presetOverlays = (k: PresetKey): Overlays => ({ ...NO_OVERLAYS, ...(PRESETS.find((p) => p[0] === k)?.[1] ?? {}) });
export function activePreset(ov: Overlays): PresetKey | null {
  for (const [k, p] of PRESETS) if (OVERLAY_KEYS.every((o) => !!p[o] === ov[o])) return k;
  return null;
}

export type CamMode = "top" | "broadcast" | "goal" | "follow" | "free";
export const CAMS: CamMode[] = ["top", "broadcast", "goal", "follow", "free"];
export type MiniSize = "s" | "m" | "l";
export const MINI_W: Record<MiniSize, number> = { s: 320, m: 440, l: 600 };

export interface PlayerPrefs { ov: Overlays; cam: CamMode; captions: boolean; mini: MiniSize; team: 0 | 1 | 2 }
const PREFS_KEY = "fiq.matchday.player";
export const DEFAULT_PLAYER_PREFS: PlayerPrefs = { ov: presetOverlays("shape"), cam: "top", captions: true, mini: "s", team: 2 };

export function loadPlayerPrefs(): PlayerPrefs {
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY) ?? "null") as Partial<PlayerPrefs> | null;
    if (!p) return DEFAULT_PLAYER_PREFS;
    const ov = { ...NO_OVERLAYS };
    for (const k of OVERLAY_KEYS) ov[k] = !!p.ov?.[k];
    return {
      ov: p.ov ? ov : DEFAULT_PLAYER_PREFS.ov,
      cam: CAMS.includes(p.cam as CamMode) ? (p.cam as CamMode) : "top",
      captions: p.captions !== false,
      mini: p.mini === "m" || p.mini === "l" ? p.mini : "s",
      team: p.team === 0 || p.team === 1 ? p.team : 2,
    };
  } catch {
    return DEFAULT_PLAYER_PREFS;
  }
}
export function savePlayerPrefs(p: PlayerPrefs) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* storage blocked: keep in memory */ }
}

// ------------------------------------------------------------------ events
export type EvKind = "goal" | "shot" | "save" | "card" | "sub" | "corner" | "free_kick" | "penalty" | "offside" | "foul" | "injury" | "shape" | "period";
export type EvFilter = "primary" | "attack" | "discipline" | "set_pieces" | "changes" | "all";
export const EV_FILTERS: [EvFilter, EvKind[] | null][] = [
  ["primary", ["goal", "shot", "save", "card", "sub", "corner", "free_kick", "penalty", "offside", "foul", "injury", "shape", "period"]],
  ["attack", ["goal", "shot", "save", "penalty"]],
  ["discipline", ["card", "foul", "offside", "injury"]],
  ["set_pieces", ["corner", "free_kick", "penalty"]],
  ["changes", ["sub", "shape", "period"]],
  ["all", null],
];
export const EV_ICON: Record<EvKind, string> = {
  goal: "⚽", shot: "◎", save: "✋", card: "▮", sub: "⇄", corner: "⚑", free_kick: "⤴", penalty: "◉", offside: "⚐", foul: "✕", injury: "✚", shape: "▦", period: "◷",
};
export const EV_COLOR: Record<EvKind, string> = {
  goal: "var(--accent)", shot: "#4fc3f7", save: "var(--good)", card: "#f5c518", sub: "#b39ddb", corner: "#4dd0e1", free_kick: "#4dd0e1",
  penalty: "#ff5d5d", offside: "var(--mute)", foul: "#ff8a65", injury: "var(--mute)", shape: "var(--good)", period: "var(--mute)",
};

export function eventKind(e: MatchEvent): EvKind | null {
  if (e.is_goal || e.is_own_goal) return "goal";
  if (e.card) return "card";
  if (e.type === "Shot") return e.subtype === "Penalty" ? "penalty" : "shot";
  if (e.type === "Goal Keeper" && e.subtype && /Saved/.test(e.subtype)) return "save";
  if (e.type === "Substitution") return "sub";
  if (e.type === "Pass" && e.subtype === "Corner") return "corner";
  if (e.type === "Pass" && e.subtype === "Free Kick") return "free_kick";
  if (e.type === "Offside" || e.outcome === "Pass Offside") return "offside";
  if (e.type === "Foul Committed") return "foul";
  if (e.type === "Injury Stoppage") return "injury";
  if (e.type === "Tactical Shift") return "shape";
  if (e.type === "Half Start" || e.type === "Half End") return "period";
  return null;
}

/** Scoreboard minute from an event clock label: "67:12" -> "68′", "45+02:10" -> "45+3′", "PEN" stays. */
export function minuteOf(label: string | null | undefined): string {
  if (!label) return "";
  if (/^PEN/i.test(label)) return "PEN";
  const plus = /^(\d+)\+(\d+):(\d+)/.exec(label);
  if (plus) return `${plus[1]}+${parseInt(plus[2], 10) + 1}′`;
  const m = /^(\d+):(\d+)/.exec(label);
  if (m) return `${parseInt(m[1], 10) + 1}′`;
  return label;
}

export const sideOfTeam = (meta: MatchMeta, teamId: string | null | undefined): SideIdx | null =>
  teamId === meta.home.team_id ? 0 : teamId === meta.away.team_id ? 1 : null;

/** Translated outcome; unknown values pass through. */
export function outcomeText(U: UIStrings, o: string | null | undefined): string {
  if (!o) return "";
  return (U.outcomes as Record<string, string>)[o] ?? o;
}
export function cardText(U: UIStrings, c: string | null | undefined): string {
  if (!c) return "";
  if (/second/i.test(c)) return U.cards.second;
  if (/red/i.test(c)) return U.cards.red;
  return U.cards.yellow;
}
export const isRed = (c: string | null | undefined) => !!c && /red|second/i.test(c);

export function describeEvent(e: MatchEvent, kind: EvKind | null, U: UIStrings, teamName: (id: string | null) => string): string {
  const xg = e.provider_xg != null ? ` · xG ${e.provider_xg.toFixed(2)}` : "";
  switch (kind) {
    case "goal": return `${e.player_name ?? U.ev.ownGoalBy}${e.is_own_goal ? ` (${U.ev.ownGoal})` : ""}${xg}`;
    case "shot": case "penalty": return `${e.player_name ?? ""} · ${outcomeText(U, e.outcome)}${xg}`;
    case "card": return `${e.player_name ?? ""} · ${cardText(U, e.card)}`;
    case "sub": return U.ev.onFor(e.recipient_name ?? "?", e.player_name ?? "?");
    case "shape": return U.ev.switchTo(teamName(e.team_id), e.formation ?? U.ev.newShape);
    case "period": return e.type === "Half Start" ? U.ev.periodStart : U.ev.periodEnd;
    default: return `${e.player_name ?? ""}${e.outcome && kind !== "foul" ? ` · ${outcomeText(U, e.outcome)}` : ""}`;
  }
}

export interface Caption { id: string; min: string; what: string; who: string; side: SideIdx | null; big: boolean; t_ms: number }
/** Caption for the newest goal, card, shot, sub or corner in the last 9 s. */
export function captionAt(events: MatchEvent[], t: number, meta: MatchMeta, U: UIStrings): Caption | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.match_elapsed_ms > t) continue;
    if (t - e.match_elapsed_ms > 9000) break;
    const corner = e.type === "Pass" && e.subtype === "Corner";
    if (!(e.is_goal || e.is_own_goal || e.card || e.type === "Shot" || e.type === "Substitution" || corner)) continue;
    const what = e.is_goal ? U.cap.goal : e.is_own_goal ? U.cap.ownGoal : e.card ? cardText(U, e.card).toUpperCase()
      : e.type === "Substitution" ? U.cap.sub(e.recipient_name ?? "") : corner ? U.cap.corner : U.cap.shot(outcomeText(U, e.outcome));
    return { id: e.event_id, min: minuteOf(e.clock_label), what, who: e.type === "Substitution" ? `▼ ${e.player_name ?? ""}` : e.player_name ?? "", side: sideOfTeam(meta, e.team_id), big: e.is_goal || e.is_own_goal, t_ms: e.match_elapsed_ms };
  }
  return null;
}

export interface Scorer { name: string; min: string; pen: boolean; og: boolean }
/** Scorers per side up to the clock, excluding the shoot-out; own goals go to the benefiting side. */
export function scorersAt(events: MatchEvent[], t: number, meta: MatchMeta): [Scorer[], Scorer[]] {
  const out: [Scorer[], Scorer[]] = [[], []];
  for (const e of events) {
    if (e.match_elapsed_ms > t || e.is_shootout || !(e.is_goal || e.is_own_goal)) continue;
    const s = sideOfTeam(meta, e.team_id);
    if (s == null) continue;
    out[s].push({ name: e.player_name ?? "", min: minuteOf(e.clock_label), pen: e.subtype === "Penalty", og: e.is_own_goal });
  }
  return out;
}

/** Latest declared formation per side (Starting XI / Tactical Shift events up to the clock). */
export function declaredShapes(events: MatchEvent[], t: number, meta: MatchMeta): [string | null, string | null] {
  const out: [string | null, string | null] = [null, null];
  for (const e of events) {
    if (e.match_elapsed_ms > t) break;
    if (!e.formation) continue;
    const s = sideOfTeam(meta, e.team_id);
    if (s != null) out[s] = e.formation;
  }
  return out;
}

export interface LineupRow { p: MetaPlayer; goals: number; card: string | null; on: string | null; off: string | null }
export interface Lineup { side: SideIdx; shape: string | null; subsMade: number; xi: LineupRow[]; cameOn: LineupRow[]; bench: LineupRow[] }
/** Starting XI, substitutes used and bench as of the clock. */
export function lineupsAt(meta: MatchMeta, events: MatchEvent[], t: number): [Lineup, Lineup] {
  const shapes = declaredShapes(events, t, meta);
  const mk = (side: SideIdx): Lineup => {
    const tid = side ? meta.away.team_id : meta.home.team_id;
    const ev = events.filter((e) => e.match_elapsed_ms <= t && e.team_id === tid && !e.is_shootout);
    const subs = ev.filter((e) => e.type === "Substitution");
    const offAt = new Map<string, string>(), onAt = new Map<string, string>();
    for (const e of subs) {
      if (e.player_id) offAt.set(e.player_id, minuteOf(e.clock_label));
      if (e.recipient_id) onAt.set(e.recipient_id, minuteOf(e.clock_label));
    }
    const goals = new Map<string, number>(), cards = new Map<string, string>();
    for (const e of ev) {
      if (e.is_goal && e.player_id) goals.set(e.player_id, (goals.get(e.player_id) ?? 0) + 1);
      if (e.card && e.player_id) { const prev = cards.get(e.player_id); if (!prev || isRed(e.card)) cards.set(e.player_id, e.card); }
    }
    const row = (p: MetaPlayer): LineupRow => ({ p, goals: goals.get(p.player_id) ?? 0, card: cards.get(p.player_id) ?? null, on: onAt.get(p.player_id) ?? null, off: offAt.get(p.player_id) ?? null });
    const squad = meta.players.filter((p) => p.team_id === tid || p.side === (side ? "away" : "home"));
    const byNum = (a: LineupRow, b: LineupRow) => (a.p.number ?? 99) - (b.p.number ?? 99);
    return {
      side, shape: shapes[side], subsMade: subs.length,
      xi: squad.filter((p) => p.starter).map(row),
      cameOn: squad.filter((p) => !p.starter && onAt.has(p.player_id)).map(row),
      bench: squad.filter((p) => !p.starter && !onAt.has(p.player_id)).map(row).sort(byNum),
    };
  };
  return [mk(0), mk(1)];
}

export interface KeyEventItem { id: string; t_ms: number; label: string }
/** Goals, cards and substitutions so far (newest first) for the command palette. */
export function keyMoments(events: MatchEvent[], t: number, U: UIStrings, max = 30): KeyEventItem[] {
  const out: KeyEventItem[] = [];
  for (let i = events.length - 1; i >= 0 && out.length < max; i--) {
    const e = events[i];
    if (e.match_elapsed_ms > t || e.is_shootout) continue;
    if (!(e.is_goal || e.is_own_goal || e.card || e.type === "Substitution")) continue;
    const what = e.is_goal ? U.cap.goal : e.is_own_goal ? U.cap.ownGoal : e.card ? cardText(U, e.card) : U.ev.sub;
    const who = e.type === "Substitution" ? U.ev.onFor(e.recipient_name ?? "?", e.player_name ?? "?") : e.player_name ?? "";
    out.push({ id: e.event_id, t_ms: e.match_elapsed_ms, label: `${minuteOf(e.clock_label)} ${what} · ${who}` });
  }
  return out;
}

// ------------------------------------------------------------------ key message
export type Tone = 0 | 1 | "n";
export interface Pillar { title: string; value: string; detail: string; tone: Tone }
export interface Story { kicker: string; headline: string; sub: string; pillars: Pillar[] }
const pc = (v: number | null | undefined, d = 0) => (v == null ? "—" : `${(100 * v).toFixed(d)}%`);

/** Headline (who leads and how likely it holds) plus momentum, threat and control pillars. */
export function buildStory(o: {
  U: UIStrings; meta: MatchMeta; short: [string, string]; name: [string, string]; t: number; clock: string; score: [number, number];
  state: MatchState | null; events: MatchEvent[]; pred: Predictions | null; predStatus: string;
}): Story {
  const { U, meta, short, name, t, score, state, pred } = o;
  const h = meta.home.team_id, a = meta.away.team_id;
  const win: [number | null, number | null] = [pred?.teams[h]?.win_phase?.probability ?? null, pred?.teams[a]?.win_phase?.probability ?? null];
  const draw = pred?.draw_phase?.probability ?? null;
  const shoot = state?.shootout;
  let headline: string;
  if (!state && t < 1000) headline = U.story.waiting;
  else if (shoot) headline = U.story.shootout(short[0], shoot[h] ?? 0, shoot[a] ?? 0, short[1]);
  else if (score[0] !== score[1]) {
    const lead: SideIdx = score[0] > score[1] ? 0 : 1;
    headline = U.story.lead(name[lead], Math.max(...score), Math.min(...score), win[lead] != null ? pc(win[lead]) : null);
  } else {
    const fav: SideIdx = (win[0] ?? 0) >= (win[1] ?? 0) ? 0 : 1;
    headline = draw != null && draw >= Math.max(win[0] ?? 0, win[1] ?? 0)
      ? U.story.levelDraw(score[0], score[1], pc(draw))
      : U.story.levelFav(score[0], score[1], win[fav] != null ? name[fav] : null, win[fav] != null ? pc(win[fav]) : null);
  }
  // Momentum: shots and xG over the last 10 min.
  let xh = 0, xa = 0, sh = 0, sa = 0;
  for (const e of o.events) {
    if (e.type !== "Shot" || e.is_shootout || e.match_elapsed_ms > t || t - e.match_elapsed_ms > 600000) continue;
    if (e.team_id === h) { xh += e.provider_xg ?? 0; sh++; } else if (e.team_id === a) { xa += e.provider_xg ?? 0; sa++; }
  }
  const even = Math.abs(xh - xa) < 0.15;
  const momentum: Pillar = {
    title: U.story.momentum, tone: even ? "n" : xh > xa ? 0 : 1,
    value: even ? U.story.even : U.story.onTop(xh > xa ? short[0] : short[1]),
    detail: U.story.momentumDetail(xh.toFixed(2), xa.toFixed(2), sh, sa),
  };
  const gh = pred?.teams[h]?.goal_next_10m?.probability ?? null, ga = pred?.teams[a]?.goal_next_10m?.probability ?? null;
  const ch = pred?.teams[h]?.corner_next_2m?.probability ?? null, ca = pred?.teams[a]?.corner_next_2m?.probability ?? null;
  const threat: Pillar | null = o.predStatus === "missing" ? null : {
    title: U.story.threat, tone: gh == null || ga == null ? "n" : gh >= ga ? 0 : 1,
    value: gh == null || ga == null ? (o.predStatus === "ready" ? U.story.noModel : U.loading) : U.story.toScore(gh >= ga ? short[0] : short[1], pc(Math.max(gh, ga))),
    detail: gh == null || ga == null ? "" : U.story.threatDetail(short[0], pc(gh), short[1], pc(ga), pc(Math.max(ch ?? 0, ca ?? 0))),
  };
  const ph = state?.stats[h]?.possession_pct ?? null, pa = state?.stats[a]?.possession_pct ?? null;
  const control: Pillar = {
    title: U.story.control, tone: ph == null || pa == null || Math.abs(ph - pa) < 4 ? "n" : ph > pa ? 0 : 1,
    value: ph == null || pa == null ? "—" : Math.abs(ph - pa) < 4 ? U.story.shared : U.story.ofBall(ph > pa ? short[0] : short[1], Math.max(ph, pa).toFixed(0)),
    detail: U.story.controlDetail(state?.stats[h]?.pass_accuracy_pct?.toFixed(0) ?? "—", state?.stats[a]?.pass_accuracy_pct?.toFixed(0) ?? "—"),
  };
  let last: MatchEvent | null = null;
  for (let i = o.events.length - 1; i >= 0; i--) {
    const e = o.events[i];
    if (e.match_elapsed_ms <= t && !e.is_shootout && (e.is_goal || e.is_own_goal || e.card)) { last = e; break; }
  }
  const sub = !last ? U.story.noKey
    : last.is_goal || last.is_own_goal ? U.story.lastGoal(minuteOf(last.clock_label), last.player_name ?? U.ev.ownGoalBy)
      : U.story.lastCard(minuteOf(last.clock_label), last.player_name ?? "", cardText(U, last.card));
  return { kicker: U.story.kicker(o.clock), headline, sub, pillars: threat ? [momentum, threat, control] : [momentum, control] };
}

// ------------------------------------------------------------------ insight toasts
export interface InsightSettings { autoPop: boolean; aiTakes: boolean; minPriority: 1 | 2 | 3 }
const INSIGHT_KEY = "fiq.matchday.insights";
export const DEFAULT_INSIGHT_SETTINGS: InsightSettings = { autoPop: true, aiTakes: true, minPriority: 2 };
export function loadInsightSettings(): InsightSettings {
  try {
    const s = JSON.parse(localStorage.getItem(INSIGHT_KEY) ?? "null") as Partial<InsightSettings> | null;
    if (!s) return DEFAULT_INSIGHT_SETTINGS;
    return { autoPop: s.autoPop !== false, aiTakes: s.aiTakes !== false, minPriority: s.minPriority === 1 || s.minPriority === 3 ? s.minPriority : 2 };
  } catch { return DEFAULT_INSIGHT_SETTINGS; }
}
export function saveInsightSettings(s: InsightSettings) {
  try { localStorage.setItem(INSIGHT_KEY, JSON.stringify(s)); } catch { /* storage blocked */ }
}

const POP_WINDOW_MS = 45000;
export const TOAST_LIFE_MS = 16000;

type Poppable = { id: string; t_ms: number; priority: number };
/** Toasts (max 3) for insights the clock just crossed; never for ones a seek skipped. */
export function useInsightToasts<I extends Poppable>(matchId: string | null, all: I[], t: number, settings: InsightSettings) {
  const [toasts, setToasts] = useState<I[]>([]);
  const shown = useRef(new Set<string>());
  const lastT = useRef(0);
  useEffect(() => { shown.current = new Set(); lastT.current = 0; setToasts([]); }, [matchId]);
  useEffect(() => {
    const jumped = t < lastT.current || t - lastT.current > 60000;
    lastT.current = t;
    if (jumped) {
      for (const i of all) if (i.t_ms <= t) shown.current.add(i.id);
      setToasts((cur) => (cur.length ? [] : cur));
      return;
    }
    const fresh = all.filter((i) => i.t_ms <= t && t - i.t_ms <= POP_WINDOW_MS && !shown.current.has(i.id));
    if (!fresh.length) return;
    fresh.forEach((i) => shown.current.add(i.id));
    if (!settings.autoPop) return;
    const pop = fresh.filter((i) => i.priority <= settings.minPriority).sort((a, b) => b.t_ms - a.t_ms);
    if (pop.length) setToasts((cur) => [...pop, ...cur.filter((c) => !pop.some((p) => p.id === c.id))].slice(0, 3));
  }, [t, all, settings.autoPop, settings.minPriority]);
  const dismiss = useCallback((id: string) => setToasts((cur) => cur.filter((x) => x.id !== id)), []);
  return { toasts, dismiss };
}

/** Question for the analyst agent about an insight. */
export function insightQuestion(U: UIStrings, i: Insight, team: string): string {
  const s = i.subject;
  if (s?.type === "substitution" && s.options[0]) return U.q.sub(team, s.options[0].off.name, s.options[0].on?.name ?? null);
  if (s?.type === "best_player") return U.q.best(U.situations[s.situation as keyof UIStrings["situations"]] ?? s.situation.replace("_", " "), team);
  if (s?.type === "player") return U.q.player(s.name, team, neutral(s.reasons?.[0] ?? i.title));
  return U.q.insight(neutral(i.title), i.minute, team);
}

// ------------------------------------------------------------------ picture-in-picture
export interface PipInfo {
  home: string; away: string; hs: number; as: number; clock: string; homeColor: string; awayColor: string; playing: boolean;
  note: { text: string; color: string } | null;
}
export interface PipLabels { back: string; toggle: string; fwd: string; title: string }
type DocPip = { requestWindow: (o: { width: number; height: number }) => Promise<Window> };

export function pipSupported(): boolean {
  if (typeof window === "undefined") return false;
  if ("documentPictureInPicture" in window) return true;
  return typeof document !== "undefined" && !!document.pictureInPictureEnabled && typeof HTMLCanvasElement !== "undefined" && "captureStream" in HTMLCanvasElement.prototype;
}

function drawPipOverlay(ctx: CanvasRenderingContext2D, w: number, h: number, i: PipInfo | null) {
  const k = w / 1280;
  if (i) {
    ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(10,16,32,0.9)"; ctx.fillRect(24 * k, 22 * k, 470 * k, 60 * k);
    ctx.fillStyle = i.homeColor || "#3d96d8"; ctx.fillRect(24 * k, 22 * k, 8 * k, 60 * k);
    ctx.fillStyle = i.awayColor || "#e9475f"; ctx.fillRect(486 * k, 22 * k, 8 * k, 60 * k);
    ctx.fillStyle = "#eef2fa"; ctx.font = `800 ${32 * k}px "Saira Extra Condensed", "Arial Narrow", sans-serif`;
    ctx.fillText(`${i.home}  ${i.hs} – ${i.as}  ${i.away}`, 48 * k, 53 * k);
    ctx.fillStyle = "#ffc53d"; ctx.font = `700 ${24 * k}px ui-monospace, monospace`; ctx.fillText(i.clock, 360 * k, 53 * k);
    if (i.note) {
      const y = h - 92 * k;
      ctx.fillStyle = "rgba(8,14,28,0.92)"; ctx.fillRect(24 * k, y, w - 48 * k, 60 * k);
      ctx.fillStyle = i.note.color || "#ffc53d"; ctx.fillRect(24 * k, y, 8 * k, 60 * k);
      ctx.fillStyle = "#ffffff"; ctx.font = `600 ${24 * k}px system-ui, sans-serif`;
      const tx = i.note.text.length > 92 ? `${i.note.text.slice(0, 90)}…` : i.note.text;
      ctx.fillText(tx, 48 * k, y + 30 * k);
    }
  }
}

/** PiP for the pitch canvas, with the score bug and latest moment drawn on top. */
export class PipController {
  private win: Window | null = null;
  private video: HTMLVideoElement | null = null;
  private timer: number | null = null;
  private raf = 0;
  private listeners = new Set<(on: boolean) => void>();
  get active() { return !!this.win || this.timer != null; }

  onChange(fn: (on: boolean) => void) { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; }
  private set(on: boolean) { this.listeners.forEach((l) => l(on)); }

  private stop = () => {
    if (this.timer != null) window.clearInterval(this.timer);
    this.timer = null;
    if (this.win) { try { this.win.cancelAnimationFrame(this.raf); } catch { /* window gone */ } }
    this.win = null;
    if (this.video) { this.video.srcObject = null; }
    this.set(false);
  };

  async close() {
    if (this.win) { this.win.close(); this.stop(); return; }
    if (typeof document !== "undefined" && document.pictureInPictureElement) await document.exitPictureInPicture();
    this.stop();
  }

  async toggle(src: () => HTMLCanvasElement | null, info: () => PipInfo | null, ctl: { toggle: () => void; seekBy: (ms: number) => void; play: () => void; pause: () => void }, L: PipLabels) {
    if (this.active || (typeof document !== "undefined" && document.pictureInPictureElement)) { await this.close(); return; }
    if (!src()) throw new Error("no-canvas");
    const dpip = (window as unknown as { documentPictureInPicture?: DocPip }).documentPictureInPicture;
    if (dpip) {
      const win = await dpip.requestWindow({ width: 760, height: 470 });
      this.win = win;
      const d = win.document;
      d.title = L.title;
      d.body.style.cssText = "margin:0;background:#0a1020;display:flex;flex-direction:column;height:100vh;font-family:system-ui,sans-serif;color:#eef2fa";
      const cv = d.createElement("canvas");
      cv.setAttribute("role", "img");
      cv.setAttribute("aria-label", L.title);
      cv.style.cssText = "flex:1;width:100%;min-height:0;display:block";
      const bar = d.createElement("div");
      bar.style.cssText = "display:flex;gap:8px;padding:8px 12px;align-items:center;justify-content:center;background:#121a2e;border-top:1px solid #25314c";
      const btn = (label: string, fn: () => void) => {
        const b = d.createElement("button");
        b.textContent = label; b.onclick = fn; b.setAttribute("aria-label", label);
        b.style.cssText = "background:#1e2944;color:#eef2fa;border:1px solid #33405e;border-radius:8px;padding:6px 14px;font:600 13px system-ui;cursor:pointer";
        bar.appendChild(b);
      };
      btn(L.back, () => ctl.seekBy(-10000));
      btn(L.toggle, () => ctl.toggle());
      btn(L.fwd, () => ctl.seekBy(10000));
      d.body.append(cv, bar);
      const ctx = cv.getContext("2d");
      const loop = () => {
        if (!this.win) return;
        this.raf = win.requestAnimationFrame(loop);
        CLOCK.pump();   // keeps the clock running while the main tab is hidden
        const c = src();
        const dpr = win.devicePixelRatio || 1;
        const W_ = Math.round(cv.clientWidth * dpr), H_ = Math.round(cv.clientHeight * dpr);
        if (!ctx || !W_ || !H_) return;
        if (cv.width !== W_ || cv.height !== H_) { cv.width = W_; cv.height = H_; }
        ctx.fillStyle = "#0a1020"; ctx.fillRect(0, 0, W_, H_);
        if (c && c.width && c.height) {
          const s2 = Math.min(W_ / c.width, H_ / c.height);
          ctx.drawImage(c, (W_ - c.width * s2) / 2, (H_ - c.height * s2) / 2, c.width * s2, c.height * s2);
        }
        drawPipOverlay(ctx, W_, H_, info());
      };
      this.raf = win.requestAnimationFrame(loop);
      win.addEventListener("pagehide", this.stop);
      this.set(true);
      return;
    }
    // Fallback: canvas stream in a <video> PiP, controls via mediaSession.
    const comp = document.createElement("canvas");
    comp.width = 1280; comp.height = 720;
    const ctx = comp.getContext("2d")!;
    const draw = () => {
      CLOCK.pump();
      const c = src();
      ctx.fillStyle = "#0a1020"; ctx.fillRect(0, 0, comp.width, comp.height);
      if (c && c.width && c.height) {
        const s2 = Math.min(comp.width / c.width, comp.height / c.height);
        ctx.drawImage(c, (comp.width - c.width * s2) / 2, (comp.height - c.height * s2) / 2, c.width * s2, c.height * s2);
      }
      drawPipOverlay(ctx, comp.width, comp.height, info());
    };
    draw();
    this.timer = window.setInterval(draw, 33);
    const v = this.video ?? document.createElement("video");
    this.video = v;
    v.muted = true; v.playsInline = true;
    v.srcObject = (comp as HTMLCanvasElement & { captureStream: (fps: number) => MediaStream }).captureStream(30);
    v.onleavepictureinpicture = this.stop;
    try {
      await v.play();
      await v.requestPictureInPicture();
    } catch (e) {
      this.stop();
      throw e;
    }
    this.set(true);
    if ("mediaSession" in navigator) {
      const ms = navigator.mediaSession;
      try {
        ms.metadata = new MediaMetadata({ title: L.title, artist: "FootballIQ" });
        ms.setActionHandler("play", () => ctl.play());
        ms.setActionHandler("pause", () => ctl.pause());
        ms.setActionHandler("seekbackward", () => ctl.seekBy(-10000));
        ms.setActionHandler("seekforward", () => ctl.seekBy(10000));
      } catch { /* some actions unsupported */ }
    }
  }
}
