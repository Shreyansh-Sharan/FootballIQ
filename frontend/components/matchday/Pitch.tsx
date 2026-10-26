"use client";

// Canvas pitch: tracking frames at the clock's render time, in 2D or 3D through one projector.
// Overlays use seen positions (players 5 s, ball 1.5 s); under 8 seen outfield players, estimates fill in.

import { useEffect, useRef, type MutableRefObject } from "react";
import { mdApi, useBucketResource } from "@/lib/matchday/api";
import { CLOCK } from "@/lib/matchday/clock";
import type { UIStrings } from "@/lib/matchday/i18n";
import type { CamMode, Overlays } from "@/lib/matchday/live";
import { hexA, idxOfPlayer, playerShort, teamShort, type IdxInfo } from "@/lib/matchday/match";
import { L, livePoints, MIN_DRAW_PLAYERS, MIN_SHAPE_PLAYERS, W, shapeOf, type ShapePoint, type TeamShape } from "@/lib/matchday/shape";
import type { FreezeFrame, Lang, MatchEvent, MatchMeta, SideIdx } from "@/lib/matchday/types";
import type { RenderFrame, TrackingBuffer } from "@/lib/trackingBuffer";
import { useMD } from "./context";

export type { Overlays } from "@/lib/matchday/live";

/** Screen positions of drawn players, for hit-testing and the inspector. */
export interface HitList { n: number; idx: Int16Array; x: Float32Array; y: Float32Array; r: Float32Array }
const newHits = (): HitList => ({ n: 0, idx: new Int16Array(48), x: new Float32Array(48), y: new Float32Array(48), r: new Float32Array(48) });
export function hitAt(h: HitList | null, x: number, y: number): number | null {
  if (!h) return null;
  let best = -1, bd = Infinity;
  for (let i = 0; i < h.n; i++) {
    const d = Math.hypot(h.x[i] - x, h.y[i] - y);
    if (d < h.r[i] * 1.5 && d < bd) { bd = d; best = i; }
  }
  return best < 0 ? null : h.idx[best];
}
export function hitPos(h: HitList | null, idx: number | null): { x: number; y: number; r: number } | null {
  if (!h || idx == null) return null;
  for (let i = 0; i < h.n; i++) if (h.idx[i] === idx) return { x: h.x[i], y: h.y[i], r: h.r[i] };
  return null;
}

interface Props {
  overlays: Partial<Overlays>;
  shapeTeams: SideIdx[];
  focus?: string | null;
  dimOthers?: boolean;
  compact?: boolean;
  fill?: boolean;
  height?: number;
  cam?: CamMode;
  /** Tracking idx; drawn with a white ring and name. */
  selected?: number | null;
  /** Called with null on empty grass. */
  onSelect?: (idx: number | null) => void;
  /** Dragging in a 3D camera switches to the free orbit. */
  onCam?: (c: CamMode) => void;
  zoomRef?: MutableRefObject<((d: number) => void) | null>;
  canvasRef?: MutableRefObject<HTMLCanvasElement | null>;
  hitsRef?: MutableRefObject<HitList | null>;
  /** Hide the "events only" tag (the host draws its own). */
  hideTag?: boolean;
  /** Skip drawing while off-screen. */
  paused?: boolean;
}

interface Pal {
  a: string; b: string; chalk: string; edge: string; home: string; away: string; accent: string; ink: string; font: string; mono: string;
  sky1: string; sky2: string; warn: string; bad: string;
}

function readPal(el: HTMLElement): Pal {
  const cs = getComputedStyle(el);
  const g = (k: string, d: string) => cs.getPropertyValue(k).trim() || d;
  return {
    a: g("--pitch-a", "#123f2b"), b: g("--pitch-b", "#154a32"), chalk: g("--chalk", "rgba(235,245,238,0.72)"), edge: g("--pitch-edge", "#0d2f20"),
    home: g("--home", "#3d96d8"), away: g("--away", "#e9475f"), accent: g("--accent", "#ffc53d"), ink: g("--ink", "#eef2fa"),
    font: g("--body", "system-ui, sans-serif"), mono: g("--mono", "ui-monospace, monospace"),
    sky1: g("--sky-a", "#04070f"), sky2: g("--sky-b", "#0d1a2e"), warn: g("--warn", "#ffb020"), bad: "#ff5d5d",
  };
}

interface DrawData {
  o: Props;
  meta: MatchMeta;
  lang: Lang;
  U: UIStrings;
  buffer: TrackingBuffer;
  info: Map<number, IdxInfo>;
  tracking: boolean;
  trackingReady: boolean;
  events: MatchEvent[];
  focusIdx: number | null;
  ff: FreezeFrame | null;
}

// ------------------------------------------------------------------ projection (allocation-free)
interface Cam { ex: number; ey: number; ez: number; tx: number; ty: number; tz: number }
interface Orbit { yaw: number; el: number; dist: number }
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

class Proj {
  is3d = false;
  /** px per metre (2D) or at the centre spot (3D). */
  scale = 1;
  /** Vertical squash for ground ellipses in 3D. */
  ry = 1;
  // output of p()
  x = 0; y = 0; k = 1; zc = 0;
  private ox = 0; private oy = 0;
  private e0 = 0; private e1 = 0; private e2 = 0;
  private f0 = 0; private f1 = 0; private f2 = 0;
  private r0 = 0; private r1 = 0;
  private u0 = 0; private u1 = 0; private u2 = 0;
  private fl = 1; private cx = 0; private cy = 0;
  private started = false; private hasPrev = false; private lx = 0; private ly = 0;

  set2d(w: number, h: number, pad: number) {
    this.is3d = false;
    const s = Math.min((w - 2 * pad) / L, (h - 2 * pad) / W);
    this.scale = s; this.k = s; this.ry = 1;
    this.ox = (w - L * s) / 2; this.oy = (h - W * s) / 2;
  }

  set3d(c: Cam, w: number, h: number) {
    this.is3d = true;
    let f0 = c.tx - c.ex, f1 = c.ty - c.ey, f2 = c.tz - c.ez;
    const fn = Math.hypot(f0, f1, f2) || 1;
    f0 /= fn; f1 /= fn; f2 /= fn;
    // right = normalize(f x up), up = right x f
    let r0 = f1, r1 = -f0;
    const rn = Math.hypot(r0, r1) || 1;
    r0 /= rn; r1 /= rn;
    this.f0 = f0; this.f1 = f1; this.f2 = f2; this.r0 = r0; this.r1 = r1;
    this.u0 = r1 * f2; this.u1 = -r0 * f2; this.u2 = r0 * f1 - r1 * f0;
    this.e0 = c.ex; this.e1 = c.ey; this.e2 = c.ez;
    this.fl = h / (2 * Math.tan(0.38)); this.cx = w / 2; this.cy = h / 2;
    this.ry = clamp(Math.abs(f2), 0.22, 1);
    this.scale = this.p(L / 2, W / 2, 0) ? this.k : 6;
  }

  /** Project a pitch point (metres, z up) into x, y, k, zc; false when behind the camera. */
  p(x: number, y: number, z = 0): boolean {
    if (!this.is3d) { this.x = this.ox + x * this.scale; this.y = this.oy + y * this.scale; this.k = this.scale; this.zc = 0; return true; }
    const d0 = x - this.e0, d1 = y - this.e1, d2 = z - this.e2;
    const zc = d0 * this.f0 + d1 * this.f1 + d2 * this.f2;
    if (zc < 1) return false;
    this.x = this.cx + ((d0 * this.r0 + d1 * this.r1) / zc) * this.fl;
    this.y = this.cy - ((d0 * this.u0 + d1 * this.u1 + d2 * this.u2) / zc) * this.fl;
    this.k = this.fl / zc; this.zc = zc;
    return true;
  }

  /** Ground path; 3D segments are subdivided so long lines bend in perspective. */
  begin(ctx: CanvasRenderingContext2D) { ctx.beginPath(); this.started = false; this.hasPrev = false; }
  to(ctx: CanvasRenderingContext2D, x: number, y: number, z = 0.02) {
    if (this.is3d && this.hasPrev) {
      const n = Math.max(1, Math.ceil(Math.hypot(x - this.lx, y - this.ly) / 4));
      const x0 = this.lx, y0 = this.ly;
      for (let i = 1; i <= n; i++) this.emit(ctx, x0 + ((x - x0) * i) / n, y0 + ((y - y0) * i) / n, z);
    } else this.emit(ctx, x, y, z);
    this.lx = x; this.ly = y; this.hasPrev = true;
  }
  private emit(ctx: CanvasRenderingContext2D, x: number, y: number, z: number) {
    if (!this.p(x, y, z)) { this.started = false; return; }
    if (this.started) ctx.lineTo(this.x, this.y);
    else { ctx.moveTo(this.x, this.y); this.started = true; }
  }
}

function camTarget(mode: CamMode, bx: number, by: number, homeBall: boolean, o: Orbit, out: Cam): boolean {
  const set = (ex: number, ey: number, ez: number, tx: number, ty: number, tz: number) => { out.ex = ex; out.ey = ey; out.ez = ez; out.tx = tx; out.ty = ty; out.tz = tz; };
  switch (mode) {
    case "broadcast": { const tx = lerp(L / 2, bx, 0.8); set(tx, -34, 23, tx, lerp(W / 2, by, 0.3), 0); return true; }
    case "goal": { const s = bx > L / 2 ? 1 : -1; set(L / 2 + 72 * s, W / 2, 13, lerp(bx, L / 2 + 22 * s, 0.35), lerp(W / 2, by, 0.5), 0); return true; }
    case "follow": { const dir = homeBall ? 1 : -1; set(bx - 24 * dir, by - 20, 15, bx + 6 * dir, by, 0); return true; }
    case "free": { const c = Math.cos(o.el); set(L / 2 + o.dist * c * Math.cos(o.yaw), W / 2 + o.dist * c * Math.sin(o.yaw), o.dist * Math.sin(o.el), L / 2, W / 2, 0); return true; }
    default: return false;
  }
}

// ------------------------------------------------------------------ per-instance state (caches, camera, hits)
interface Stage {
  cam: Cam; tgt: Cam; camOk: boolean; orbit: Orbit; lastNow: number; pr: Proj; hits: HitList;
  runsT: number; runs: Map<number, { x: number; y: number }[]>;
  trailT: number; trail: { x: number; y: number }[];
  heatT: number; heat: number[];
  speedT: number; speeds: Map<number, number>;
  ballT: number; ballX: number; ballY: number; ballOk: boolean;
  heatSprite: HTMLCanvasElement | null; heatKey: string;
  /** Top-left notes for overlays that cannot be computed now, with stripe colours. */
  notes: string[]; noteCols: string[];
}
const newStage = (): Stage => ({
  cam: { ex: 0, ey: 0, ez: 0, tx: 0, ty: 0, tz: 0 }, tgt: { ex: 0, ey: 0, ez: 0, tx: 0, ty: 0, tz: 0 }, camOk: false,
  orbit: { yaw: -Math.PI / 2, el: 0.62, dist: 95 }, lastNow: 0, pr: new Proj(), hits: newHits(),
  runsT: -1e9, runs: new Map(), trailT: -1e9, trail: [], heatT: -1e9, heat: [], speedT: -1e9, speeds: new Map(),
  ballT: -1e9, ballX: 0, ballY: 0, ballOk: false, heatSprite: null, heatKey: "", notes: [], noteCols: [],
});

export default function Pitch(props: Props) {
  const md = useMD();
  const cv = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const pal = useRef<Pal | null>(null);
  const st = useRef<Stage | null>(null);
  if (!st.current) st.current = newStage();
  const data = useRef<DrawData | null>(null);
  const eventsOnly = !md.hasTracking;
  // events-only matches: latest freeze-frame per 2 s clock bucket
  const ff = useBucketResource(eventsOnly ? `${md.matchId}|ff` : null, 2000, (at) => mdApi.freezeFrame(md.matchId, at));
  const ffData = eventsOnly ? ff.data?.freeze_frame ?? null : null;
  const ffShown = ffData && ffData.match_elapsed_ms <= md.clock.t ? ffData : null;
  data.current = {
    o: props, meta: md.meta, lang: md.lang, U: md.U, buffer: md.tracking.buffer, info: md.idxInfo,
    tracking: md.hasTracking, trackingReady: md.tracking.status === "ready", events: md.events.data,
    focusIdx: idxOfPlayer(md.idxInfo, props.focus), ff: ffShown,
  };

  useEffect(() => {
    const id = requestAnimationFrame(() => { if (wrap.current) pal.current = readPal(wrap.current); });
    return () => cancelAnimationFrame(id);
  }, [md.palKey]);

  const { zoomRef, canvasRef, hitsRef } = props;
  useEffect(() => {
    if (zoomRef) zoomRef.current = (d) => { const o = st.current!.orbit; o.dist = clamp(o.dist + d, 35, 150); };
    if (hitsRef) hitsRef.current = st.current!.hits;
    if (canvasRef) canvasRef.current = cv.current;
    return () => {
      if (zoomRef) zoomRef.current = null;
      if (canvasRef && canvasRef.current === cv.current) canvasRef.current = null;
    };
  }, [zoomRef, canvasRef, hitsRef]);

  const { height, fill } = props;
  useEffect(() => {
    const c = cv.current, box = wrap.current;
    if (!c || !box) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    let w = 0, h = 0, dpr = 1;
    const size = () => {
      const r = box.getBoundingClientRect();
      dpr = Math.min(2, window.devicePixelRatio || 1);
      w = r.width;
      h = fill ? r.height : height ? height : (w * (W + 8)) / (L + 8);
      if (w <= 0 || h <= 0) return;
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
      c.style.height = `${h}px`;
    };
    size();
    if (!pal.current) pal.current = readPal(box);
    const ro = new ResizeObserver(size);
    ro.observe(box);
    const off = CLOCK.addDraw(() => {
      if (data.current && pal.current && st.current && w > 0 && h > 0 && !data.current.o.paused) drawPitch(ctx, w, h, dpr, data.current, pal.current, st.current);
    });
    return () => { off(); ro.disconnect(); };
  }, [height, fill]);

  // ---- pointer: click selects, drag orbits in the 3D cameras
  const drag = useRef<{ x: number; y: number; moved: boolean; id: number } | null>(null);
  const interactive = !!(props.onSelect || props.onCam);
  const cam = props.cam ?? "top";
  const onDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!interactive || e.button > 0) return;
    drag.current = { x: e.clientX, y: e.clientY, moved: false, id: e.pointerId };
  };
  const onMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId || cam === "top" || !props.onCam) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 5) return;
    const s = st.current!;
    if (!d.moved) {
      d.moved = true;
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
      if (cam !== "free") {   // continue from where the current camera is
        const c = s.cam;
        const dist = clamp(Math.hypot(c.ex - L / 2, c.ey - W / 2, c.ez), 35, 150);
        s.orbit = { dist, yaw: Math.atan2(c.ey - W / 2, c.ex - L / 2), el: clamp(Math.asin(clamp(c.ez / dist, -1, 1)), 0.12, 1.5) };
        props.onCam("free");
      }
    }
    s.orbit.yaw -= dx * 0.008;
    s.orbit.el = clamp(s.orbit.el + dy * 0.006, 0.12, 1.5);
    d.x = e.clientX; d.y = e.clientY;
  };
  const onUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.moved || !props.onSelect) return;
    const r = e.currentTarget.getBoundingClientRect();
    props.onSelect(hitAt(st.current!.hits, e.clientX - r.left, e.clientY - r.top));
  };

  const age = ffShown ? Math.max(0, Math.round((md.clock.t - ffShown.match_elapsed_ms) / 1000)) : null;
  return (
    <div className={`pitch-wrap ${fill ? "fill" : ""}`} ref={wrap}>
      <canvas ref={cv} role="img"
        aria-label={md.hasTracking ? "Live pitch: players, ball and team shape" : "Pitch: event freeze-frame and the ball at the last event"}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={() => { drag.current = null; }}
        style={{ cursor: !interactive ? "default" : cam === "top" ? (props.onSelect ? "pointer" : "default") : "grab", touchAction: interactive && cam !== "top" ? "none" : "auto" }} />
      {eventsOnly && !props.compact && !props.hideTag && (
        <div className="pitch-tag">{md.U.eventsOnlyFF} · {age != null ? md.U.ffAge(age) : md.U.ffNone}</div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ drawing
function drawPitch(ctx: CanvasRenderingContext2D, w: number, h: number, dpr: number, d: DrawData, P: Pal, S: Stage) {
  const o = d.o;
  const ov = o.overlays;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.globalAlpha = 1;
  ctx.setLineDash([]);
  ctx.lineCap = "butt";
  S.hits.n = 0;
  S.notes.length = 0;
  S.noteCols.length = 0;
  const note = (text: string, c: string) => { S.notes.push(text); S.noteCols.push(c); };
  const pr = S.pr;
  const now = performance.now();
  const dt = Math.min(0.1, Math.max(0, (now - (S.lastNow || now)) / 1000));
  S.lastNow = now;

  // ---- frame and camera
  const newest = d.tracking ? d.buffer.newestT : null;
  const rt = newest != null ? Math.min(CLOCK.view, newest) : 0;
  const frame = newest != null ? d.buffer.frameAt(rt) : null;
  const mode: CamMode = d.tracking && frame ? o.cam ?? "top" : "top";
  let homeBall = true;
  if (frame?.ball) {   // ball cam only: nearest player's side, seen or estimated
    let bd = Infinity;
    for (const p of frame.players) {
      const dd = Math.hypot(p.x - frame.ball.x, p.y - frame.ball.y);
      if (dd < bd) { bd = dd; homeBall = d.info.get(p.idx)?.side !== 1; }
    }
  }
  if (mode !== "top" && camTarget(mode, frame?.ball?.x ?? L / 2, frame?.ball?.y ?? W / 2, homeBall, S.orbit, S.tgt)) {
    const c = S.cam, g = S.tgt;
    if (!S.camOk) { Object.assign(c, g); S.camOk = true; }
    else {
      const a = 1 - Math.exp(-dt * (mode === "free" ? 14 : 2.4));
      c.ex = lerp(c.ex, g.ex, a); c.ey = lerp(c.ey, g.ey, a); c.ez = lerp(c.ez, g.ez, a);
      c.tx = lerp(c.tx, g.tx, a); c.ty = lerp(c.ty, g.ty, a); c.tz = lerp(c.tz, g.tz, a);
    }
    pr.set3d(c, w, h);
  } else {
    pr.set2d(w, h, Math.max(10, w * 0.02));
  }
  const s = pr.scale;
  if (pr.is3d) drawBase3D(ctx, pr, w, h, P); else drawBase2D(ctx, pr, w, h, P);
  const col = (ti: SideIdx) => (ti === 0 ? P.home : P.away);
  const t = CLOCK.t;

  // ---------------------------------------------------------------- events only
  if (!d.tracking) {
    drawEventsOnly(ctx, pr, d, P, s, t, col);
    if (ov.shots) drawShots(ctx, pr, d, P, t);
    return;
  }

  // ---------------------------------------------------------------- tracking
  if (newest == null || !frame) {
    ctx.fillStyle = "rgba(255,255,255,0.7)"; ctx.font = `600 13px ${P.font}`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(d.U.loading, w / 2, h / 2);
    return;
  }
  const compact = !!o.compact;
  const teams = o.shapeTeams ?? [];
  const wantShape = teams.length > 0 && !!(ov.shape || ov.hull || ov.dims || ov.ref || ov.lines);
  const analytic = wantShape || !!ov.passing || !!ov.press;
  const live = analytic ? livePoints(d.buffer, d.info, rt, frame) : null;
  const pts: ShapePoint[] = live ? live.pts : EMPTY_PTS;
  const teamEst = live ? [live.seen[0] < MIN_SHAPE_PLAYERS, live.seen[1] < MIN_SHAPE_PLAYERS] : [false, false];
  const sideName = (ti: SideIdx) => teamShort(ti === 0 ? d.meta.home : d.meta.away, d.lang);

  // ball: seen now, else last seen within 1.5 s (100 ms steps), else the frame estimate, else the last
  // located event within 8 s; the last two count as estimated
  let bx = 0, by = 0, ballOk = false, ballEst = false;
  if ((ov.passing || ov.press) && !frame.ball) {
    for (let i = d.events.length - 1; i >= 0; i--) {
      const e = d.events[i];
      if (e.match_elapsed_ms > rt) continue;
      if (rt - e.match_elapsed_ms > 8000) break;
      if (e.x_m == null || e.y_m == null) continue;
      bx = e.end_x_m ?? e.x_m; by = e.end_y_m ?? e.y_m; ballOk = true; ballEst = true;
      break;
    }
  }
  if ((ov.passing || ov.press) && frame.ball) {
    if (frame.ball.observed) { bx = frame.ball.x; by = frame.ball.y; ballOk = true; }
    else if (Math.abs(rt - S.ballT) < 100) { bx = S.ballX; by = S.ballY; ballOk = S.ballOk; }
    else {
      for (let k = 1; k <= 15 && !ballOk; k++) {
        const f = d.buffer.frameAt(rt - k * 100);
        if (f?.ball?.observed && f.t <= rt) { bx = f.ball.x; by = f.ball.y; ballOk = true; }
      }
      S.ballT = rt; S.ballX = bx; S.ballY = by; S.ballOk = ballOk;
    }
    if (!ballOk) { bx = frame.ball.x; by = frame.ball.y; ballOk = true; ballEst = true; }
  }

  // heat: seen ball positions over the last 60 s, sampled and refreshed every 0.5 s
  if (ov.heat) {
    if (rt < S.heatT || rt - S.heatT >= 500) {
      S.heat.length = 0;
      const oldest = d.buffer.oldestT ?? rt;
      for (let k = 0; k < 120; k++) {
        const tt = rt - k * 500;
        if (tt < oldest) break;
        const f = d.buffer.frameAt(tt);
        if (f?.ball?.observed) S.heat.push(f.ball.x, f.ball.y);
      }
      S.heatT = rt;
    }
    if (S.heat.length) drawHeat(ctx, pr, S, P);
    else note(`${d.U.overlays.heat}: ${d.U.ovNA.heat}`.toUpperCase(), P.accent);
  }

  // shapes: measured with 8+ seen players, else partly estimated
  const shapes: (TeamShape | null)[] = [null, null];
  if (wantShape) {
    for (const ti of teams) {
      const sh = shapeOf(pts, ti, MIN_DRAW_PLAYERS);
      shapes[ti] = sh;
      if (!sh) {
        note(`${sideName(ti)} · ${d.U.shapeNA}`, col(ti));
        continue;
      }
      if (sh.estimated) note(`◐ ${sideName(ti)} · ${d.U.shapeEst(sh.observed, sh.n)}`, col(ti));
      if (ov.hull && sh.hull.length > 2) {
        pr.begin(ctx);
        for (const q of sh.hull) pr.to(ctx, q[0], q[1], 0.03);
        pr.to(ctx, sh.hull[0][0], sh.hull[0][1], 0.03);
        ctx.closePath();
        ctx.fillStyle = hexA(col(ti), sh.estimated ? (pr.is3d ? 0.08 : 0.09) : pr.is3d ? 0.14 : 0.16); ctx.fill();
        if (sh.estimated) ctx.setLineDash([6, 4]);
        ctx.strokeStyle = hexA(col(ti), sh.estimated ? 0.7 : 0.85); ctx.lineWidth = 1.5; ctx.stroke();
        ctx.setLineDash([]);
      }
      if (ov.lines) drawFormationLines(ctx, pr, pts, ti, col(ti), sh.estimated);
    }
  }

  // player trails (3.6 s), refreshed every 60 ms of match time
  if (ov.runs) {
    if (rt < S.runsT || rt - S.runsT >= 60) {
      S.runs.clear();
      for (const p of frame.players) S.runs.set(p.idx, d.buffer.trail(p.idx, rt, 3600, 4));
      S.runsT = rt;
    }
    ctx.lineWidth = 1.5;
    for (const p of frame.players) {
      const tr = S.runs.get(p.idx);
      if (!tr || tr.length < 2) continue;
      const side = d.info.get(p.idx)?.side ?? 0;
      pr.begin(ctx);
      for (const q of tr) pr.to(ctx, q.x, q.y, 0.03);
      pr.to(ctx, p.x, p.y, 0.03);
      ctx.strokeStyle = hexA(col(side), p.observed ? 0.45 : 0.2);
      ctx.stroke();
    }
  }

  if (ov.trail) {
    if (rt < S.trailT || rt - S.trailT >= 40) { S.trail = d.buffer.ballTrail(rt, 3000, 3); S.trailT = rt; }
    const tr = S.trail;
    if (tr.length > 1) {
      ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.lineWidth = 2; ctx.setLineDash([]);
      pr.begin(ctx);
      for (const q of tr) pr.to(ctx, q.x, q.y, 0.05);
      if (frame.ball) pr.to(ctx, frame.ball.x, frame.ball.y, 0.05);
      ctx.stroke();
    }
  }

  // possession (geometric proxy): side of the nearest player to the ball
  let poss: SideIdx | null = null;
  if (ballOk && pts.length) {
    let bd = Infinity;
    for (const p of pts) { const dd = Math.hypot(p.x - bx, p.y - by); if (dd < bd) { bd = dd; poss = p.side; } }
  }

  const nearEst = ballEst || teamEst[0] || teamEst[1];

  // pressing: defenders within 10 m of the ball, 4 m rings (dashed for estimated positions)
  if (ov.press) {
    if (!ballOk || poss == null) note(`${d.U.overlays.press}: ${d.U.ovNA.ball}`.toUpperCase(), P.warn);
    else {
      let n = 0;
      ctx.lineWidth = 1.3;
      for (const p of pts) {
        if (p.side === poss || p.role === "GK" || Math.hypot(p.x - bx, p.y - by) >= 10) continue;
        n++;
        ring(ctx, pr, p.x, p.y, 4, 0.03);
        ctx.fillStyle = hexA(P.warn, p.est ? 0.07 : 0.14); ctx.fill();
        if (p.est || ballEst) ctx.setLineDash([4, 3]);
        ctx.strokeStyle = hexA(P.warn, p.est ? 0.5 : 0.75); ctx.stroke();
        ctx.setLineDash([]);
      }
      if (nearEst) note(`◐ ${d.U.overlays.press}: ${d.U.partlyEst}`.toUpperCase(), P.warn);
      if (n >= 1 && !compact && pr.p(bx + 2, by - 3, 0.5)) label(ctx, pr.x, pr.y, (nearEst ? "~" : "") + d.U.pressN(n), P.warn, nearEst ? EST_INK : "#0a1020", s, "c", P.font, true);
    }
  }

  // passing options: carrier + 4 nearest team-mates, lanes open / blocked, best two triangles
  if (ov.passing) {
    if (!ballOk || poss == null) note(`${d.U.overlays.passing}: ${d.U.ovNA.ball}`.toUpperCase(), P.accent);
    else {
      if (nearEst) note(`◐ ${d.U.overlays.passing}: ${d.U.partlyEst}`.toUpperCase(), P.accent);
      drawPassing(ctx, pr, pts, poss, bx, by, P, s, compact, d.U, nearEst);
    }
  }

  if (ov.shots) drawShots(ctx, pr, d, P, t);

  // unit lines, dims, ref box: above the hulls, below the players
  if (wantShape && (ov.shape || ov.dims || ov.ref)) {
    for (const ti of teams) { const sh = shapes[ti]; if (sh) drawShape(ctx, pr, sh, ti, col(ti), P, s, ov, compact, d.U); }
  }

  // speeds from seen positions ~1 s apart, refreshed every 100 ms
  if (ov.speed) {
    if (rt < S.speedT || rt - S.speedT >= 100) {
      S.speeds.clear();
      const prev = d.buffer.lastObserved(rt - 1000, 400);
      for (const p of frame.players) {
        const q = prev.get(p.idx);
        if (!p.observed || !q) continue;
        const dtt = (rt - q.t) / 1000;
        if (dtt < 0.6) continue;
        const v = Math.hypot(p.x - q.x, p.y - q.y) / dtt;
        if (v < 11.5) S.speeds.set(p.idx, v);
      }
      S.speedT = rt;
    }
  }

  // ball holder (display): nearest observed player within 1.5 m of a low ball
  let holder = -1;
  if (frame.ball && (frame.ball.z == null || frame.ball.z < 1.5)) {
    let bd = 1.5;
    for (const p of frame.players) {
      if (!p.observed) continue;
      const dd = Math.hypot(p.x - frame.ball.x, p.y - frame.ball.y);
      if (dd < bd) { bd = dd; holder = p.idx; }
    }
  }

  if (pr.is3d) drawPlayers3D(ctx, pr, frame, d, P, S, holder, col);
  else drawPlayers2D(ctx, pr, frame, d, P, S, holder, col, compact);

  if (!compact) {
    for (const p of frame.players) {
      const who = d.info.get(p.idx);
      const isFocus = d.focusIdx != null && p.idx === d.focusIdx;
      const isSel = o.selected != null && o.selected === p.idx;
      const v = S.speeds.get(p.idx) ?? 0;
      const fast = !!ov.speed && v > 7.2;
      const named = isSel || (!!ov.names && (holder === p.idx || isFocus));
      if (!named && !fast) continue;
      const nm = who?.player ? playerShort(who.player, d.lang) : who?.rosterName ?? (who ? `#${who.number}` : "");
      const text = (fast ? "⚡ " : "") + (named ? nm : "") + (fast ? `${named ? " · " : ""}${(v * 3.6).toFixed(1)} km/h` : "");
      const z = pr.is3d ? 2.3 : 0;
      if (!pr.p(p.x, p.y, z)) continue;
      const r = pr.is3d ? 4 : Math.max(6, s * 1.05);
      const c = who ? col(who.side) : P.accent;
      label(ctx, pr.x, pr.y - r - 6, text, isSel ? "#ffffff" : c, "#fff", s, "bc", P.font, true);
    }
  }

  if (!compact) for (let i = 0; i < S.notes.length; i++) label(ctx, 8, 8 + i * 24, S.notes[i], S.noteCols[i], "#fff", s, "tl", P.font);
}

const EMPTY_PTS: ShapePoint[] = [];

// ------------------------------------------------------------------ base pitch
function drawBase2D(ctx: CanvasRenderingContext2D, pr: Proj, w: number, h: number, P: Pal) {
  const s = pr.scale;
  pr.p(0, 0);
  const ox = pr.x, oy = pr.y;
  const X_ = (x: number) => ox + x * s, Y_ = (y: number) => oy + y * s;
  ctx.fillStyle = P.edge; ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 14; i++) { ctx.fillStyle = i % 2 ? P.a : P.b; ctx.fillRect(X_((i * L) / 14), Y_(0), (L / 14) * s + 0.5, W * s); }
  ctx.strokeStyle = P.chalk; ctx.lineWidth = Math.max(1, s * 0.12);
  const rect = (x: number, y: number, ww: number, hh: number) => ctx.strokeRect(X_(x), Y_(y), ww * s, hh * s);
  rect(0, 0, L, W); ctx.beginPath(); ctx.moveTo(X_(L / 2), Y_(0)); ctx.lineTo(X_(L / 2), Y_(W)); ctx.stroke();
  ctx.beginPath(); ctx.arc(X_(L / 2), Y_(W / 2), 9.15 * s, 0, 7); ctx.stroke();
  rect(0, W / 2 - 20.16, 16.5, 40.32); rect(L - 16.5, W / 2 - 20.16, 16.5, 40.32); rect(0, W / 2 - 9.16, 5.5, 18.32); rect(L - 5.5, W / 2 - 9.16, 5.5, 18.32);
  ctx.beginPath(); ctx.arc(X_(11), Y_(W / 2), 9.15 * s, -0.93, 0.93); ctx.stroke();
  ctx.beginPath(); ctx.arc(X_(L - 11), Y_(W / 2), 9.15 * s, Math.PI - 0.93, Math.PI + 0.93); ctx.stroke();
  ctx.fillStyle = P.chalk;
  for (const x of SPOTS) { ctx.beginPath(); ctx.arc(X_(x), Y_(W / 2), Math.max(1.5, s * 0.25), 0, 7); ctx.fill(); }
  ctx.lineWidth = Math.max(1.5, s * 0.2); rect(-1.6, W / 2 - 3.66, 1.6, 7.32); rect(L, W / 2 - 3.66, 1.6, 7.32);
}
const SPOTS = [11, L - 11, L / 2];

// circle outlines in metres, built once
function circle(cx: number, cy: number, r: number, a0: number, a1: number, n: number): Float32Array {
  const out = new Float32Array((n + 1) * 2);
  for (let i = 0; i <= n; i++) { const a = a0 + ((a1 - a0) * i) / n; out[2 * i] = cx + r * Math.cos(a); out[2 * i + 1] = cy + r * Math.sin(a); }
  return out;
}
const ARC_A = Math.acos(5.5 / 9.15);
const CENTRE = circle(L / 2, W / 2, 9.15, 0, Math.PI * 2, 40);
const ARC_L = circle(11, W / 2, 9.15, -ARC_A, ARC_A, 16);
const ARC_R = circle(L - 11, W / 2, 9.15, Math.PI - ARC_A, Math.PI + ARC_A, 16);
const UNIT = circle(0, 0, 1, 0, Math.PI * 2, 24);
const GX = new Float32Array(17 * 19), GY = new Float32Array(17 * 19), GOK = new Uint8Array(17 * 19);

function strokePoly(ctx: CanvasRenderingContext2D, pr: Proj, a: Float32Array) {
  pr.begin(ctx);
  for (let i = 0; i < a.length; i += 2) pr.to(ctx, a[i], a[i + 1], 0.02);
  ctx.stroke();
}

function drawBase3D(ctx: CanvasRenderingContext2D, pr: Proj, w: number, h: number, P: Pal) {
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, P.sky1); g.addColorStop(1, P.sky2);
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  // grass: 12 x 14 cells inside the pitch plus a 2-cell margin, projected once per corner
  const cw = L / 12, chm = W / 14;
  for (let i = 0; i < 17; i++) for (let j = 0; j < 19; j++) {
    const k = i * 19 + j;
    if (pr.p((i - 2) * cw, (j - 2) * chm, 0)) { GX[k] = pr.x; GY[k] = pr.y; GOK[k] = 1; } else GOK[k] = 0;
  }
  ctx.lineWidth = 1;
  for (let i = 0; i < 16; i++) for (let j = 0; j < 18; j++) {
    const a = i * 19 + j, b = (i + 1) * 19 + j, c = (i + 1) * 19 + j + 1, e = i * 19 + j + 1;
    if (!GOK[a] || !GOK[b] || !GOK[c] || !GOK[e]) continue;
    const ci = i - 2, cj = j - 2;
    const inside = ci >= 0 && ci < 12 && cj >= 0 && cj < 14;
    const fill = inside ? (ci % 2 ? P.a : P.b) : P.edge;
    ctx.beginPath(); ctx.moveTo(GX[a], GY[a]); ctx.lineTo(GX[b], GY[b]); ctx.lineTo(GX[c], GY[c]); ctx.lineTo(GX[e], GY[e]); ctx.closePath();
    ctx.fillStyle = fill; ctx.strokeStyle = fill; ctx.fill(); ctx.stroke();
  }
  ctx.strokeStyle = P.chalk; ctx.lineWidth = 1.3;
  const rect = (x0: number, y0: number, x1: number, y1: number) => {
    pr.begin(ctx); pr.to(ctx, x0, y0); pr.to(ctx, x1, y0); pr.to(ctx, x1, y1); pr.to(ctx, x0, y1); pr.to(ctx, x0, y0); ctx.stroke();
  };
  rect(0, 0, L, W);
  pr.begin(ctx); pr.to(ctx, L / 2, 0); pr.to(ctx, L / 2, W); ctx.stroke();
  strokePoly(ctx, pr, CENTRE); strokePoly(ctx, pr, ARC_L); strokePoly(ctx, pr, ARC_R);
  rect(0, 13.84, 16.5, 54.16); rect(L - 16.5, 13.84, L, 54.16); rect(0, 24.84, 5.5, 43.16); rect(L - 5.5, 24.84, L, 43.16);
  ctx.fillStyle = P.chalk;
  for (const x of SPOTS) if (pr.p(x, W / 2, 0.02)) { ctx.beginPath(); ctx.arc(pr.x, pr.y, Math.max(1.5, 0.3 * pr.k), 0, 7); ctx.fill(); }
  drawGoal3D(ctx, pr, 0); drawGoal3D(ctx, pr, L);
}

function drawGoal3D(ctx: CanvasRenderingContext2D, pr: Proj, gx: number) {
  const off = gx === 0 ? -1.8 : 1.8;
  const q: number[] = [];
  const add = (x: number, y: number, z: number) => { if (!pr.p(x, y, z)) return false; q.push(pr.x, pr.y, pr.k); return true; };
  if (!(add(gx, 30.34, 0) && add(gx, 37.66, 0) && add(gx, 30.34, 2.44) && add(gx, 37.66, 2.44)
    && add(gx + off, 30.34, 0) && add(gx + off, 37.66, 0) && add(gx + off, 30.34, 2.1) && add(gx + off, 37.66, 2.1))) return;
  const X = (i: number) => q[i * 3], Y = (i: number) => q[i * 3 + 1];
  ctx.fillStyle = "rgba(225,236,252,0.07)"; ctx.strokeStyle = "rgba(225,236,252,0.22)"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(X(2), Y(2)); ctx.lineTo(X(3), Y(3)); ctx.lineTo(X(7), Y(7)); ctx.lineTo(X(6), Y(6)); ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(X(6), Y(6)); ctx.lineTo(X(7), Y(7)); ctx.lineTo(X(5), Y(5)); ctx.lineTo(X(4), Y(4)); ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.strokeStyle = "#f4f7fb"; ctx.lineWidth = Math.max(1.5, q[2] * 0.12);
  ctx.beginPath(); ctx.moveTo(X(0), Y(0)); ctx.lineTo(X(2), Y(2)); ctx.lineTo(X(3), Y(3)); ctx.lineTo(X(1), Y(1)); ctx.stroke();
}

/** Ground ring of radius r metres (path only). */
function ring(ctx: CanvasRenderingContext2D, pr: Proj, x: number, y: number, r: number, z: number) {
  if (!pr.is3d) {
    if (!pr.p(x, y, z)) return;
    ctx.beginPath(); ctx.arc(pr.x, pr.y, r * pr.k, 0, 7);
    return;
  }
  pr.begin(ctx);
  for (let i = 0; i < UNIT.length; i += 2) pr.to(ctx, x + r * UNIT[i], y + r * UNIT[i + 1], z);
  ctx.closePath();
}

// ------------------------------------------------------------------ overlays
function drawHeat(ctx: CanvasRenderingContext2D, pr: Proj, S: Stage, P: Pal) {
  const key = P.accent;
  if (!S.heatSprite || S.heatKey !== key) {   // one radial sprite, stamped per position
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const g = c.getContext("2d")!;
    const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, hexA(P.accent, 0.11)); gr.addColorStop(0.6, hexA(P.accent, 0.04)); gr.addColorStop(1, hexA(P.accent, 0));
    g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
    S.heatSprite = c; S.heatKey = key;
  }
  const sp = S.heatSprite;
  for (let i = 0; i < S.heat.length; i += 2) {
    if (!pr.p(S.heat[i], S.heat[i + 1], 0.03)) continue;
    const r = 6 * pr.k;
    ctx.drawImage(sp, pr.x - r, pr.y - r * pr.ry, 2 * r, 2 * r * pr.ry);
  }
}

function drawFormationLines(ctx: CanvasRenderingContext2D, pr: Proj, pts: ShapePoint[], ti: SideIdx, c: string, est: boolean) {
  ctx.setLineDash(est ? [2, 5] : pr.is3d ? [5, 5] : [4, 4]);
  ctx.lineWidth = 1.6; ctx.strokeStyle = hexA(c, est ? 0.5 : 0.7);
  for (const role of ROLES) {
    const unit = pts.filter((p) => p.side === ti && p.role === role).sort((a, b) => a.y - b.y);
    if (unit.length < 2) continue;
    pr.begin(ctx);
    for (const p of unit) pr.to(ctx, p.x, p.y, 0.05);
    ctx.stroke();
  }
  ctx.setLineDash([]);
}
const ROLES = ["DEF", "MID", "ATT"] as const;

function segDist(px: number, py: number, ax: number, ay: number, bx: number, by: number) {
  const dx = bx - ax, dy = by - ay;
  const t = clamp(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy || 1), 0, 1);
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function drawPassing(ctx: CanvasRenderingContext2D, pr: Proj, pts: ShapePoint[], poss: SideIdx, bx: number, by: number, P: Pal, s: number, compact: boolean, U: UIStrings, est: boolean) {
  const mates = pts.filter((p) => p.side === poss && p.role !== "GK");
  const opp = pts.filter((p) => p.side !== poss);
  let c: ShapePoint | null = null, cd = Infinity;
  for (const p of mates) { const dd = Math.hypot(p.x - bx, p.y - by); if (dd < cd) { cd = dd; c = p; } }
  if (!c) return;
  const car = c;
  const nb = mates.filter((p) => p !== car).sort((a, b) => Math.hypot(a.x - car.x, a.y - car.y) - Math.hypot(b.x - car.x, b.y - car.y)).slice(0, 4);
  const blocked = (a: ShapePoint, b: ShapePoint) => opp.some((q) => segDist(q.x, q.y, a.x, a.y, b.x, b.y) < 2.2);
  const lane = (a: ShapePoint, b: ShapePoint, open: boolean, width: number, alpha: number) => {
    pr.begin(ctx); pr.to(ctx, a.x, a.y, 0.05); pr.to(ctx, b.x, b.y, 0.05);
    const fade = a.est || b.est ? 0.55 : 1;
    if (open) { ctx.setLineDash(a.est || b.est ? [6, 3] : []); ctx.strokeStyle = hexA(P.accent, alpha * fade); }
    else { ctx.setLineDash([5, 4]); ctx.strokeStyle = hexA(P.bad, 0.85 * fade); }
    ctx.lineWidth = width; ctx.stroke();
  };
  // triangles with every side under 24 m, ranked by the share of open edges
  const tris: { v: [ShapePoint, ShapePoint, ShapePoint]; open: [boolean, boolean, boolean]; score: number }[] = [];
  for (let i = 0; i < nb.length; i++) for (let j = i + 1; j < nb.length; j++) {
    const v: [ShapePoint, ShapePoint, ShapePoint] = [car, nb[i], nb[j]];
    if (Math.hypot(v[0].x - v[1].x, v[0].y - v[1].y) >= 24 || Math.hypot(v[1].x - v[2].x, v[1].y - v[2].y) >= 24 || Math.hypot(v[2].x - v[0].x, v[2].y - v[0].y) >= 24) continue;
    const open: [boolean, boolean, boolean] = [!blocked(v[0], v[1]), !blocked(v[1], v[2]), !blocked(v[2], v[0])];
    tris.push({ v, open, score: (+open[0] + +open[1] + +open[2]) / 3 });
  }
  tris.sort((a, b) => b.score - a.score);
  const top = tris.slice(0, 2);
  for (const tr of top) {
    pr.begin(ctx);
    pr.to(ctx, tr.v[0].x, tr.v[0].y, 0.03); pr.to(ctx, tr.v[1].x, tr.v[1].y, 0.03); pr.to(ctx, tr.v[2].x, tr.v[2].y, 0.03); pr.to(ctx, tr.v[0].x, tr.v[0].y, 0.03);
    ctx.closePath(); ctx.fillStyle = hexA(P.accent, est ? 0.06 : 0.1); ctx.fill();
    for (let e = 0; e < 3; e++) lane(tr.v[e], tr.v[(e + 1) % 3], tr.open[e], 1.8, 0.9);
  }
  for (const m of nb) lane(car, m, !blocked(car, m), 1.1, 0.55);
  ctx.setLineDash([]);
  if (!compact) {
    for (const tr of top) {
      const cx = (tr.v[0].x + tr.v[1].x + tr.v[2].x) / 3, cy = (tr.v[0].y + tr.v[1].y + tr.v[2].y) / 3;
      if (pr.p(cx, cy, 0.05)) label(ctx, pr.x, pr.y, (est ? "~" : "") + U.openPct(Math.round(tr.score * 100)), P.accent, est ? EST_INK : "#0a1020", s, "c", P.font);
    }
  }
}

function drawShots(ctx: CanvasRenderingContext2D, pr: Proj, d: DrawData, P: Pal, t: number) {
  const home = d.meta.home.team_id;
  for (const e of d.events) {
    if (e.match_elapsed_ms > t) break;
    if (e.type !== "Shot" || e.is_shootout || e.x_m == null || e.y_m == null) continue;
    if (!pr.p(e.x_m, e.y_m, 0.04)) continue;
    const r = Math.max(3, (0.8 + (e.provider_xg ?? 0.05) * 3.2) * pr.k);
    const c = e.team_id === home ? P.home : P.away;
    ctx.beginPath(); ctx.ellipse(pr.x, pr.y, r, r * pr.ry, 0, 0, 7);
    if (e.is_goal) { ctx.globalAlpha = 0.9; ctx.fillStyle = c; ctx.fill(); ctx.globalAlpha = 1; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke(); }
    else { ctx.fillStyle = hexA(c, 0.18); ctx.fill(); ctx.strokeStyle = c; ctx.lineWidth = 1.8; ctx.stroke(); }
  }
}

function drawShape(ctx: CanvasRenderingContext2D, pr: Proj, sh: TeamShape, ti: SideIdx, c: string, P: Pal, s: number,
  ov: Partial<Overlays>, compact: boolean, U: UIStrings) {
  const big = !compact && (pr.is3d || s >= 4.6);
  // under 8 seen players: "~" grey numbers, dashed fainter geometry
  const est = sh.estimated;
  const m = (v: number) => `${est ? "~" : ""}${Math.round(v)}`;
  const ink = est ? EST_INK : "#fff";
  const inkOnAccent = est ? EST_INK : "#0a1020";
  const lc = est ? hexA(c, 0.6) : c;
  const ac = est ? hexA(P.accent, 0.6) : P.accent;
  if (ov.ref) {   // compact reference box: 35 m deep x 40 m wide, centred on the team's shape
    const cx = (sh.deepX + sh.highX) / 2, cy = (sh.ymin + sh.ymax) / 2;
    ctx.setLineDash([6, 5]); ctx.strokeStyle = P.accent; ctx.lineWidth = 1.6;
    pr.begin(ctx); pr.to(ctx, cx - 17.5, cy - 20); pr.to(ctx, cx + 17.5, cy - 20); pr.to(ctx, cx + 17.5, cy + 20); pr.to(ctx, cx - 17.5, cy + 20); pr.to(ctx, cx - 17.5, cy - 20);
    ctx.stroke(); ctx.setLineDash([]);
    if (!compact && pr.p(cx - 17.5, cy - 20, 0)) label(ctx, pr.x + 4, pr.y + 4, "REF 35×40 m", P.accent, "#0a1020", s, "tl", P.font);
  }
  if (ov.shape) {
    const units: [string, TeamShape["def"]][] = [["DEF", sh.def], ["MID", sh.mid], ["ATT", sh.att]];
    for (const [nm, ln] of units) {
      if (!ln) continue;
      ctx.strokeStyle = lc; ctx.lineWidth = Math.max(2, pr.is3d ? 2.5 : s * 0.3);
      if (est) ctx.setLineDash([7, 4]);
      pr.begin(ctx); pr.to(ctx, ln.x, ln.ymin, 0.06); pr.to(ctx, ln.x, ln.ymax, 0.06); ctx.stroke();
      ctx.setLineDash([]);
      if (big && pr.p(ln.x, ln.ymin, 0.06)) label(ctx, pr.x, pr.y - 4, `${nm} ${m(ln.height)} m · W ${m(ln.width)}`, c, ink, s, "bc", P.font);
    }
    const gapY = ti === 0 ? sh.ymax + 2.5 : sh.ymin - 2.5;
    const gp = (a: TeamShape["def"], b: TeamShape["def"], v: number | null) => {
      if (!a || !b || v == null) return;
      if (!pr.p(a.x, gapY, 0.06)) return;
      const x1 = pr.x, y1 = pr.y;
      if (!pr.p(b.x, gapY, 0.06)) return;
      arrow(ctx, x1, y1, pr.x, pr.y, lc);
      if (big) label(ctx, (x1 + pr.x) / 2, (y1 + pr.y) / 2 + (ti === 0 ? 12 : -12), `${m(v)} m`, c, ink, s, "c", P.font);
    };
    gp(sh.def, sh.mid, sh.gapDM); gp(sh.mid, sh.att, sh.gapMA);
  }
  if (ov.dims) {
    const ly = ti === 0 ? Math.max(1.5, sh.ymin - 3.5) : Math.min(W - 1.5, sh.ymax + 3.5);
    if (pr.p(sh.deepX, ly, 0.06)) {
      const x1 = pr.x, y1 = pr.y;
      if (pr.p(sh.highX, ly, 0.06)) {
        arrow(ctx, x1, y1, pr.x, pr.y, ac);
        if (!compact) label(ctx, (x1 + pr.x) / 2, (y1 + pr.y) / 2 + (ti === 0 ? -10 : 10), `${U.length.toUpperCase()} ${m(sh.length)} m`, P.accent, inkOnAccent, s, "c", P.font);
      }
    }
    const wx = ti === 0 ? Math.max(1.5, sh.deepX - 3) : Math.min(L - 1.5, sh.deepX + 3);
    if (pr.p(wx, sh.ymin, 0.06)) {
      const x1 = pr.x, y1 = pr.y;
      if (pr.p(wx, sh.ymax, 0.06)) {
        arrow(ctx, x1, y1, pr.x, pr.y, ac);
        if (!compact) label(ctx, (x1 + pr.x) / 2 + (ti === 0 ? 8 : -8), (y1 + pr.y) / 2, `${U.width.toUpperCase()} ${m(sh.width)} m`, P.accent, inkOnAccent, s, ti === 0 ? "l" : "r", P.font);
      }
    }
  }
}

// ------------------------------------------------------------------ players
function pushHit(S: Stage, idx: number, x: number, y: number, r: number) {
  const h = S.hits;
  if (h.n >= h.idx.length) return;
  h.idx[h.n] = idx; h.x[h.n] = x; h.y[h.n] = y; h.r[h.n] = r; h.n++;
}

function drawPlayers2D(ctx: CanvasRenderingContext2D, pr: Proj, frame: RenderFrame, d: DrawData, P: Pal, S: Stage, holder: number, col: (s: SideIdx) => string, compact: boolean) {
  const o = d.o, s = pr.scale;
  const r = Math.max(compact ? 4 : 6, s * 1.05);
  for (const p of frame.players) {
    const who = d.info.get(p.idx);
    const side = who?.side ?? null;
    const isFocus = d.focusIdx != null && p.idx === d.focusIdx;
    const isSel = o.selected != null && o.selected === p.idx;
    pr.p(p.x, p.y);
    const x = pr.x, y = pr.y;
    let alpha = p.observed ? 1 : 0.42;
    if (d.focusIdx != null && !isFocus && o.dimOthers) alpha *= 0.35;
    ctx.globalAlpha = alpha;
    ctx.beginPath(); ctx.arc(x, y, r, 0, 7);
    const gk = who?.role === "GK";
    ctx.fillStyle = gk ? (side === 0 ? "#f1c232" : "#2fbf71") : side != null ? col(side) : "#9aa4b8";
    ctx.fill();
    ctx.lineWidth = 1.5; ctx.strokeStyle = "rgba(255,255,255,0.9)";
    if (!p.observed) ctx.setLineDash([3, 3]);
    ctx.stroke(); ctx.setLineDash([]);
    if (!compact && who) {
      ctx.fillStyle = gk ? "#0a1020" : "#fff"; ctx.font = `700 ${Math.round(r * 1.05)}px ${P.font}`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(who.number, x, y + 0.5);
    }
    ctx.globalAlpha = 1;
    if (holder === p.idx) { ctx.beginPath(); ctx.arc(x, y, r + 4, 0, 7); ctx.strokeStyle = P.accent; ctx.lineWidth = 2.5; ctx.stroke(); }
    if (isFocus) {
      ctx.beginPath(); ctx.arc(x, y, r + 8 + Math.sin(CLOCK.t / 250) * 1.5, 0, 7); ctx.setLineDash([4, 3]); ctx.strokeStyle = P.accent; ctx.lineWidth = 2; ctx.stroke(); ctx.setLineDash([]);
    }
    if (isSel) { ctx.beginPath(); ctx.arc(x, y, r + 5.5, 0, 7); ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 3; ctx.stroke(); }
    pushHit(S, p.idx, x, y, r);
  }
  if (frame.ball) {
    pr.p(frame.ball.x, frame.ball.y);
    ctx.globalAlpha = frame.ball.observed ? 1 : 0.5;
    ctx.beginPath(); ctx.arc(pr.x, pr.y, Math.max(compact ? 2.5 : 3.5, s * 0.5), 0, 7);
    ctx.fillStyle = "#fff"; ctx.fill(); ctx.strokeStyle = "#0a1020"; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.globalAlpha = 1;
  }
}

// depth-sorted figures; scratch arrays reused between frames
const ORDER: number[] = [];
const DEPTH = new Float64Array(48);
function drawPlayers3D(ctx: CanvasRenderingContext2D, pr: Proj, frame: RenderFrame, d: DrawData, P: Pal, S: Stage, holder: number, col: (s: SideIdx) => string) {
  const o = d.o;
  const ps = frame.players;
  ORDER.length = 0;
  for (let i = 0; i < ps.length && i < 47; i++) {
    if (!pr.p(ps[i].x, ps[i].y, 0)) continue;
    DEPTH[i] = pr.zc; ORDER.push(i);
  }
  const ballIdx = 47;
  if (frame.ball && pr.p(frame.ball.x, frame.ball.y, 0)) { DEPTH[ballIdx] = pr.zc; ORDER.push(ballIdx); }
  ORDER.sort((a, b) => DEPTH[b] - DEPTH[a]);
  ctx.lineCap = "round";
  for (const i of ORDER) {
    if (i === ballIdx) {
      const b = frame.ball!;
      if (!pr.p(b.x, b.y, 0)) continue;
      const gx = pr.x, gy = pr.y, gk = pr.k;
      ctx.fillStyle = "rgba(0,0,0,0.5)"; ctx.beginPath(); ctx.ellipse(gx, gy, 0.3 * gk, 0.3 * gk * pr.ry, 0, 0, 7); ctx.fill();
      if (!pr.p(b.x, b.y, 0.11 + (b.z ?? 0))) continue;
      ctx.globalAlpha = b.observed ? 1 : 0.6;
      ctx.fillStyle = "#fff"; ctx.strokeStyle = "#0a1020"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(pr.x, pr.y, Math.max(2.5, 0.2 * pr.k), 0, 7); ctx.fill(); ctx.stroke();
      ctx.globalAlpha = 1;
      continue;
    }
    const p = ps[i];
    const who = d.info.get(p.idx);
    const side = who?.side ?? null;
    const isFocus = d.focusIdx != null && p.idx === d.focusIdx;
    const isSel = o.selected != null && o.selected === p.idx;
    if (!pr.p(p.x, p.y, 0)) continue;
    const fx = pr.x, fy = pr.y, k = pr.k;
    if (!pr.p(p.x, p.y, 1.85)) continue;
    const hx = pr.x, hy = pr.y;
    const gk = who?.role === "GK";
    const shirt = gk ? (side === 0 ? "#f1c232" : "#2fbf71") : side != null ? col(side) : "#9aa4b8";
    let alpha = p.observed ? 1 : 0.55;
    if (d.focusIdx != null && !isFocus && o.dimOthers) alpha *= 0.35;
    ctx.globalAlpha = alpha;
    ctx.fillStyle = "rgba(0,0,0,0.45)"; ctx.beginPath(); ctx.ellipse(fx, fy, 0.75 * k, 0.75 * k * pr.ry, 0, 0, 7); ctx.fill();
    if (isSel || holder === p.idx || isFocus) {
      ctx.strokeStyle = isSel ? "#ffffff" : P.accent; ctx.lineWidth = 2;
      if (isFocus && !isSel) ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.ellipse(fx, fy, 1.5 * k, 1.5 * k * pr.ry, 0, 0, 7); ctx.stroke(); ctx.setLineDash([]);
    }
    const wd = Math.max(2.5, 0.5 * k);
    const at = (f: number, xy: 0 | 1) => (xy ? fy + (hy - fy) * f : fx + (hx - fx) * f);
    ctx.strokeStyle = "#121a2a"; ctx.lineWidth = 0.85 * wd;
    ctx.beginPath(); ctx.moveTo(at(0, 0), at(0, 1)); ctx.lineTo(at(0.47, 0), at(0.47, 1)); ctx.stroke();
    ctx.strokeStyle = shirt; ctx.lineWidth = 1.15 * wd;
    if (!p.observed) ctx.setLineDash([2, 2]);
    ctx.beginPath(); ctx.moveTo(at(0.47, 0), at(0.47, 1)); ctx.lineTo(at(0.8, 0), at(0.8, 1)); ctx.stroke(); ctx.setLineDash([]);
    const hdx = at(0.93, 0), hdy = at(0.93, 1);
    ctx.fillStyle = "#d5dce6"; ctx.beginPath(); ctx.arc(hdx, hdy, Math.max(1.6, 0.15 * k), 0, 7); ctx.fill();
    if (k > 5 && who) {
      const fs = clamp(0.55 * k, 9, 13);
      ctx.font = `700 ${fs}px ${P.font}`;
      const tw = ctx.measureText(who.number).width + 8, ty = hdy - Math.max(8, 0.5 * k);
      ctx.fillStyle = shirt; ctx.beginPath(); ctx.roundRect(hdx - tw / 2, ty - fs, tw, fs + 4, 3); ctx.fill();
      ctx.fillStyle = gk ? "#0a1020" : "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "alphabetic"; ctx.fillText(who.number, hdx, ty + 1);
    }
    ctx.globalAlpha = 1;
    pushHit(S, p.idx, (fx + hx) / 2, (fy + hy) / 2, Math.max(12, k * 1.1));
  }
  ctx.lineCap = "butt";
}

// ------------------------------------------------------------------ events only
function drawEventsOnly(ctx: CanvasRenderingContext2D, pr: Proj, d: DrawData, P: Pal, s: number, t: number, col: (s: SideIdx) => string) {
  const o = d.o;
  const sideOf = (team: string | null | undefined): SideIdx | null => (team === d.meta.home.team_id ? 0 : team === d.meta.away.team_id ? 1 : null);
  // latest freeze-frame: visible area, players (keepers as squares, the actor outlined), faded when > 8 s old
  const ff = d.ff;
  if (ff) {
    const old = t - ff.match_elapsed_ms > 8000;
    if (ff.visible_area.length > 2) {
      ctx.setLineDash([4, 4]);
      pr.begin(ctx);
      for (const [x, y] of ff.visible_area) pr.to(ctx, x, y, 0.02);
      ctx.closePath();
      ctx.fillStyle = "rgba(255,255,255,0.06)"; ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.3)"; ctx.lineWidth = 1; ctx.stroke();
      ctx.setLineDash([]);
    }
    const r = Math.max(o.compact ? 3.5 : 5, s * 0.95);
    for (const p of ff.players) {
      if (!pr.p(p.x_m, p.y_m, 0)) continue;
      const sd = sideOf(p.team_id);
      ctx.globalAlpha = old ? 0.35 : 0.9;
      ctx.fillStyle = sd != null ? col(sd) : "#9aa4b8";
      ctx.beginPath();
      if (p.keeper) ctx.rect(pr.x - r, pr.y - r, 2 * r, 2 * r); else ctx.arc(pr.x, pr.y, r, 0, 7);
      ctx.fill();
      ctx.lineWidth = p.actor ? 3 : 1.2; ctx.strokeStyle = p.actor ? "#ffffff" : "rgba(10,16,32,0.7)"; ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }
  // the ball at the last located event, with the 8 events before it
  const trail: MatchEvent[] = [];
  for (let i = d.events.length - 1; i >= 0 && trail.length < 9; i--) {
    const e = d.events[i];
    if (e.match_elapsed_ms <= t && e.x_m != null && e.y_m != null) trail.push(e);
  }
  trail.reverse();
  const cur = trail[trail.length - 1];
  for (let i = 0; i < trail.length - 1; i++) {
    const e = trail[i], nx = trail[i + 1];
    const ex = e.end_x_m ?? nx.x_m!, ey = e.end_y_m ?? nx.y_m!;
    const sd = sideOf(e.team_id);
    ctx.globalAlpha = 0.2 + (0.65 * (i + 1)) / trail.length;
    ctx.strokeStyle = sd != null ? col(sd) : P.accent; ctx.lineWidth = 2;
    ctx.setLineDash(e.type === "Carry" ? [4, 3] : []);
    pr.begin(ctx); pr.to(ctx, e.x_m!, e.y_m!, 0.04); pr.to(ctx, ex, ey, 0.04); ctx.stroke();
  }
  ctx.globalAlpha = 1; ctx.setLineDash([]);
  if (cur) {
    const side = sideOf(cur.team_id);
    const bx = cur.end_x_m ?? cur.x_m!, by = cur.end_y_m ?? cur.y_m!;
    if (pr.p(bx, by, 0)) {
      ctx.beginPath(); ctx.arc(pr.x, pr.y, Math.max(10, s * 2.2), 0, 7);
      ctx.fillStyle = hexA(side != null ? col(side) : P.accent, 0.2); ctx.fill();
      ctx.beginPath(); ctx.arc(pr.x, pr.y, Math.max(3.5, s * 0.5), 0, 7);
      ctx.fillStyle = "#fff"; ctx.fill(); ctx.strokeStyle = "#0a1020"; ctx.lineWidth = 1.5; ctx.stroke();
      if (!o.compact && cur.player_name) label(ctx, pr.x, pr.y - Math.max(10, s * 2.2) - 4, `${cur.clock_label} · ${cur.player_name}`, side != null ? col(side) : P.accent, "#fff", s, "bc", P.font, true);
    }
  }
}

// ------------------------------------------------------------------ primitives
/** Ink for numbers built on estimated positions. */
const EST_INK = "#a3aec4";

function arrow(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number, c: string) {
  ctx.strokeStyle = c; ctx.fillStyle = c; ctx.lineWidth = 1.6; ctx.setLineDash([]);
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  const head = (xa: number, ya: number, xb: number, yb: number) => {
    const a = Math.atan2(yb - ya, xb - xa);
    ctx.beginPath(); ctx.moveTo(xb, yb); ctx.lineTo(xb - 7 * Math.cos(a - 0.4), yb - 7 * Math.sin(a - 0.4)); ctx.lineTo(xb - 7 * Math.cos(a + 0.4), yb - 7 * Math.sin(a + 0.4)); ctx.closePath(); ctx.fill();
  };
  head(x1, y1, x2, y2); head(x2, y2, x1, y1);
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

function label(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, bg: string, fg: string, s: number, anchor: "bc" | "tl" | "l" | "r" | "c", font: string, strong = false) {
  ctx.font = `${strong ? 700 : 600} ${Math.max(10, Math.min(14, Math.round(s * 1.05)))}px ${font}`;
  const tw = ctx.measureText(text).width + 10, th = Math.max(16, Math.min(22, s * 1.6));
  let lx = x - tw / 2, ly = y - th / 2;
  if (anchor === "bc") ly = y - th;
  if (anchor === "tl") { lx = x; ly = y; }
  if (anchor === "l") lx = x;
  if (anchor === "r") lx = x - tw;
  const cw = ctx.canvas.clientWidth || 9999, ch = ctx.canvas.clientHeight || 9999;
  lx = Math.max(2, Math.min(cw - tw - 2, lx)); ly = Math.max(2, Math.min(ch - th - 2, ly));
  ctx.setLineDash([]);
  ctx.fillStyle = "rgba(8,14,28,0.86)"; roundRect(ctx, lx, ly, tw, th, 4); ctx.fill();
  ctx.fillStyle = bg; ctx.fillRect(lx, ly, 3, th);
  ctx.fillStyle = fg === "#0a1020" ? bg : fg; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(text, lx + 6, ly + th / 2 + 0.5);
}
