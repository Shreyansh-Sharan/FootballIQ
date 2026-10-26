// Team shape from one tracking frame (105 x 68 m, home attacks left to right; height = metres from own goal).
// A player is seen if observed within 5 s; under 8 seen, frame positions fill in and the shape is `estimated`.

import type { RenderFrame, TrackingBuffer } from "../trackingBuffer";
import type { IdxInfo } from "./match";
import type { Role, SideIdx } from "./types";

export const L = 105;
export const W = 68;
export const MIN_SHAPE_PLAYERS = 8;
export const OBSERVED_MAX_AGE_MS = 5000;

export interface ShapePoint { idx: number; x: number; y: number; side: SideIdx; role: Role; /** Frame position of an unseen player. */ est?: boolean }
export interface UnitLine { height: number; x: number; ymin: number; ymax: number; width: number; n: number }
export interface TeamShape {
  length: number; width: number; area: number; hull: [number, number][];
  deepX: number; highX: number; ymin: number; ymax: number;
  def: UnitLine | null; mid: UnitLine | null; att: UnitLine | null;
  gapDM: number | null; gapMA: number | null; n: number;
  /** Outfield players seen within the last 5 s. */
  observed: number;
  /** Under MIN_SHAPE_PLAYERS seen: built from estimated positions. */
  estimated: boolean;
}
/** Fewest outfield points for a drawable (estimated) shape. */
export const MIN_DRAW_PLAYERS = 3;
const DEDUPE_M = 0.5;

export function hull(pts: [number, number][]): [number, number][] {
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (p.length < 3) return p;
  const cr = (o: [number, number], a: [number, number], b: [number, number]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo: [number, number][] = [];
  const up: [number, number][] = [];
  for (const q of p) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
  for (let i = p.length - 1; i >= 0; i--) { const q = p[i]; while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
  return lo.slice(0, -1).concat(up.slice(0, -1));
}

export function area(h: [number, number][]): number {
  let a = 0;
  for (let i = 0; i < h.length; i++) { const p = h[i], q = h[(i + 1) % h.length]; a += p[0] * q[1] - q[0] * p[1]; }
  return Math.abs(a) / 2;
}

/** Height from own goal for a side (home defends x = 0). */
export const heightOf = (side: SideIdx, x: number) => (side === 0 ? x : L - x);

/** Shape of one team, or null when fewer than `min` outfield points are available. */
export function shapeOf(points: ShapePoint[], ti: SideIdx, min = MIN_SHAPE_PLAYERS): TeamShape | null {
  const own = points.filter((p) => p.side === ti && p.role !== "GK");
  if (own.length < min) return null;
  let observed = 0;
  for (const p of own) if (!p.est) observed++;
  const pts: [number, number][] = own.map((p) => [p.x, p.y]);
  const units: Record<"DEF" | "MID" | "ATT", ShapePoint[]> = { DEF: [], MID: [], ATT: [] };
  for (const p of own) if (p.role !== "GK") units[p.role].push(p);
  const fxs = own.map((p) => heightOf(ti, p.x));
  const ys = own.map((p) => p.y);
  const h = hull(pts);
  const line = (u: ShapePoint[]): UnitLine | null => {
    if (!u.length) return null;
    const fx = u.reduce((a, p) => a + heightOf(ti, p.x), 0) / u.length;
    const yy = u.map((p) => p.y);
    const ymin = Math.min(...yy), ymax = Math.max(...yy);
    return { height: fx, x: ti === 0 ? fx : L - fx, ymin, ymax, width: ymax - ymin, n: u.length };
  };
  const def = line(units.DEF), mid = line(units.MID), att = line(units.ATT);
  const minFx = Math.min(...fxs), maxFx = Math.max(...fxs);
  return {
    length: maxFx - minFx, width: Math.max(...ys) - Math.min(...ys), area: area(h), hull: h,
    deepX: ti === 0 ? minFx : L - minFx, highX: ti === 0 ? maxFx : L - maxFx, ymin: Math.min(...ys), ymax: Math.max(...ys),
    def, mid, att, gapDM: def && mid ? mid.height - def.height : null, gapMA: mid && att ? att.height - mid.height : null, n: own.length,
    observed, estimated: observed < MIN_SHAPE_PLAYERS,
  };
}

/** Positions usable for geometry at time t: observed now, or last observed within 5 s. */
export function shapePoints(buffer: TrackingBuffer, info: Map<number, IdxInfo>, t: number, frame?: RenderFrame | null): ShapePoint[] {
  const fr = frame === undefined ? buffer.frameAt(t) : frame;
  if (!fr) return [];
  const seen = buffer.lastObserved(t, OBSERVED_MAX_AGE_MS);
  const out: ShapePoint[] = [];
  for (const p of fr.players) {
    const who = info.get(p.idx);
    if (!who) continue;
    if (p.observed) out.push({ idx: p.idx, x: p.x, y: p.y, side: who.side, role: who.role });
    else {
      const o = seen.get(p.idx);
      if (o) out.push({ idx: p.idx, x: o.x, y: o.y, side: who.side, role: who.role });
    }
  }
  return out;
}

/** Seen positions, plus frame positions (`est`) for teams under MIN_SHAPE_PLAYERS seen; placeholders within 0.5 m count once. */
export function livePoints(buffer: TrackingBuffer, info: Map<number, IdxInfo>, t: number, frame?: RenderFrame | null): { pts: ShapePoint[]; seen: [number, number] } {
  const fr = frame === undefined ? buffer.frameAt(t) : frame;
  const pts = shapePoints(buffer, info, t, fr);
  const seen: [number, number] = [0, 0];
  for (const p of pts) if (p.role !== "GK") seen[p.side]++;
  if (!fr || (seen[0] >= MIN_SHAPE_PLAYERS && seen[1] >= MIN_SHAPE_PLAYERS)) return { pts, seen };
  const have = new Set<number>();
  for (const p of pts) have.add(p.idx);
  const start = pts.length;
  for (const p of fr.players) {
    if (have.has(p.idx)) continue;
    const who = info.get(p.idx);
    if (!who || seen[who.side] >= MIN_SHAPE_PLAYERS) continue;
    let dup = false;
    for (let i = start; i < pts.length; i++) {
      const q = pts[i];
      if (q.side === who.side && Math.abs(q.x - p.x) < DEDUPE_M && Math.abs(q.y - p.y) < DEDUPE_M && Math.hypot(q.x - p.x, q.y - p.y) < DEDUPE_M) { dup = true; break; }
    }
    if (!dup) pts.push({ idx: p.idx, x: p.x, y: p.y, side: who.side, role: who.role, est: true });
  }
  return { pts, seen };
}

/** Both teams' shapes at t: estimated under 8 seen, null under 3 points. */
export function shapesAt(buffer: TrackingBuffer, info: Map<number, IdxInfo>, t: number): [TeamShape | null, TeamShape | null] {
  const { pts } = livePoints(buffer, info, t);
  return [shapeOf(pts, 0, MIN_DRAW_PLAYERS), shapeOf(pts, 1, MIN_DRAW_PLAYERS)];
}
