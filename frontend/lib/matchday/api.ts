// Matchday fetchers and polling hooks; every request is cut at the replay clock (to_ms / at_ms).
// Panels filter cached data by `t`, so rewinding never shows anything later than the clock.

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { API_URL } from "../api";
import { TrackingBuffer, type WireFrame } from "../trackingBuffer";
import { CLOCK } from "./clock";
import { fallbackMeta } from "./match";
import type {
  AiTakeResp, CommentaryResp, FormationsResp, FreezeFrame, InsightList, Lang, MatchEvent, MatchListItem, MatchMeta, MatchState, MomentsResp,
  PlayerFocus, Predictions, SeriesResp, TacticalWindow, TacticalWindowRef, TrackingRosterEntry,
} from "./types";

export class HttpError extends Error {
  constructor(public status: number, path: string) {
    super(`${status} ${path}`);
  }
}

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
const m = (id: string) => `/v1/matches/${enc(id)}`;
const ms = (v: number) => Math.max(0, Math.floor(v));

export const mdApi = {
  matches: () => getJSON<MatchListItem[]>("/v1/matches"),
  meta: (id: string) => getJSON<MatchMeta>(`${m(id)}/matchday/meta`),
  series: (id: string, to: number) => getJSON<SeriesResp>(`${m(id)}/matchday/series?to_ms=${ms(to)}`),
  moments: (id: string, to: number) => getJSON<MomentsResp>(`${m(id)}/matchday/moments?to_ms=${ms(to)}`),
  player: (id: string, pid: string, at: number) => getJSON<PlayerFocus>(`${m(id)}/matchday/player/${enc(pid)}?at_ms=${ms(at)}`),
  commentary: (id: string, lang: Lang, from: number, to: number) =>
    getJSON<CommentaryResp>(`${m(id)}/commentary?lang=${lang}&from_ms=${Math.floor(from)}&to_ms=${ms(to)}`),
  events: (id: string, from: number, to: number) =>
    getJSON<{ events: MatchEvent[] }>(`${m(id)}/events?from_ms=${Math.max(-1, Math.floor(from))}&to_ms=${ms(to)}`),
  state: (id: string, at: number) => getJSON<MatchState>(`${m(id)}/state?at_ms=${ms(at)}`),
  tracking: (id: string) => getJSON<{ available: boolean; roster?: TrackingRosterEntry[] }>(`${m(id)}/tracking`),
  frames: (id: string, from: number, to: number, max = 2000) =>
    getJSON<{ frames: WireFrame[] }>(`${m(id)}/frames?from_ms=${Math.max(-1, Math.floor(from))}&to_ms=${ms(to)}&max_frames=${max}`),
  freezeFrame: (id: string, at: number) => getJSON<{ freeze_frame: FreezeFrame | null }>(`${m(id)}/freeze-frame?at_ms=${ms(at)}`),
  predictions: (id: string, at: number) => getJSON<Predictions>(`${m(id)}/predictions?at_ms=${ms(at)}`),
  tacticalWindows: (id: string, at: number) => getJSON<{ windows: TacticalWindowRef[] }>(`${m(id)}/tactical/windows?at_ms=${ms(at)}`),
  tacticalWindow: (id: string, team: string, win: string, at: number) =>
    getJSON<TacticalWindow>(`${m(id)}/tactical?team=${enc(team)}&window=${enc(win)}&at_ms=${ms(at)}`),
  formations: (id: string, at: number) => getJSON<FormationsResp>(`${m(id)}/tactical/formations?at_ms=${ms(at)}`),
  insights: (id: string, at: number) => getJSON<InsightList>(`${m(id)}/insights?at_ms=${ms(at)}`),
  insightAi: (id: string, insightId: string) => postJSON<AiTakeResp>(`${m(id)}/insights/${enc(insightId)}/ai`, {}),
};

/** Absolute URL for a commentary audio path. */
export const audioUrl = (u: string) => (/^https?:/.test(u) ? u : `${API_URL}${u}`);

export type Status = "loading" | "ready" | "missing" | "error";
const isMissing = (e: unknown) => e instanceof HttpError && (e.status === 404 || e.status === 501);
/** Also 503: resource not produced (e.g. models not scored). */
const isUnavailable = (e: unknown) => isMissing(e) || (e instanceof HttpError && e.status === 503);

// ------------------------------------------------------------------ cutoff resources
export interface Resource<T> { data: T; status: Status; fetchedTo: number }

interface CutoffOpts<R, T> {
  /** Resets everything when it changes; null = disabled. */
  key: string | null;
  initial: T;
  /** Whether to refetch, given the fetched cutoff and the clock. */
  due: (fetchedTo: number, t: number) => boolean;
  /** Fetch only (fetchedTo, t] instead of everything up to t. */
  delta: boolean;
  fetch: (fromMs: number, toMs: number) => Promise<R>;
  merge: (prev: T, res: R) => T;
  onBatch?: (res: R, fromMs: number, toMs: number) => void;
  intervalMs?: number;
}

export function useCutoffResource<R, T>(o: CutoffOpts<R, T>): Resource<T> {
  const [st, setSt] = useState<Resource<T>>({ data: o.initial, status: "loading", fetchedTo: -1 });
  const opts = useRef(o);
  opts.current = o;
  useEffect(() => {
    const init = opts.current.initial;
    setSt({ data: init, status: "loading", fetchedTo: -1 });
    if (!o.key) return;
    let alive = true;
    let inFlight = false;
    let fetchedTo = -1;
    let data = init;
    let status: Status = "loading";
    let retryAt = 0;
    const tick = async () => {
      if (!alive || inFlight || !CLOCK.ready || performance.now() < retryAt) return;
      const t = Math.floor(CLOCK.t);
      if (fetchedTo >= 0 && (t <= fetchedTo || !opts.current.due(fetchedTo, t))) return;
      inFlight = true;
      const from = opts.current.delta && fetchedTo >= 0 ? fetchedTo : -1;
      try {
        const res = await opts.current.fetch(from, t);
        if (!alive) return;
        data = opts.current.merge(from < 0 ? init : data, res);
        fetchedTo = Math.max(fetchedTo, t);
        status = "ready";
        setSt({ data, status, fetchedTo });
        opts.current.onBatch?.(res, from, t);
      } catch (e) {
        if (!alive) return;
        retryAt = performance.now() + (isMissing(e) ? 15000 : 5000);
        if (status !== "ready") {
          status = isMissing(e) ? "missing" : "error";
          setSt({ data, status, fetchedTo });
        }
      } finally {
        inFlight = false;
      }
    };
    void tick();
    const id = setInterval(tick, o.intervalMs ?? 1000);
    const off = CLOCK.onSeek(() => void tick());
    return () => {
      alive = false;
      clearInterval(id);
      off();
    };
  }, [o.key]); // eslint-disable-line react-hooks/exhaustive-deps
  return st;
}

/** Point-in-time resource (at_ms = clock), refetched once the clock moves by minDeltaMs. */
export function usePointResource<T>(key: string | null, fetcher: (at: number) => Promise<T>, minDeltaMs = 1000, intervalMs = 1000): { data: T | null; status: Status } {
  const [st, setSt] = useState<{ data: T | null; status: Status }>({ data: null, status: "loading" });
  const f = useRef(fetcher);
  f.current = fetcher;
  useEffect(() => {
    setSt({ data: null, status: "loading" });
    if (!key) return;
    let alive = true;
    let inFlight = false;
    let lastAt = -1e12;
    let retryAt = 0;
    let ok = false;
    const tick = async () => {
      if (!alive || inFlight || !CLOCK.ready || performance.now() < retryAt) return;
      const t = Math.floor(CLOCK.t);
      if (Math.abs(t - lastAt) < minDeltaMs) return;
      inFlight = true;
      try {
        const d = await f.current(t);
        if (!alive) return;
        lastAt = t;
        ok = true;
        setSt({ data: d, status: "ready" });
      } catch (e) {
        if (!alive) return;
        retryAt = performance.now() + (isMissing(e) ? 15000 : 5000);
        if (!ok) setSt({ data: null, status: isMissing(e) ? "missing" : "error" });
      } finally {
        inFlight = false;
      }
    };
    void tick();
    const id = setInterval(tick, intervalMs);
    const off = CLOCK.onSeek(() => void tick());
    return () => {
      alive = false;
      clearInterval(id);
      off();
    };
  }, [key, minDeltaMs, intervalMs]);
  return st;
}

/** Fetched at the start of the clock's `stepMs` bucket so viewers share backend caches; a backwards seek clears it. */
export function useBucketResource<T>(key: string | null, stepMs: number, fetcher: (at: number) => Promise<T>): { data: T | null; status: Status; at: number } {
  const [st, setSt] = useState<{ data: T | null; status: Status; at: number }>({ data: null, status: "loading", at: -1 });
  const f = useRef(fetcher);
  f.current = fetcher;
  useEffect(() => {
    setSt({ data: null, status: "loading", at: -1 });
    if (!key) return;
    let alive = true;
    let inFlight = false;
    let have = -1;
    let retryAt = 0;
    let ok = false;
    const tick = async () => {
      if (!alive || inFlight || !CLOCK.ready) return;
      const at = Math.floor(CLOCK.t / stepMs) * stepMs;
      if (at === have) return;
      if (at < have) { have = -1; ok = false; setSt({ data: null, status: "loading", at: -1 }); }
      if (performance.now() < retryAt) return;
      inFlight = true;
      try {
        const d = await f.current(at);
        if (!alive) return;
        if (CLOCK.t < at) return;   // rewound mid-flight: drop the later cut
        have = at;
        ok = true;
        setSt({ data: d, status: "ready", at });
      } catch (e) {
        if (!alive) return;
        retryAt = performance.now() + (isUnavailable(e) ? 20000 : 5000);
        if (!ok) setSt({ data: null, status: isUnavailable(e) ? "missing" : "error", at: -1 });
      } finally {
        inFlight = false;
      }
    };
    void tick();
    const id = setInterval(tick, 1000);
    const off = CLOCK.onSeek(() => void tick());
    return () => {
      alive = false;
      clearInterval(id);
      off();
    };
  }, [key, stepMs]);
  return st;
}

/** One fetch per key (e.g. the state at the end of a recap scope). */
export function useKeyed<T>(key: string | null, fetcher: () => Promise<T>): { data: T | null; status: Status } {
  const [st, setSt] = useState<{ data: T | null; status: Status }>({ data: null, status: "loading" });
  const f = useRef(fetcher);
  f.current = fetcher;
  useEffect(() => {
    if (!key) { setSt({ data: null, status: "loading" }); return; }
    let alive = true;
    setSt((s) => ({ data: s.data, status: s.data ? "ready" : "loading" }));
    f.current().then((d) => alive && setSt({ data: d, status: "ready" }), (e) => alive && setSt({ data: null, status: isUnavailable(e) ? "missing" : "error" }));
    return () => { alive = false; };
  }, [key]);
  return st;
}

// ------------------------------------------------------------------ match list + meta
export function useMatchList(): { items: MatchListItem[]; status: Status } {
  const [st, setSt] = useState<{ items: MatchListItem[]; status: Status }>({ items: [], status: "loading" });
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const load = () => mdApi.matches().then(
      (items) => alive && setSt({ items: Array.isArray(items) ? items : [], status: "ready" }),
      (e) => {
        if (!alive) return;
        setSt((s) => ({ items: s.items, status: isMissing(e) ? "missing" : "error" }));
        timer = setTimeout(load, 5000);
      },
    );
    void load();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, []);
  return st;
}

/** /matchday/meta, falling back to a minimal meta from the match list while unavailable. */
export function useMeta(matchId: string | null, item: MatchListItem | undefined): { meta: MatchMeta | null; status: Status | "fallback" } {
  const [st, setSt] = useState<{ meta: MatchMeta | null; status: Status | "fallback"; id: string | null }>({ meta: null, status: "loading", id: null });
  const itemRef = useRef(item);
  itemRef.current = item;
  useEffect(() => {
    setSt({ meta: null, status: "loading", id: matchId });
    if (!matchId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const load = () => mdApi.meta(matchId).then(
      (meta) => alive && setSt({ meta: { ...meta, players: meta.players ?? [], periods: meta.periods ?? [] }, status: "ready", id: matchId }),
      () => {
        if (!alive) return;
        const it = itemRef.current;
        setSt((s) => (s.status === "ready" ? s : { meta: it ? fallbackMeta(it) : null, status: it ? "fallback" : "error", id: matchId }));
        timer = setTimeout(load, 15000);
      },
    );
    void load();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [matchId]);
  return st.id === matchId ? { meta: st.meta, status: st.status } : { meta: null, status: "loading" };
}

// ------------------------------------------------------------------ tracking
export interface TrackingFeed {
  buffer: TrackingBuffer;
  roster: TrackingRosterEntry[];
  status: Status | "none";
}

/** Roster plus a frame poller that buffers just ahead of the clock, capped at the live edge. */
export function useTracking(matchId: string | null, enabled: boolean): TrackingFeed {
  const buffer = useMemo(() => new TrackingBuffer(), [matchId]); // eslint-disable-line react-hooks/exhaustive-deps
  const [roster, setRoster] = useState<TrackingRosterEntry[]>([]);
  const [status, setStatus] = useState<Status | "none">("loading");
  // Match the "none" status was reported for; ignores a stale value on match change.
  const [noneFor, setNoneFor] = useState<string | null>(null);

  useEffect(() => {
    setRoster([]);
    setStatus(enabled ? "loading" : "none");
    if (!matchId || !enabled) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const load = () => mdApi.tracking(matchId).then(
      (r) => {
        if (!alive) return;
        if (!r.available) { setStatus("none"); setNoneFor(matchId); return; }
        setRoster(r.roster ?? []);
      },
      (e) => {
        if (!alive) return;
        setStatus(isMissing(e) ? "none" : "error");
        if (isMissing(e)) setNoneFor(matchId);
        else timer = setTimeout(load, 8000);
      },
    );
    void load();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [matchId, enabled]);

  useEffect(() => {
    if (!matchId || !enabled) return;
    let alive = true;
    let inFlight = false;
    let have = -1;
    let gen = 0;
    let retryAt = 0;
    let ok = false;
    buffer.reset();
    const offSeek = CLOCK.onSeek((t) => {
      const oldest = buffer.oldestT;
      if (have < 0 || t > have + 500 || oldest == null || t < oldest + 1200) {
        buffer.reset();
        have = -1;
        gen++;
      }
    });
    const tick = async () => {
      if (!alive || inFlight || !CLOCK.ready || performance.now() < retryAt) return;
      const t = CLOCK.t;
      const ahead = CLOCK.playing ? Math.max(1500, CLOCK.speed * 2000) : 300;
      const target = Math.floor(Math.min(CLOCK.edge, t + ahead));
      let from: number;
      if (have < 0) from = Math.max(-1, Math.floor(t - 1500));
      else {
        if (target <= have + 20) return;
        from = have;
      }
      if (target - from > 59000) from = target - 59000;
      if (from >= target) return;
      inFlight = true;
      const g = gen;
      try {
        const r = await mdApi.frames(matchId, from, target, 2000);
        if (!alive || g !== gen) return;
        buffer.push(r.frames ?? []);
        have = target;
        if (!ok) { ok = true; setStatus("ready"); }
      } catch (e) {
        if (!alive) return;
        retryAt = performance.now() + (isMissing(e) ? 30000 : 3000);
        if (!ok) { setStatus(isMissing(e) ? "none" : "error"); if (isMissing(e)) setNoneFor(matchId); }
      } finally {
        inFlight = false;
      }
    };
    void tick();
    const id = setInterval(tick, 200);
    return () => {
      alive = false;
      clearInterval(id);
      offSeek();
    };
  }, [matchId, enabled, buffer]);

  return { buffer, roster, status: !enabled ? "none" : status === "none" && noneFor !== matchId ? "loading" : status };
}

// ------------------------------------------------------------------ concrete resources
const byId = <X extends { id: string }>(xs: X[]) => {
  const seen = new Map<string, X>();
  for (const x of xs) seen.set(x.id, x);
  return [...seen.values()];
};

export function useSeries(matchId: string | null) {
  return useCutoffResource<SeriesResp, SeriesResp>({
    key: matchId,
    initial: { step_ms: 30000, points: [] },
    delta: false,
    due: (have, t) => Math.floor(t / 30000) > Math.floor(have / 30000),
    fetch: (_f, to) => mdApi.series(matchId!, to),
    merge: (prev, res) => {
      const pts = new Map(prev.points.map((p) => [p.t_ms, p]));
      for (const p of res.points ?? []) pts.set(p.t_ms, p);
      return { step_ms: res.step_ms || 30000, points: [...pts.values()].sort((a, b) => a.t_ms - b.t_ms) };
    },
  });
}

export function useMoments(matchId: string | null) {
  return useCutoffResource<MomentsResp, MomentsResp>({
    key: matchId,
    initial: { moments: [] },
    delta: false,
    due: (have, t) => t - have >= 1000,
    fetch: (_f, to) => mdApi.moments(matchId!, to),
    merge: (prev, res) => ({ moments: byId([...prev.moments, ...(res.moments ?? [])]).sort((a, b) => a.t_ms - b.t_ms) }),
  });
}

export function useEvents(matchId: string | null) {
  return useCutoffResource<{ events: MatchEvent[] }, MatchEvent[]>({
    key: matchId,
    initial: [],
    delta: true,
    due: (have, t) => t - have >= 1000,
    fetch: (from, to) => mdApi.events(matchId!, from, to),
    merge: (prev, res) => {
      const seen = new Set(prev.map((e) => e.event_id));
      const add = (res.events ?? []).filter((e) => !seen.has(e.event_id));
      return add.length ? [...prev, ...add].sort((a, b) => a.match_elapsed_ms - b.match_elapsed_ms) : prev;
    },
  });
}

export interface CommentaryData { tts: "azure" | "none"; lines: CommentaryResp["lines"] }
export function useCommentaryData(matchId: string | null, lang: Lang, onBatch: (res: CommentaryResp, from: number, to: number) => void) {
  return useCutoffResource<CommentaryResp, CommentaryData>({
    key: matchId ? `${matchId}|${lang}` : null,
    initial: { tts: "none", lines: [] },
    delta: true,
    intervalMs: 500,
    due: (have, t) => t - have >= 400,
    fetch: (from, to) => mdApi.commentary(matchId!, lang, from, to),
    merge: (prev, res) => ({ tts: res.tts ?? prev.tts, lines: byId([...prev.lines, ...(res.lines ?? [])]).sort((a, b) => a.t_ms - b.t_ms) }),
    onBatch,
  });
}

export function useMatchState(matchId: string | null) {
  return usePointResource<MatchState>(matchId, (at) => mdApi.state(matchId!, at), 1000, 1000);
}

export function usePlayerFocus(matchId: string | null, playerId: string | null) {
  return usePointResource<PlayerFocus>(matchId && playerId ? `${matchId}|${playerId}` : null, (at) => mdApi.player(matchId!, playerId!, at), 2000, 1000);
}
