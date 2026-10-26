// Ranks moments per persona (WEIGHT x importance, boosted for the viewer's team/player) and renders them from templates.
// Placeholders map to the moment's `f` facts (docs/MATCHDAY_API.md) plus names, minute and score.

import { UI } from "./i18n";
import { playerShort, teamName } from "./match";
import { HOW, SCORE, SUBWHY, T, type Stance } from "./templates";
import type { Lang, MatchMeta, MetaPlayer, Moment, Pattern, SeriesPoint, SideIdx } from "./types";

export type Persona = "fan" | "casual" | "coach" | "analyst" | "player";
export type Metric = "none" | "xg" | "speed" | "distance" | "passing";
export type ThemeMode = "dark" | "light" | "auto";

export interface View {
  persona: Persona;
  fav: SideIdx;
  favPlayer: string | null;
  lang: Lang;
  metric: Metric;
  spoiler: boolean;
  alerts: { goal: boolean; win: boolean };
  theme: ThemeMode;
}

export const DEFAULT_VIEW: View = {
  persona: "fan", fav: 0, favPlayer: null, lang: "en", metric: "speed", spoiler: false, alerts: { goal: true, win: true }, theme: "dark",
};

export const WEIGHT: Record<Persona, Record<string, number>> = {
  fan: { goal: 1, chance: 0.8, card: 0.6, sub: 0.55, flow: 0.45, shape: 0.35, speed: 0.65, pass: 0.55, milestone: 0.5 },
  casual: { goal: 1, chance: 0.75, card: 0.5, sub: 0.35, flow: 0.45, shape: 0.2, speed: 0.75, pass: 0.55, milestone: 0.55 },
  coach: { goal: 0.8, chance: 0.6, card: 0.65, sub: 0.85, flow: 0.95, shape: 1, speed: 0.35, pass: 0.6, milestone: 0.35 },
  analyst: { goal: 0.85, chance: 0.9, card: 0.4, sub: 0.45, flow: 0.95, shape: 0.9, speed: 0.75, pass: 0.85, milestone: 0.5 },
  player: { goal: 1, chance: 0.6, card: 0.4, sub: 0.3, flow: 0.2, shape: 0.15, speed: 0.6, pass: 0.5, milestone: 0.6 },
};

export function relevance(m: Moment, view: View): number {
  let w = ((WEIGHT[view.persona] ?? WEIGHT.casual)[m.kind] ?? 0.4) * (Number.isFinite(m.imp) ? m.imp : 0.3);
  if (view.persona === "fan" && m.side != null && m.side === view.fav) w *= 1.25;
  if (view.favPlayer && (m.player_id === view.favPlayer || m.player2_id === view.favPlayer)) w *= view.persona === "player" ? 3 : 1.6;
  if (view.persona === "player" && m.player_id !== view.favPlayer && m.kind !== "goal") w *= 0.25;
  return w;
}

export function stanceFor(m: Moment, view: Pick<View, "persona" | "fav">): Stance {
  if (view.persona === "fan") return m.side != null ? (m.side === view.fav ? "own" : "rival") : "casual";
  if (view.persona === "player") return "casual";
  return view.persona;
}

/** Match context for renderInsight. */
export interface RenderCtx {
  meta: MatchMeta;
  players: Map<string, MetaPlayer>;
  /** Score [home, away] at a match time. */
  scoreAt: (t: number) => [number, number];
}

export function makeCtx(meta: MatchMeta, moments: Moment[], points: SeriesPoint[]): RenderCtx {
  const players = new Map(meta.players.map((p) => [p.player_id, p]));
  const goals = moments.filter((m) => m.kind === "goal" && m.clock !== "PEN" && typeof m.f.sa === "number" && typeof m.f.sb === "number");
  const scoreAt = (t: number): [number, number] => {
    let s: [number, number] | null = null;
    for (const g of goals) if (g.t_ms <= t) s = [g.f.sa as number, g.f.sb as number];
    let p: SeriesPoint | null = null;
    for (const x of points) if (x.t_ms <= t) p = x;
    if (p && Array.isArray(p.score) && (!s || p.score[0] + p.score[1] > s[0] + s[1])) return [p.score[0], p.score[1]];
    return s ?? [0, 0];
  };
  return { meta, players, scoreAt };
}

// ------------------------------------------------------------------ formatting of facts
const num = (v: unknown): number | null => {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(+v)) return +v;
  return null;
};
const fixed = (v: unknown, d: number) => { const n = num(v); return n == null ? "" : n.toFixed(d); };
const round = (v: unknown) => { const n = num(v); return n == null ? "" : String(Math.round(n)); };
/** Moment percentages are 0-100 by contract (a 1 means 1%, not 100%). */
const pct = (v: unknown) => { const n = num(v); return n == null ? "" : String(Math.round(n)); };
const speed = (v: unknown) => { const n = num(v); return n == null ? "" : Number.isInteger(n) ? String(n) : n.toFixed(1); };

const FORMAT: Record<string, (v: unknown) => string> = {
  xg: (v) => fixed(v, 2), txg: (v) => fixed(v, 2), spd: speed, dist: round, pdist: round, diff: round, xpp: pct,
  wcB: pct, wcA: pct, chaos: round, tov: (v) => fixed(v, 1), tr: (v) => fixed(v, 1), du: (v) => fixed(v, 1), lb: pct, seq: (v) => fixed(v, 1),
  ctrl: round, poss: pct, acc: pct, tempo: (v) => fixed(v, 1), bip: pct, len: round, wid: round, def: round, gap: round, area: round,
  km: (v) => fixed(v, 1), sprints: round, fouls: round,
};

export function templateKey(m: Moment): string {
  if (m.kind === "card" && (m.f.card === "red" || m.f.card === "second_yellow")) return "card.red";
  return m.kind + (m.variant ? `.${m.variant}` : "");
}

export interface Rendered { h: string; b: string; stance: Stance }

export function renderInsight(m: Moment, view: Pick<View, "persona" | "fav">, lang: Lang, ctx: RenderCtx): Rendered {
  const key = templateKey(m);
  const st = stanceFor(m, view);
  const set = T[lang][key] ?? T.en[key] ?? (m.kind === "card" ? T[lang].card : undefined);
  const tpl = set ? set[st] ?? set.casual ?? Object.values(set)[0] : undefined;
  const U = UI[lang];
  const { meta } = ctx;
  const f = m.f ?? {};
  const pl = (id: string | null) => { const p = id ? ctx.players.get(id) : undefined; return p ? playerShort(p, lang) : ""; };
  const sc = ctx.scoreAt(m.t_ms);
  const sa = num(f.sa) ?? sc[0];
  const sb = num(f.sb) ?? sc[1];
  const score: [number, number] = [sa, sb];
  const fav = view.fav ?? 0;
  const us = score[fav], them = score[1 - fav];
  const side = m.side;
  const xg = num(f.xg);
  const pattern = typeof f.pattern === "string" ? (f.pattern as Pattern) : null;
  const vals: Record<string, string> = {};
  for (const [k, v] of Object.entries(f)) if (v != null) vals[k] = FORMAT[k] ? FORMAT[k](v) : String(v);
  Object.assign(vals, {
    m: m.clock, p: pl(m.player_id) + (f.own_goal ? ` ${HOW[lang].ogTag}` : ""), p2: pl(m.player2_id),
    t: side != null ? teamName(side === 0 ? meta.home : meta.away, lang) : "",
    o: side != null ? teamName(side === 0 ? meta.away : meta.home, lang) : "",
    sa: String(sa), sb: String(sb),
    ownScore: SCORE[lang].ownGoal(us, them), rivalScore: SCORE[lang].rivalGoal(us, them),
    how: f.own_goal ? HOW[lang].og : f.pen ? HOW[lang].pen : (xg ?? 0) < 0.1 ? HOW[lang].low : HOW[lang].clear,
    xgp: xg != null ? String(Math.round(100 * xg)) : "",
    subWhy: f.behind ? SUBWHY[lang].chase : SUBWHY[lang].manage,
    pattern: pattern ? U.patterns[pattern] ?? pattern : "", patternDesc: pattern ? U.patternDesc[pattern] ?? "" : "",
  });
  if (!tpl) return { h: `${m.kind}${m.variant ? ` · ${m.variant}` : ""}`, b: [vals.p, vals.t, m.clock].filter(Boolean).join(" · "), stance: st };
  const fill = (s: string) => s.replace(/\{(\w+)\}/g, (_, k: string) => vals[k] ?? "").trim();
  return { h: fill(tpl[0]), b: fill(tpl[1]), stance: st };
}

/** Label for a perspective ("Solaria fan", "Player focus · Ibarra"). */
export function personaLabel(view: View, lang: Lang, meta: MatchMeta | null, players: Map<string, MetaPlayer>): string {
  const U = UI[lang];
  if (view.persona === "fan") return U.fanOf(meta ? teamName(view.fav === 0 ? meta.home : meta.away, lang) : "");
  if (view.persona === "player") {
    const p = view.favPlayer ? players.get(view.favPlayer) : undefined;
    return p ? `${U.personas.player} · ${playerShort(p, lang)}` : U.personas.player;
  }
  return U.personas[view.persona];
}
