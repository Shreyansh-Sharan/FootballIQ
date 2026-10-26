// Match helpers: clock labels from meta.periods, localised names, team UI colours and kit swatches.

import type { Lang, MatchListItem, MatchMeta, MetaPeriod, MetaPlayer, MetaTeam, Role, SideIdx, TeamColors, TrackingRosterEntry } from "./types";

const NOMINAL_MIN: Record<number, number> = { 1: 45, 2: 45, 3: 15, 4: 15 };
const BASE_MIN: Record<number, number> = { 1: 0, 2: 45, 3: 90, 4: 105 };

export function periodAt(periods: MetaPeriod[], t: number): MetaPeriod | null {
  let cur: MetaPeriod | null = periods[0] ?? null;
  for (const p of periods) if (t >= p.start_ms) cur = p;
  return cur;
}

const baseOf = (p: MetaPeriod) => (Number.isFinite(p.base_minute) ? p.base_minute : BASE_MIN[p.period] ?? 0);
const isShootout = (p: MetaPeriod) => p.period >= 5;

/** Scoreboard minute like the API's `clock`: 57′, 45+2′, 105+1′, PEN. */
export function clockLabel(periods: MetaPeriod[], t: number): string {
  const p = periodAt(periods, t);
  if (!p) return `${Math.floor(t / 60000) + 1}′`;
  if (isShootout(p)) return "PEN";
  const base = baseOf(p);
  const el = Math.max(0, t - p.start_ms) / 60000;
  const nom = NOMINAL_MIN[p.period];
  if (nom != null && el >= nom) return `${base + nom}+${Math.floor(el - nom) + 1}′`;
  return `${base + Math.floor(el) + 1}′`;
}

/** Header clock: MM:SS, stoppage as 45+2′, PEN in a shootout. */
export function clockMMSS(periods: MetaPeriod[], t: number): string {
  const p = periodAt(periods, t);
  const pad = (n: number) => String(n).padStart(2, "0");
  if (!p) return `${pad(Math.floor(t / 60000))}:${pad(Math.floor((t % 60000) / 1000))}`;
  if (isShootout(p)) return "PEN";
  const base = baseOf(p);
  const el = Math.max(0, t - p.start_ms);
  const nom = NOMINAL_MIN[p.period];
  if (nom != null && el >= nom * 60000) return `${base + nom}+${Math.floor((el - nom * 60000) / 60000) + 1}′`;
  return `${pad(base + Math.floor(el / 60000))}:${pad(Math.floor((el % 60000) / 1000))}`;
}

/** Match-elapsed ms for a scoreboard minute (used by `?t=<minutes>`). */
export function msOfMinute(periods: MetaPeriod[], minute: number): number {
  const ps = periods.filter((p) => !isShootout(p));
  for (let i = ps.length - 1; i >= 0; i--) {
    const p = ps[i];
    if (minute >= baseOf(p)) return Math.min(p.start_ms + p.duration_ms, p.start_ms + (minute - baseOf(p)) * 60000);
  }
  return minute * 60000;
}

/** End of the first half, or null when unknown. */
export function halfTimeMs(periods: MetaPeriod[]): number | null {
  const p = periods.find((x) => x.period === 1);
  return p ? p.start_ms + p.duration_ms : null;
}

/** Axis ticks every 15 minutes within each period, plus period boundaries. */
export function axisTicks(periods: MetaPeriod[], duration: number): { t: number; label: string }[] {
  if (!periods.length) {
    const out = [];
    for (let m = 0; m * 60000 <= duration; m += 15) out.push({ t: m * 60000, label: `${m}′` });
    return out;
  }
  const out: { t: number; label: string }[] = [];
  for (const p of periods) {
    if (isShootout(p)) { out.push({ t: p.start_ms, label: "PEN" }); continue; }
    const base = baseOf(p);
    const nom = NOMINAL_MIN[p.period] ?? 45;
    for (let m = 0; m < nom; m += 15) out.push({ t: p.start_ms + m * 60000, label: `${base + m}′` });
  }
  const last = periods.filter((p) => !isShootout(p)).slice(-1)[0];
  if (last) out.push({ t: Math.min(duration, last.start_ms + (NOMINAL_MIN[last.period] ?? 45) * 60000), label: `${baseOf(last) + (NOMINAL_MIN[last.period] ?? 45)}′` });
  return out.filter((x) => x.t <= duration);
}

/** Period starts after kick-off, for chart and transport separators. */
export function periodBreaks(periods: MetaPeriod[]): number[] {
  return periods.filter((p) => p.start_ms > 0).map((p) => p.start_ms);
}

// ------------------------------------------------------------------ names
export const teamOf = (meta: MatchMeta, side: SideIdx): MetaTeam => (side === 0 ? meta.home : meta.away);
export const teamName = (team: MetaTeam, lang: Lang) => (lang === "hi" && team.name_hi ? team.name_hi : team.name);
export const teamShort = (team: MetaTeam, lang: Lang) => (lang === "hi" && team.short_hi ? team.short_hi : team.short);
export const playerName = (p: MetaPlayer, lang: Lang) => (lang === "hi" && p.name_hi ? p.name_hi : p.name);
export const playerShort = (p: MetaPlayer, lang: Lang) => (lang === "hi" && p.short_hi ? p.short_hi : p.short || p.name);
export const sideIdx = (side: string | null | undefined): SideIdx | null => (side === "home" ? 0 : side === "away" ? 1 : null);

/** Default favourite player for a side: the number 10, else a starting forward, else any starter. */
export function defaultPlayer(meta: MatchMeta, side: SideIdx): string | null {
  const key = side === 0 ? "home" : "away";
  const ps = meta.players.filter((p) => p.side === key);
  const pick = ps.find((p) => p.starter && p.number === 10) ?? ps.find((p) => p.starter && p.role === "ATT") ?? ps.find((p) => p.starter) ?? ps[0];
  return pick ? pick.player_id : null;
}

export function roleOf(group: string | null | undefined): Role {
  const g = (group ?? "").toUpperCase();
  if (/GK|GOAL/.test(g)) return "GK";
  if (/DEF|BACK|CB|LB|RB|WB/.test(g)) return "DEF";
  if (/ATT|FW|FOR|STRIK|WING|ST\b|CF/.test(g)) return "ATT";
  return "MID";
}

/** Who a tracking idx is: the meta player when the join succeeds, else roster data. */
export interface IdxInfo { idx: number; side: SideIdx; role: Role; number: string; player: MetaPlayer | null; rosterName: string | null }

/** Joins the roster to meta.players by (side, shirt number), then player_id: tracking and event ids can differ. */
export function indexRoster(roster: TrackingRosterEntry[], meta: MatchMeta | null): Map<number, IdxInfo> {
  const byId = new Map<string, MetaPlayer>();
  const byNum = new Map<string, MetaPlayer>();
  const teamSide = new Map<string, string>();
  if (meta) { teamSide.set(meta.home.team_id, "home"); teamSide.set(meta.away.team_id, "away"); }
  for (const p of meta?.players ?? []) {
    byId.set(p.player_id, p);
    if (p.number != null) byNum.set(`${p.side}:${p.number}`, p);
  }
  const out = new Map<number, IdxInfo>();
  for (const r of roster) {
    const side = teamSide.get(r.team_id) ?? r.side;
    const num = parseInt(r.jersey, 10);
    const player = (Number.isFinite(num) ? byNum.get(`${side}:${num}`) : undefined) ?? (r.player_id ? byId.get(r.player_id) : undefined) ?? null;
    out.set(r.idx, {
      idx: r.idx, side: side === "away" ? 1 : 0, role: player?.role ?? roleOf(r.position_group),
      number: player?.number != null ? String(player.number) : r.jersey, player, rosterName: r.name,
    });
  }
  return out;
}

/** Tracking idx of a meta player, via the roster join. */
export function idxOfPlayer(info: Map<number, IdxInfo>, playerId: string | null | undefined): number | null {
  if (!playerId) return null;
  for (const v of info.values()) if (v.player?.player_id === playerId) return v.idx;
  return null;
}

// ------------------------------------------------------------------ colours
const DEFAULT_COLORS: [TeamColors, TeamColors] = [
  { primary: "#3d96d8", secondary: "#ffffff", ink: "#0d2a4a", pattern: "solid" },
  { primary: "#e9475f", secondary: "#ffffff", ink: "#3a0a12", pattern: "solid" },
];
export const colorsOf = (meta: MatchMeta | null, side: SideIdx): TeamColors => {
  const c = meta ? teamOf(meta, side).colors : null;
  return c && c.primary ? { ...DEFAULT_COLORS[side], ...c } : DEFAULT_COLORS[side];
};

function hexRgb(hex: string): [number, number, number] | null {
  const m = hex.trim().replace("#", "");
  const h = m.length === 3 ? m.split("").map((c) => c + c).join("") : m;
  if (!/^[0-9a-f]{6}$/i.test(h)) return null;
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgbHsl([r, g, b]: [number, number, number]): [number, number, number] {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
  const l = (mx + mn) / 2;
  if (mx === mn) return [0, 0, l];
  const d = mx - mn;
  const s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
  const h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s, l];
}
function hslHex(h: number, s: number, l: number): string {
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return "#" + [f(0), f(8), f(4)].map((x) => Math.round(x * 255).toString(16).padStart(2, "0")).join("");
}

/** One UI colour per team, readable on both themes: the most saturated kit colour, mid lightness. */
function uiColor(c: TeamColors): { hex: string; hue: number; sat: number } {
  const cands = [c.primary, c.secondary, c.ink].map(hexRgb).filter((x): x is [number, number, number] => !!x).map(rgbHsl);
  const score = ([, s, l]: [number, number, number]) => s * (1 - Math.abs(l - 0.5) * 1.6);
  const best = cands.sort((a, b) => score(b) - score(a))[0] ?? [210, 0.6, 0.5];
  const [h, s, l] = best;
  const sat = s < 0.15 ? 0.12 : Math.max(0.55, Math.min(0.85, s));
  return { hex: hslHex(h, sat, Math.max(0.46, Math.min(0.6, l))), hue: h, sat };
}

/** [home, away] UI colours; the away side falls back to another hue when both kits read the same. */
export function teamColors(meta: MatchMeta | null): [string, string] {
  const a = uiColor(colorsOf(meta, 0));
  const b = uiColor(colorsOf(meta, 1));
  const dh = Math.abs(((a.hue - b.hue + 540) % 360) - 180);
  if (dh < 35 || (a.sat < 0.2 && b.sat < 0.2)) return [a.hex, hslHex((a.hue + 180) % 360, 0.7, 0.55)];
  return [a.hex, b.hex];
}

export function hexA(hex: string, a: number): string {
  const rgb = hexRgb(hex);
  if (!rgb) return hex;
  return `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`;
}

/** CSS background for a kit swatch (square or band) from meta colours. */
export function kitBackground(c: TeamColors, band = false): string {
  const w = band ? 14 : 6;
  switch (c.pattern) {
    case "stripes": return `repeating-linear-gradient(90deg, ${c.primary} 0 ${w}px, ${c.secondary} ${w}px ${w * 2}px)`;
    case "hoops": return `repeating-linear-gradient(0deg, ${c.primary} 0 ${band ? 4 : 6}px, ${c.secondary} ${band ? 4 : 6}px ${band ? 8 : 12}px)`;
    case "tricolor": return `linear-gradient(90deg, ${c.primary} 0 ${band ? 33 : 40}%, ${c.secondary} ${band ? 33 : 40}% ${band ? 66 : 60}%, ${c.ink} ${band ? 66 : 60}%)`;
    default: return c.primary;
  }
}
/** Number colour on a kit swatch. */
export function kitInk(c: TeamColors): string {
  return c.pattern === "tricolor" ? "#ffffff" : c.ink;
}

// ------------------------------------------------------------------ fallback meta
const abbr = (name: string) => name.replace(/[^A-Za-z ]/g, "").split(/\s+/).filter(Boolean).map((w) => w.slice(0, 3)).join("").slice(0, 3).toUpperCase() || name.slice(0, 3).toUpperCase();

/** A minimal meta from the match list when /matchday/meta is not available yet. */
export function fallbackMeta(m: MatchListItem): MatchMeta {
  const DUR = 96 * 60000;
  return {
    match_id: m.match_id, competition: m.competition, stage: m.stage, date: m.date, stadium: null,
    home: { team_id: m.home.team_id, side: "home", name: m.home.name, short: abbr(m.home.name), colors: null },
    away: { team_id: m.away.team_id, side: "away", name: m.away.name, short: abbr(m.away.name), colors: null },
    periods: [
      { period: 1, label: "1st half", start_ms: 0, duration_ms: 47 * 60000, base_minute: 0 },
      { period: 2, label: "2nd half", start_ms: 47 * 60000, duration_ms: 49 * 60000, base_minute: 45 },
    ],
    duration_ms: DUR, players: [], has_tracking: !!m.completeness?.continuous_tracking, fallback: true,
  };
}
