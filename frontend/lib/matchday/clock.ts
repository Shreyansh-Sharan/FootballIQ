// Shared match clock outside React: a rAF loop advances `t`, canvases draw each frame, subscribers get 4 Hz snaps.
// `edge` is the live edge (seeks never pass it); `view` trails `t` at the edge so tracking frames interpolate.

"use client";

import { useEffect, useState } from "react";

export const SPEEDS = [0.5, 1, 2, 5, 10, 30, 60] as const;
export type Speed = (typeof SPEEDS)[number];
const LIVE_LAG_MS = 450;

export interface ClockSnap {
  t: number;
  edge: number;
  playing: boolean;
  speed: number;
  duration: number;
  ready: boolean;
}

type Fn = () => void;

class MatchClock {
  t = 0;
  edge = 0;
  playing = false;
  speed: number = 1;
  duration = 0;
  ready = false;
  /** Render time for tracking (t minus the live lag). */
  view = 0;
  private lag = 0;
  private last = 0;
  private raf = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private users = 0;
  private listeners = new Set<(s: ClockSnap) => void>();
  private draws = new Set<Fn>();
  private seekers = new Set<(t: number) => void>();
  private snapCache: ClockSnap = { t: 0, edge: 0, playing: false, speed: 1, duration: 0, ready: false };

  /** Starts the loops; ref-counted, safe under strict mode. */
  start(): Fn {
    this.users++;
    if (this.users === 1 && typeof window !== "undefined") {
      this.last = performance.now();
      const loop = (now: number) => {
        this.step(now);
        this.raf = requestAnimationFrame(loop);
      };
      this.raf = requestAnimationFrame(loop);
      this.timer = setInterval(() => this.emit(), 250);
    }
    return () => {
      this.users--;
      if (this.users === 0) {
        cancelAnimationFrame(this.raf);
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
      }
    };
  }

  /** Steps from a PiP window's frame while this tab's rAF is paused; no-op while the main loop runs. */
  pump() {
    if (typeof performance === "undefined" || !this.users) return;
    const now = performance.now();
    if (now - this.last > 40) this.step(now);
  }

  private step(now: number) {
    const dt = Math.min(0.25, Math.max(0, (now - this.last) / 1000));
    this.last = now;
    if (this.playing && this.ready) {
      this.t = Math.min(this.duration, this.t + dt * 1000 * this.speed);
      if (this.t > this.edge) this.edge = this.t;
      if (this.t >= this.duration) {
        this.playing = false;
        this.emit();
      }
    }
    // Lag eases in at the live edge (no jump back) and drops to 0 behind it.
    const atLive = this.edge - this.t < 1;
    const want = atLive ? LIVE_LAG_MS * Math.min(this.speed, 8) : 0;
    if (want > this.lag) this.lag = Math.min(want, this.lag + dt * 1000 * this.speed * 0.5);
    else this.lag = want;
    this.view = Math.max(0, this.t - this.lag);
    this.draws.forEach((d) => d());
  }

  snap(): ClockSnap {
    const s = this.snapCache;
    if (s.t !== this.t || s.edge !== this.edge || s.playing !== this.playing || s.speed !== this.speed || s.duration !== this.duration || s.ready !== this.ready) {
      this.snapCache = { t: this.t, edge: this.edge, playing: this.playing, speed: this.speed, duration: this.duration, ready: this.ready };
    }
    return this.snapCache;
  }

  private emit() {
    const s = this.snap();
    this.listeners.forEach((l) => l(s));
  }

  /** New match: clock at `startT` (also the live edge), playing. */
  reset(duration: number, startT: number, play = true) {
    this.duration = Math.max(0, duration);
    this.t = Math.max(0, Math.min(this.duration, startT));
    this.edge = this.t;
    this.view = this.t;
    this.lag = 0;
    this.playing = play && this.t < this.duration;
    this.ready = true;
    this.seekers.forEach((f) => f(this.t));
    this.emit();
  }

  /** Stops and blocks pollers until the next match's clock is set. */
  hold() {
    this.ready = false;
    this.playing = false;
    this.t = 0;
    this.edge = 0;
    this.view = 0;
    this.lag = 0;
    this.emit();
  }

  /** Keep t and edge but change the length (meta arrived after a fallback). */
  setDuration(duration: number) {
    this.duration = Math.max(this.edge, duration);
    this.emit();
  }

  seek(t: number) {
    if (!this.ready) return;
    this.t = Math.max(0, Math.min(this.edge, t));
    this.lag = this.edge - this.t < 1 ? this.lag : 0;
    this.view = Math.max(0, this.t - this.lag);
    this.seekers.forEach((f) => f(this.t));
    this.emit();
  }

  goLive() {
    this.seek(this.edge);
  }

  setPlaying(p: boolean) {
    this.playing = p && this.t < this.duration;
    this.last = typeof performance !== "undefined" ? performance.now() : 0;
    this.emit();
  }

  toggle() {
    this.setPlaying(!this.playing);
  }

  setSpeed(s: number) {
    this.speed = s;
    this.emit();
  }

  /** One step up or down the SPEEDS ladder (keyboard ↑ / ↓). */
  stepSpeed(dir: 1 | -1) {
    const i = SPEEDS.findIndex((v) => v >= this.speed);
    const cur = i < 0 ? SPEEDS.length - 1 : i;
    this.setSpeed(SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, cur + dir))]);
  }

  /** Relative seek (never past the live edge). */
  seekBy(ms: number) {
    this.seek(this.t + ms);
  }

  subscribe(fn: (s: ClockSnap) => void): Fn {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  addDraw(fn: Fn): Fn {
    this.draws.add(fn);
    return () => this.draws.delete(fn);
  }

  onSeek(fn: (t: number) => void): Fn {
    this.seekers.add(fn);
    return () => this.seekers.delete(fn);
  }
}

export const CLOCK = new MatchClock();

/** Clock snapshot, refreshed 4x per second and on every transport change. */
export function useClock(): ClockSnap {
  const [s, setS] = useState<ClockSnap>(() => CLOCK.snap());
  useEffect(() => {
    setS(CLOCK.snap());
    return CLOCK.subscribe(setS);
  }, []);
  return s;
}
