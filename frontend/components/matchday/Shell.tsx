"use client";

// Matchday shell: owns the match, clock, view prefs, polled data and commentary; tabs read them via context.
// Also owns the single live pitch stage (see Stage), shortcuts, palette and pop-ups so they work on every tab.

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useEvents, useMatchList, useMatchState, useMeta, useMoments, usePlayerFocus, useSeries, useTracking } from "@/lib/matchday/api";
import { CLOCK, useClock } from "@/lib/matchday/clock";
import { useCommentary } from "@/lib/matchday/commentary";
import { onHandoff } from "@/lib/matchday/handoff";
import { UI } from "@/lib/matchday/i18n";
import { useAiTake, useInsights } from "@/lib/matchday/analysis";
import {
  DEFAULT_INSIGHT_SETTINGS, DEFAULT_PLAYER_PREFS, loadInsightSettings, loadPlayerPrefs, MINI_W, PipController, pipSupported, saveInsightSettings,
  savePlayerPrefs, useInsightToasts, type InsightSettings, type PipInfo, type PlayerPrefs,
} from "@/lib/matchday/live";
import { clockMMSS, defaultPlayer, indexRoster, msOfMinute, playerShort, teamColors, teamName, teamShort } from "@/lib/matchday/match";
import { DEFAULT_VIEW, makeCtx, personaLabel, relevance, renderInsight, type View } from "@/lib/matchday/perspective";
import type { MatchListItem } from "@/lib/matchday/types";
import { MatchdayCtx, type Matchday } from "./context";
import Drawer from "./Drawer";
import Header, { Logo, MatchPicker, TABS, type TabKey } from "./Header";
import Help from "./live/Help";
import { LiveCtx, type LiveCtl, type Lower } from "./live/LiveCtx";
import Palette from "./live/Palette";
import Stage, { type StageVariant } from "./live/Stage";
import Toasts from "./live/Toasts";
import type { HitList } from "./Pitch";
import BroadcastTab from "./tabs/BroadcastTab";
import FlowTab from "./tabs/FlowTab";
import LiveTab from "./tabs/LiveTab";
import PlayerTab from "./tabs/PlayerTab";
import RecapsTab from "./tabs/RecapsTab";
import ShapeTab from "./tabs/ShapeTab";
import StoriesTab from "./tabs/StoriesTab";
import AITab from "./tabs/AITab";
import CoachTab from "./tabs/CoachTab";
import ModelsTab from "./tabs/ModelsTab";
import PreMatchTab from "./tabs/PreMatchTab";
import ShotsTab from "./tabs/ShotsTab";
import TacticalTab from "./tabs/TacticalTab";

const PREFS = "fiq.matchday.view";
const TAB_KEY = "fiq.matchday.tab";
/** Tabs with their own pitch; no miniplayer. */
const PITCH_TABS: TabKey[] = ["live", "shape", "broadcast", "player"];
const useIsoLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

function loadPrefs(): Partial<View> {
  try { return JSON.parse(localStorage.getItem(PREFS) ?? "null") ?? {}; } catch { return {}; }
}
function savePrefs(v: View) {
  try { localStorage.setItem(PREFS, JSON.stringify(v)); } catch { /* storage blocked: keep in memory */ }
}
function sanitize(p: Partial<View>): View {
  const v = { ...DEFAULT_VIEW, ...p, alerts: { ...DEFAULT_VIEW.alerts, ...(p.alerts ?? {}) } };
  if (v.fav !== 0 && v.fav !== 1) v.fav = 0;
  if (!["en", "es", "hi"].includes(v.lang)) v.lang = "en";
  if (!["dark", "light", "auto"].includes(v.theme)) v.theme = "dark";
  if (!["fan", "casual", "coach", "analyst", "player"].includes(v.persona)) v.persona = "fan";
  return v;
}

export default function Shell() {
  const list = useMatchList();
  const [matchId, setMatchId] = useState<string | null>(null);
  const [view, setViewRaw] = useState<View>(DEFAULT_VIEW);
  const viewRef = useRef<View>(view);
  viewRef.current = view;
  const [tab, setTabRaw] = useState<TabKey>("live");
  const [drawer, setDrawer] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [lower, setLower] = useState<Lower | null>(null);
  const wanted = useRef<{ match: string | null; minute: number | null }>({ match: null, minute: null });
  const clock = useClock();

  // ---- live player state
  const [prefs, setPrefsRaw] = useState<PlayerPrefs>(DEFAULT_PLAYER_PREFS);
  const [sel, setSel] = useState<number | null>(null);
  const [theatre, setTheatre] = useState(false);
  const [help, setHelp] = useState(false);
  const [palette, setPalette] = useState(false);
  const [miniClosed, setMiniClosed] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [pipOn, setPipOn] = useState(false);
  const [pipOk, setPipOk] = useState(false);
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  const [insSettings, setInsSettingsRaw] = useState<InsightSettings>(DEFAULT_INSIGHT_SETTINGS);
  const dockRef = useRef<HTMLDivElement>(null);
  const parkRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hitsRef = useRef<HitList | null>(null);
  const zoomRef = useRef<((d: number) => void) | null>(null);
  const pip = useMemo(() => new PipController(), []);
  const pipInfo = useRef<PipInfo | null>(null);

  // ---- mount: prefs, tab (hash, else last), ?match= and ?t=<minutes>, clock loop
  useEffect(() => {
    setViewRaw(sanitize(loadPrefs()));
    setPrefsRaw(loadPlayerPrefs());
    setInsSettingsRaw(loadInsightSettings());
    setPipOk(pipSupported());
    const fromHash = () => {
      const h = window.location.hash.slice(1) as TabKey;
      if (TABS.includes(h)) { setTabRaw(h); return true; }
      return false;
    };
    if (!fromHash()) {
      try { const last = localStorage.getItem(TAB_KEY) as TabKey | null; if (last && TABS.includes(last)) setTabRaw(last); } catch { /* storage blocked */ }
    }
    window.addEventListener("hashchange", fromHash);
    const q = new URLSearchParams(window.location.search);
    const tm = q.get("t");
    wanted.current = { match: q.get("match"), minute: tm != null && tm !== "" && Number.isFinite(+tm) ? Math.max(0, +tm) : null };
    const stop = CLOCK.start();
    const el = document.createElement("div");
    el.className = "stage-host";
    setHost(el);
    const offPip = pip.onChange(setPipOn);
    return () => { stop(); offPip(); window.removeEventListener("hashchange", fromHash); };
  }, [pip]);

  useEffect(() => {
    if (!host) return;
    const f = () => setFullscreen(document.fullscreenElement === host);
    document.addEventListener("fullscreenchange", f);
    return () => document.removeEventListener("fullscreenchange", f);
  }, [host]);

  const setView = useCallback((v: View) => { setViewRaw(v); savePrefs(v); }, []);
  const setTab = useCallback((k: TabKey) => {
    setTabRaw(k);
    try { history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${k}`); } catch { /* ignore */ }
    try { localStorage.setItem(TAB_KEY, k); } catch { /* storage blocked */ }
  }, []);
  const setPrefs = useCallback((p: Partial<PlayerPrefs>) => setPrefsRaw((cur) => { const next = { ...cur, ...p }; savePlayerPrefs(next); return next; }), []);
  const setInsSettings = useCallback((s: InsightSettings) => { setInsSettingsRaw(s); saveInsightSettings(s); }, []);

  // ---- cross-panel handoffs
  useEffect(() => onHandoff((h) => {
    if (h.type === "tab") setTab(h.tab);
    else if (h.type === "ask" || h.type === "explain") setTab("ai");
    else if (h.type === "coach") setTab("coach");
    else if (h.type === "focus") { setView({ ...viewRef.current, favPlayer: h.playerId }); if (h.tab) setTab(h.tab); }
    else if (h.type === "seek") CLOCK.seek(Math.max(0, h.t_ms - (h.lead_ms ?? 0)));
  }), [setTab, setView]);

  const chooseMatch = useCallback((id: string) => {
    if (!id) return;
    CLOCK.hold();   // nothing polls the new match until its clock is set
    setLower(null);
    setSel(null);
    setMatchId(id);
    try {
      const u = new URL(window.location.href);
      u.searchParams.set("match", id);
      u.searchParams.delete("t");
      history.replaceState(null, "", u.toString());
    } catch { /* ignore */ }
  }, []);

  // ---- default match
  useEffect(() => {
    if (matchId || !list.items.length) return;
    const w = wanted.current.match;
    const pick = list.items.find((m) => m.match_id === w) ?? list.items.find((m) => m.featured) ?? list.items[0];
    CLOCK.hold();
    setMatchId(pick.match_id);
  }, [list.items, matchId]);

  const item: MatchListItem | undefined = list.items.find((m) => m.match_id === matchId);
  const { meta, status: metaStatus } = useMeta(matchId, item);

  // ---- reset the clock once per match (kickoff or ?t=)
  const clockFor = useRef<string | null>(null);
  useEffect(() => {
    if (!meta || !matchId) return;   // useMeta only returns meta for the current matchId
    if (clockFor.current === matchId) {
      if (!meta.fallback) CLOCK.setDuration(meta.duration_ms);
      return;
    }
    clockFor.current = matchId;
    const minute = wanted.current.minute;
    wanted.current.minute = null;
    CLOCK.reset(meta.duration_ms, minute != null ? msOfMinute(meta.periods, minute) : 0, true);
  }, [meta, matchId]);

  // ---- data, all bounded by the clock
  const lang = view.lang;
  const U = UI[lang];
  const ready = !!meta && clockFor.current === matchId;
  const id = ready ? matchId : null;
  const tracking = useTracking(id, !!meta?.has_tracking);
  const hasTracking = !!meta?.has_tracking && tracking.status !== "none";
  const series = useSeries(id);
  const moments = useMoments(id);
  const events = useEvents(id);
  const state = useMatchState(id);
  const commentary = useCommentary(id, lang, clock.playing);
  const focusId = view.favPlayer && meta?.players.some((p) => p.player_id === view.favPlayer) ? view.favPlayer : meta ? defaultPlayer(meta, view.fav) : null;
  const needFocus = tab === "player" || (tab === "live" && view.metric !== "none");
  const focus = usePlayerFocus(id, needFocus ? focusId : null);
  // insights + AI takes, shared with the Coach / AI tabs
  const ins = useInsights(id);
  const { toasts, dismiss } = useInsightToasts(id, ins.insights, clock.t, insSettings);
  const { takes, request: requestAi } = useAiTake(id);
  useEffect(() => {   // auto AI take for priority 1-2 pop-ups
    if (insSettings.aiTakes) toasts.filter((x) => x.priority <= 2).forEach((x) => requestAi(x.id));
  }, [toasts, insSettings.aiTakes, requestAi]);

  // drop a favourite player not in this match
  useEffect(() => {
    if (meta && !meta.fallback && view.favPlayer && !meta.players.some((p) => p.player_id === view.favPlayer)) setView({ ...view, favPlayer: null });
  }, [meta]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- theme + language on the document
  useEffect(() => {
    const el = document.documentElement;
    el.lang = lang;
    if (view.theme === "auto") el.removeAttribute("data-theme"); else el.setAttribute("data-theme", view.theme);
  }, [view.theme, lang]);

  const t = clock.t;
  const ctx = useMemo(() => (meta ? makeCtx(meta, moments.data.moments, series.data.points) : null), [meta, moments.data, series.data]);
  const idxInfo = useMemo(() => indexRoster(tracking.roster, meta), [tracking.roster, meta]);
  const colors = useMemo(() => teamColors(meta), [meta]);
  const points = useMemo(() => series.data.points.filter((p) => p.t_ms <= t), [series.data, t]);
  const point = points.length ? points[points.length - 1] : null;
  const score: [number, number] = useMemo(() => {
    const s = state.data?.score;
    if (meta && s && s[meta.home.team_id] != null && s[meta.away.team_id] != null) return [s[meta.home.team_id], s[meta.away.team_id]];
    return ctx ? ctx.scoreAt(t) : [0, 0];
  }, [state.data, meta, ctx, t]);

  // ---- lower thirds + alerts for fresh moments; skip what a seek jumped over
  const popped = useRef(new Set<string>());
  const lastT = useRef(0);
  const lastWin = useRef<number | null>(null);
  useEffect(() => { popped.current = new Set(); lastT.current = 0; lastWin.current = null; }, [matchId]);
  useEffect(() => {
    if (!ctx || !meta) return;
    const prev = lastT.current;
    lastT.current = t;
    const jumped = t < prev || t - prev > 90000;
    const cands = moments.data.moments.filter((m) => m.t_ms <= t && !popped.current.has(m.id));
    cands.forEach((m) => popped.current.add(m.id));
    if (jumped) return;
    const window_ = 10000 * Math.max(1, clock.speed);
    const fresh = cands.filter((m) => t - m.t_ms <= window_).map((m) => ({ m, r: relevance(m, view) })).filter((x) => x.r >= 0.18).sort((a, b) => b.r - a.r)[0];
    if (fresh) {
      const r = renderInsight(fresh.m, view, lang, ctx);
      setLower({ id: fresh.m.id, t_ms: fresh.m.t_ms, clock: fresh.m.clock, side: fresh.m.side, h: r.h, b: r.b, kind: String(fresh.m.kind), player: fresh.m.player_id });
    }
    const goal = cands.find((m) => m.kind === "goal" && t - m.t_ms <= window_ && focusId && (m.player_id === focusId || m.player2_id === focusId));
    if (view.alerts.goal && goal && view.favPlayer) {
      const p = ctx.players.get(view.favPlayer);
      if (p) setToast(U.goalAlert(playerShort(p, lang)));
    }
  }, [t, moments.data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const w = point?.win;
    if (!w || !meta) return;
    const mine = view.fav === 0 ? w[0] : w[2];
    const before = lastWin.current;
    lastWin.current = mine;
    if (view.alerts.win && before != null && before >= 0.3 && mine < 0.3) setToast(U.winAlert(teamName(view.fav ? meta.away : meta.home, lang)));
  }, [point?.t_ms]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!lower) return; const k = setTimeout(() => setLower(null), 7000); return () => clearTimeout(k); }, [lower?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!toast) return; const k = setTimeout(() => setToast(null), 2600); return () => clearTimeout(k); }, [toast]);

  // ---- fullscreen + picture-in-picture
  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) { void document.exitFullscreen().catch(() => undefined); return; }
    if (!host || !host.requestFullscreen) return;
    host.requestFullscreen().catch(() => undefined);
  }, [host]);
  const togglePip = useCallback(() => {
    const L = UI[viewRef.current.lang];
    pip.toggle(() => canvasRef.current, () => pipInfo.current,
      { toggle: () => CLOCK.toggle(), seekBy: (ms) => CLOCK.seekBy(ms), play: () => CLOCK.setPlaying(true), pause: () => CLOCK.setPlaying(false) }, L.pipL)
      .catch(() => setToast(L.pipFailed));
  }, [pip]);

  // ---- stage placement: Live tab slot, miniplayer dock or off-screen park
  const showMini = !PITCH_TABS.includes(tab) && !miniClosed;
  const variant: StageVariant = tab === "live" && slot ? "full" : showMini ? "mini" : "parked";
  useIsoLayoutEffect(() => {
    if (!host || (typeof document !== "undefined" && document.fullscreenElement === host)) return;
    const target = variant === "full" ? slot : variant === "mini" ? dockRef.current : parkRef.current;
    if (target && host.parentNode !== target) target.appendChild(host);
  });
  useEffect(() => { if (tab === "live") setMiniClosed(false); }, [tab]);
  useEffect(() => { setSel(null); }, [matchId]);

  // ---- keyboard shortcuts, on every tab
  const kb = useRef({ tab, sel, theatre, captions: prefs.captions, help, palette, hasTracking, pipOk });
  kb.current = { tab, sel, theatre, captions: prefs.captions, help, palette, hasTracking, pipOk };
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((v) => !v); return; }
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || el?.isContentEditable || e.metaKey || e.ctrlKey || e.altKey) return;
      if (document.querySelector('[aria-modal="true"]')) return;   // dialogs handle their own keys
      const s = kb.current;
      const onControl = tag === "BUTTON" || tag === "A" || tag === "SUMMARY";
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      let fn: (() => void) | null = null;
      switch (key) {
        case " ": case "k": if (!(onControl && key === " ")) fn = () => CLOCK.toggle(); break;
        case "j": fn = () => CLOCK.seekBy(-10000); break;
        case "l": fn = () => CLOCK.seekBy(10000); break;
        case "ArrowLeft": fn = () => CLOCK.seekBy(-5000); break;
        case "ArrowRight": fn = () => CLOCK.seekBy(5000); break;
        case "ArrowUp": fn = () => CLOCK.stepSpeed(1); break;
        case "ArrowDown": fn = () => CLOCK.stepSpeed(-1); break;
        case "f": fn = toggleFullscreen; break;
        case "t": fn = () => { if (s.tab !== "live") { setTab("live"); setTheatre(true); } else setTheatre(!s.theatre); }; break;
        case "i": if (s.pipOk && s.hasTracking) fn = togglePip; break;
        case "c": fn = () => setPrefs({ captions: !s.captions }); break;
        case "?": fn = () => setHelp((v) => !v); break;
        case "Escape": if (s.sel != null) fn = () => setSel(null); break;
      }
      if (fn) { e.preventDefault(); fn(); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [toggleFullscreen, togglePip, setTab, setPrefs]);

  // ---- sticky header height (--top-h) so toasts sit below it
  useEffect(() => {
    const hd = document.querySelector<HTMLElement>("header.top");
    if (!hd) return;
    const ro = new ResizeObserver(() => document.documentElement.style.setProperty("--top-h", `${Math.round(hd.getBoundingClientRect().height)}px`));
    ro.observe(hd);
    return () => ro.disconnect();
  }, [ready]);

  const closeDrawer = useCallback(() => setDrawer(false), []);
  const setOv = useCallback((ov: PlayerPrefs["ov"]) => setPrefs({ ov }), [setPrefs]);
  const toggleOv = useCallback((k: keyof PlayerPrefs["ov"]) => setPrefsRaw((cur) => {
    const next = { ...cur, ov: { ...cur.ov, [k]: !cur.ov[k] } };
    savePlayerPrefs(next);
    return next;
  }), []);
  const setCam = useCallback((cam: PlayerPrefs["cam"]) => setPrefs({ cam }), [setPrefs]);
  const setTeam = useCallback((team: PlayerPrefs["team"]) => setPrefs({ team }), [setPrefs]);
  const setCaptions = useCallback((captions: boolean) => setPrefs({ captions }), [setPrefs]);
  const setMini = useCallback((mini: PlayerPrefs["mini"]) => setPrefs({ mini }), [setPrefs]);

  // ---- boot / error states before a match is ready
  if (!meta || !matchId || !ctx) {
    const msg = list.status === "error" || list.status === "missing" ? U.apiDown
      : list.status === "ready" && !list.items.length ? U.noMatches
        : metaStatus === "error" ? U.failed : U.loading;
    return (
      <div className="md">
        <header className="top"><div className="top-in boot-top"><Logo /><div />
          <div className="top-r"><MatchPicker items={list.items} value={matchId} onChange={chooseMatch} lang={lang} /></div></div></header>
        <div className="boot" role="status">{msg === U.loading && <span className="live-dot" />}{msg}</div>
      </div>
    );
  }

  const md: Matchday = {
    matchId, meta, metaStatus, lang, U, view, setView, clock, players: ctx.players, ctx, series, points, point, moments, events, state, score,
    tracking, idxInfo, hasTracking, colors, palKey: `${view.theme}|${colors.join(",")}`, commentary, focusId, focus, notify: setToast,
  };
  const mmss = clockMMSS(meta.periods, t);
  pipInfo.current = {
    home: teamShort(meta.home, lang), away: teamShort(meta.away, lang), hs: score[0], as: score[1], clock: mmss, homeColor: colors[0], awayColor: colors[1],
    playing: clock.playing, note: lower ? { text: `${lower.clock}  ${lower.h}`, color: lower.side === 0 ? colors[0] : lower.side === 1 ? colors[1] : "#ffc53d" } : toasts[0] ? { text: `${toasts[0].minute}  ${toasts[0].title}`, color: "#ffc53d" } : null,
  };
  const live: LiveCtl = {
    ov: prefs.ov, setOv, toggleOv, cam: prefs.cam, setCam, team: prefs.team, setTeam, sel, setSel, theatre, setTheatre, captions: prefs.captions, setCaptions,
    help, setHelp, palette, setPalette, mini: prefs.mini, setMini, miniClosed, setMiniClosed, fullscreen, toggleFullscreen, pipOn, pipOk, togglePip,
    setSlot, canvasRef, hitsRef, zoomRef, lower,
    insights: { all: ins.insights, status: ins.status, toasts, dismiss, settings: insSettings, setSettings: setInsSettings, takes, requestAi },
  };
  const persona = personaLabel(view, lang, meta, ctx.players);
  const miniW = MINI_W[prefs.mini];
  return (
    <MatchdayCtx.Provider value={md}>
      <LiveCtx.Provider value={live}>
        <div className="md" style={{ "--home": colors[0], "--away": colors[1] } as React.CSSProperties}>
          <Header items={list.items} onMatch={chooseMatch} tab={tab} setTab={setTab} openDrawer={() => setDrawer(true)} personaText={persona} />
          <main lang={lang}>
            {meta.fallback && <div className="note warn" role="status">{U.metaFallback}</div>}
            {tab === "live" && <LiveTab />}
            {tab === "stories" && <StoriesTab />}
            {tab === "shape" && <ShapeTab />}
            {tab === "flow" && <FlowTab />}
            {tab === "player" && <PlayerTab />}
            {tab === "recaps" && <RecapsTab />}
            {tab === "broadcast" && <BroadcastTab />}
            {tab === "prematch" && <PreMatchTab />}
            {tab === "tactical" && <TacticalTab />}
            {tab === "shots" && <ShotsTab />}
            {tab === "models" && <ModelsTab />}
            {tab === "coach" && <CoachTab />}
            {tab === "ai" && <AITab />}
          </main>
          <footer>{U.footer} {U.startHint}</footer>

          <div ref={dockRef} className="dock" hidden={variant !== "mini"} style={{ width: miniW, height: Math.round(miniW * 0.66) }} aria-label={U.tabs.live} role="region" />
          <div ref={parkRef} className="park" aria-hidden="true" />
          {!PITCH_TABS.includes(tab) && miniClosed && (
            <button className="reopen" onClick={() => setMiniClosed(false)} aria-label={U.mini.reopen}>
              <span className="live-dot" style={{ animation: clock.playing ? undefined : "none" }} />
              {U.live} {mmss} · {teamShort(meta.home, lang)} {score[0]}–{score[1]} {teamShort(meta.away, lang)}
            </button>
          )}
          {host && createPortal(<Stage variant={variant} />, host)}

          <Toasts />
          {drawer && <Drawer close={closeDrawer} items={list.items} onMatch={chooseMatch} />}
          {palette && <Palette items={list.items} onMatch={chooseMatch} setTab={setTab} />}
          {help && <Help />}
          {toast && <div className="toast" role="status">{toast}</div>}
        </div>
      </LiveCtx.Provider>
    </MatchdayCtx.Provider>
  );
}
