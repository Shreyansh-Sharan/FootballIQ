// Buffer for 30 Hz tracking frames, interpolated for display just behind the newest frame.
// Interpolation is display-only: players keep their frame's `observed` flag and nothing feeds analytics.

export type WirePlayer = [idx: number, x: number, y: number, observed: number];
export type WireBall = [x: number, y: number, z: number | null, observed: number] | null;
export type WireFrame = [t: number, frameNum: number, ball: WireBall, players: WirePlayer[]];

export interface RosterEntry {
  idx: number;
  team_id: string;
  side: "home" | "away";
  jersey: string;
  player_id: string | null;
  name: string | null;
  position_group: string | null;
  started: boolean | null;
}

export interface RenderPlayer {
  idx: number;
  x: number;
  y: number;
  observed: boolean;
  vx: number; // m/s from the bracketing frames
  vy: number;
}

export interface RenderFrame {
  t: number;
  frameNum: number;
  ball: { x: number; y: number; z: number | null; observed: boolean } | null;
  players: RenderPlayer[];
  interpolated: boolean;
}

const MAX_FRAMES = 1800; // ~60 s at 30 Hz, enough for the 60 s heatmap
const LAG_MS = 120; // behind the newest frame, to interpolate

export class TrackingBuffer {
  private frames: WireFrame[] = [];
  private clockT = 0;
  private clockWall = 0;
  private speed = 1;
  private paused = true;

  reset(frames: WireFrame[] = []) {
    this.frames = [];
    this.push(frames);
  }

  push(frames: WireFrame[]) {
    for (const f of frames) {
      const last = this.frames[this.frames.length - 1];
      if (!last || f[0] > last[0]) this.frames.push(f);
      else if (f[0] < last[0]) {
        // out of order: insert in place
        const i = this.frames.findIndex((g) => g[0] > f[0]);
        this.frames.splice(i < 0 ? this.frames.length : i, 0, f);
      }
    }
    if (this.frames.length > MAX_FRAMES) this.frames.splice(0, this.frames.length - MAX_FRAMES);
  }

  /** Syncs to the server clock on each state message. */
  syncClock(replayT: number, speed: number, paused: boolean) {
    this.clockT = replayT;
    this.clockWall = performance.now();
    this.speed = speed;
    this.paused = paused;
  }

  get newestT(): number | null {
    return this.frames.length ? this.frames[this.frames.length - 1][0] : null;
  }

  /** Estimated replay time now (between server ticks), never ahead of the newest frame. */
  renderTime(nowWall = performance.now()): number | null {
    const newest = this.newestT;
    if (newest == null) return null;
    const est = this.paused ? this.clockT : this.clockT + (nowWall - this.clockWall) * this.speed;
    return Math.min(est, newest) - (this.paused ? 0 : LAG_MS * Math.min(this.speed, 2));
  }

  frameAt(t: number): RenderFrame | null {
    const fs = this.frames;
    if (!fs.length) return null;
    if (t <= fs[0][0]) return toRender(fs[0], null, 0);
    // last frame with time <= t
    let lo = 0;
    let hi = fs.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (fs[mid][0] <= t) lo = mid;
      else hi = mid - 1;
    }
    const a = fs[lo];
    const b = fs[lo + 1];
    if (!b || b[0] - a[0] > 1500) return toRender(a, null, 0); // real tracking gap: never invent motion across it
    return toRender(a, b, (t - a[0]) / (b[0] - a[0]));
  }

  /** Recent ball positions (oldest first) up to time t. */
  ballTrail(t: number, windowMs = 4000, step = 3): { x: number; y: number }[] {
    const out: { x: number; y: number }[] = [];
    for (let i = 0; i < this.frames.length; i += step) {
      const f = this.frames[i];
      if (f[0] > t) break;
      if (f[0] < t - windowMs || !f[2]) continue;
      out.push({ x: f[2][0], y: f[2][1] });
    }
    return out;
  }

  /** Oldest buffered frame time (null when empty). */
  get oldestT(): number | null {
    return this.frames.length ? this.frames[0][0] : null;
  }

  /** Last observed position per player at or before t, within maxAgeMs; unobserved rows are placeholders. */
  lastObserved(t: number, maxAgeMs = 5000): Map<number, { x: number; y: number; t: number }> {
    const out = new Map<number, { x: number; y: number; t: number }>();
    const fs = this.frames;
    if (!fs.length || t < fs[0][0]) return out;
    let lo = 0;
    let hi = fs.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (fs[mid][0] <= t) lo = mid;
      else hi = mid - 1;
    }
    for (let i = lo; i >= 0; i--) {
      const f = fs[i];
      if (f[0] < t - maxAgeMs) break;
      for (const p of f[3]) if (p[3] && !out.has(p[0])) out.set(p[0], { x: p[1], y: p[2], t: f[0] });
    }
    return out;
  }

  /** Recent positions of one player (oldest first) up to time t, for movement trails. */
  trail(idx: number, t: number, windowMs = 4000, step = 3): { x: number; y: number }[] {
    const out: { x: number; y: number }[] = [];
    for (let i = 0; i < this.frames.length; i += step) {
      const f = this.frames[i];
      if (f[0] > t) break;
      if (f[0] < t - windowMs) continue;
      const p = f[3].find((q) => q[0] === idx);
      if (p) out.push({ x: p[1], y: p[2] });
    }
    return out;
  }
}

function toRender(a: WireFrame, b: WireFrame | null, alpha: number): RenderFrame {
  const dt = b ? (b[0] - a[0]) / 1000 : 0;
  const bMap = new Map<number, WirePlayer>();
  if (b) for (const p of b[3]) bMap.set(p[0], p);
  const players: RenderPlayer[] = a[3].map((p) => {
    const q = bMap.get(p[0]);
    if (!q || !dt) return { idx: p[0], x: p[1], y: p[2], observed: !!p[3], vx: 0, vy: 0 };
    return {
      idx: p[0],
      x: p[1] + (q[1] - p[1]) * alpha,
      y: p[2] + (q[2] - p[2]) * alpha,
      observed: !!p[3] && !!q[3],
      vx: (q[1] - p[1]) / dt,
      vy: (q[2] - p[2]) / dt,
    };
  });
  let ball: RenderFrame["ball"] = null;
  if (a[2]) {
    const bb = b?.[2];
    ball = bb
      ? {
          x: a[2][0] + (bb[0] - a[2][0]) * alpha,
          y: a[2][1] + (bb[1] - a[2][1]) * alpha,
          z: a[2][2],
          observed: !!a[2][3] && !!bb[3],
        }
      : { x: a[2][0], y: a[2][1], z: a[2][2], observed: !!a[2][3] };
  }
  return { t: b ? a[0] + (b[0] - a[0]) * alpha : a[0], frameNum: a[1], ball, players, interpolated: !!b && alpha > 0 };
}
