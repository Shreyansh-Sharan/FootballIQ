"use client";

// /welcome landing page. The hero preview loops 20 s of real tracking around a goal of the featured match.

import "@/app/matchday-analysis.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { API_URL } from "@/lib/api";
import { mdApi, useMatchList } from "@/lib/matchday/api";
import { AU } from "@/lib/matchday/i18n-analysis";
import { UI } from "@/lib/matchday/i18n";
import { clockMMSS, playerShort, teamColors, teamName, teamShort } from "@/lib/matchday/match";
import type { ThemeMode } from "@/lib/matchday/perspective";
import type { Lang, MatchMeta, Moment } from "@/lib/matchday/types";
import { TrackingBuffer, type WireFrame } from "@/lib/trackingBuffer";
import { LangSeg, Logo, TAB_GROUPS, nextTheme } from "../Header";
import { I } from "../Icons";

const PREFS = "fiq.matchday.view";
const BEFORE = 14000, AFTER = 6000;

function readPrefs(): { lang: Lang; theme: ThemeMode } {
  try {
    const p = JSON.parse(localStorage.getItem(PREFS) ?? "null") ?? {};
    return { lang: ["en", "es", "hi"].includes(p.lang) ? p.lang : "en", theme: ["dark", "light", "auto"].includes(p.theme) ? p.theme : "dark" };
  } catch { return { lang: "en", theme: "dark" }; }
}
function writePrefs(patch: Partial<{ lang: Lang; theme: ThemeMode }>) {
  try {
    const p = JSON.parse(localStorage.getItem(PREFS) ?? "null") ?? {};
    localStorage.setItem(PREFS, JSON.stringify({ ...p, ...patch }));
  } catch { /* storage blocked: keep in memory */ }
}

/** Most important assisted open-play goal, else any open-play goal, else any goal. */
function pickGoal(ms: Moment[]): Moment | null {
  const goals = ms.filter((m) => m.kind === "goal");
  const open = goals.filter((m) => !m.f?.pen && !m.f?.own_goal);
  const assisted = open.filter((m) => m.player2_id);
  const by = (xs: Moment[]) => [...xs].sort((a, b) => b.imp - a.imp)[0];
  return (assisted.length ? by(assisted) : open.length ? by(open) : goals.length ? by(goals) : null) ?? null;
}

interface Pv { meta: MatchMeta; goal: Moment | null; from: number; to: number; sides: Map<number, { side: 0 | 1; jersey: string }> }

function Preview({ lang }: { lang: Lang }) {
  const A = AU[lang].land;
  const list = useMatchList();
  const featured = list.items.find((m) => m.featured) ?? list.items.find((m) => m.completeness?.continuous_tracking) ?? list.items[0];
  const [pv, setPv] = useState<Pv | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [score, setScore] = useState<[number, number] | null>(null);
  const [clock, setClock] = useState("");
  const buffer = useMemo(() => new TrackingBuffer(), []);
  const cv = useRef<HTMLCanvasElement>(null);
  const tRef = useRef(0);

  useEffect(() => {
    if (list.status === "error" || list.status === "missing") { setState("error"); return; }
    if (!featured) return;
    let alive = true;
    const id = featured.match_id;
    (async () => {
      try {
        const meta = await mdApi.meta(id);
        const ms = await fetch(`${API_URL}/v1/matches/${encodeURIComponent(id)}/matchday/moments?to_ms=${Math.floor(meta.duration_ms)}`, { cache: "no-store" })
          .then((r) => (r.ok ? r.json() : { moments: [] })).catch(() => ({ moments: [] }));
        const goal = pickGoal(ms.moments ?? []);
        const centre = goal?.t_ms ?? Math.min(meta.duration_ms, 20 * 60000);
        const from = Math.max(0, centre - BEFORE), to = Math.min(meta.duration_ms, centre + AFTER);
        const [tr, fr] = await Promise.all([mdApi.tracking(id), mdApi.frames(id, from, to, 900)]);
        if (!alive) return;
        const sides = new Map<number, { side: 0 | 1; jersey: string }>();
        for (const r of tr.roster ?? []) sides.set(r.idx, { side: r.team_id === meta.away.team_id ? 1 : 0, jersey: r.jersey });
        buffer.reset((fr.frames ?? []) as WireFrame[]);
        if (!tr.available || !(fr.frames ?? []).length) { setState("error"); return; }
        setPv({ meta, goal, from, to, sides });
        setState("ready");
      } catch {
        if (alive) setState("error");
      }
    })();
    return () => { alive = false; };
  }, [featured?.match_id, list.status, buffer]); // eslint-disable-line react-hooks/exhaustive-deps

  // reduced motion: a still of the goal frame
  useEffect(() => {
    if (!pv) return;
    const c = cv.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const [home, away] = teamColors(pv.meta);
    const W = 111, H = 74, M = 3;
    let raf = 0;
    const start = performance.now();
    const span = Math.max(1000, pv.to - pv.from);
    const draw = (now: number) => {
      const r = c.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = Math.max(200, Math.round(r.width * dpr)), h = Math.round((w * H) / W);
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
      const s = w / W;
      const cs = getComputedStyle(c);
      const g = (k: string, d: string) => cs.getPropertyValue(k).trim() || d;
      const t = reduce && pv.goal ? pv.goal.t_ms : pv.from + ((now - start) % span);
      tRef.current = t;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = g("--pitch-edge", "#0d2f20"); ctx.fillRect(0, 0, w, h);
      ctx.setTransform(s, 0, 0, s, M * s, M * s);
      for (let i = 0; i < 12; i++) { ctx.fillStyle = i % 2 ? g("--pitch-b", "#154a32") : g("--pitch-a", "#123f2b"); ctx.fillRect((i * 105) / 12, 0, 105 / 12 + 0.05, 68); }
      ctx.strokeStyle = g("--chalk", "rgba(235,245,238,0.72)"); ctx.lineWidth = 0.3;
      ctx.strokeRect(0, 0, 105, 68); ctx.beginPath(); ctx.moveTo(52.5, 0); ctx.lineTo(52.5, 68); ctx.stroke();
      ctx.beginPath(); ctx.arc(52.5, 34, 9.15, 0, Math.PI * 2); ctx.stroke();
      ctx.strokeRect(0, 13.84, 16.5, 40.32); ctx.strokeRect(88.5, 13.84, 16.5, 40.32); ctx.strokeRect(0, 24.84, 5.5, 18.32); ctx.strokeRect(99.5, 24.84, 5.5, 18.32);
      const fr = buffer.frameAt(t);
      if (fr) {
        const trail = buffer.ballTrail(t, 3000, 2);
        if (trail.length > 1) {
          ctx.strokeStyle = "rgba(255,255,255,0.45)"; ctx.lineWidth = 0.35; ctx.beginPath();
          trail.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y))); ctx.stroke();
        }
        ctx.font = `700 1.5px ${g("--mono", "monospace")}`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        for (const p of fr.players) {
          const who = pv.sides.get(p.idx);
          if (!who) continue;
          const col = who.side ? away : home;
          ctx.globalAlpha = p.observed ? 1 : 0.6;
          ctx.beginPath(); ctx.arc(p.x, p.y, 1.45, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill();
          ctx.lineWidth = 0.2; ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.setLineDash(p.observed ? [] : [0.4, 0.3]); ctx.stroke(); ctx.setLineDash([]);
          ctx.fillStyle = "#fff"; ctx.fillText(who.jersey, p.x, p.y + 0.05);
          ctx.globalAlpha = 1;
        }
        if (fr.ball) {
          ctx.beginPath(); ctx.arc(fr.ball.x, fr.ball.y, 0.75, 0, Math.PI * 2);
          ctx.fillStyle = fr.ball.observed ? "#ffffff" : "rgba(255,255,255,0.55)"; ctx.fill();
          ctx.lineWidth = 0.2; ctx.strokeStyle = "#0a1020"; ctx.stroke();
        }
      }
      if (!reduce) raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [pv, buffer]);

  // score + clock at the loop time, 1 Hz
  useEffect(() => {
    if (!pv) return;
    let alive = true;
    const tick = () => {
      const t = Math.floor(tRef.current || pv.from);
      setClock(clockMMSS(pv.meta.periods, t));
      mdApi.state(pv.meta.match_id, t).then((s) => {
        if (alive) setScore([s.score?.[pv.meta.home.team_id] ?? 0, s.score?.[pv.meta.away.team_id] ?? 0]);
      }).catch(() => undefined);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => { alive = false; clearInterval(id); };
  }, [pv]);

  const meta = pv?.meta;
  const scorer = meta && pv?.goal?.player_id ? meta.players.find((p) => p.player_id === pv.goal!.player_id) : undefined;
  const goalTeam = meta && pv?.goal ? (pv.goal.side === 1 ? meta.away : meta.home) : null;
  return (
    <div className="an-prev" style={meta ? ({ "--home": teamColors(meta)[0], "--away": teamColors(meta)[1] } as React.CSSProperties) : undefined}>
      <div className="an-prev-top">
        <span className="live-dot" aria-hidden="true" />
        <span className="tag">{A.liveClock}</span>
        <span className="an-grow" />
        {meta && (
          <span className="disp" style={{ fontWeight: 800, fontSize: 20, display: "inline-flex", gap: 10, textTransform: "uppercase" }}>
            <span style={{ color: "var(--home)" }}>{teamShort(meta.home, lang)}</span>
            <span>{score ? `${score[0]} – ${score[1]}` : "– –"}</span>
            <span style={{ color: "var(--away)" }}>{teamShort(meta.away, lang)}</span>
          </span>
        )}
        {clock && <span className="chip" style={{ fontSize: 12 }}>{clock}</span>}
      </div>
      <div className="an-prev-stage">
        {state === "ready" && <canvas ref={cv} role="img" aria-label={A.previewAria(goalTeam ? teamName(goalTeam, lang) : "")} />}
        {state !== "ready" && (
          <div className="note" role="status">{state === "loading" && <span className="spin" aria-hidden="true" />}<span>{state === "loading" ? A.previewLoading : A.previewNA}</span></div>
        )}
      </div>
      <div className="an-row" style={{ justifyContent: "space-between", padding: "10px 4px 0", fontSize: 13 }}>
        <span className="dim">{scorer && goalTeam ? A.previewCaption(playerShort(scorer, lang), teamName(goalTeam, lang)) : meta ? `${teamName(meta.home, lang)} v ${teamName(meta.away, lang)}` : ""}</span>
        <span className="an-mono-note">{A.previewSrc}</span>
      </div>
      {meta && <div className="an-mono-note" style={{ padding: "4px 4px 0" }}>{meta.competition}{meta.stage ? ` · ${meta.stage}` : ""} · {meta.date}</div>}
    </div>
  );
}

export default function Landing() {
  const [lang, setLang] = useState<Lang>("en");
  const [theme, setTheme] = useState<ThemeMode>("dark");
  useEffect(() => { const p = readPrefs(); setLang(p.lang); setTheme(p.theme); }, []);
  useEffect(() => {
    const el = document.documentElement;
    el.lang = lang;
    if (theme === "auto") el.removeAttribute("data-theme"); else el.setAttribute("data-theme", theme);
  }, [lang, theme]);
  const U = UI[lang];
  const A = AU[lang].land;
  const tabs = TAB_GROUPS.flatMap(([g, ks]) => ks.map((k) => [g, k] as const));
  const watch = <a className="btn an-big" href="/">{I.play}{A.watchLive}</a>;
  return (
    <div className="md an-land" lang={lang}>
      <header className="an-land-top">
        <div className="in">
          <Logo />
          <nav className="an-land-nav" aria-label="Sections">
            <a href="#how">{A.how}</a><a href="#product">{A.product}</a><a href="#roles">{A.roles}</a>
          </nav>
          <span className="an-grow" />
          <LangSeg lang={lang} onLang={(l) => { setLang(l); writePrefs({ lang: l }); }} />
          <button className="iconbtn" aria-label={`${U.theme}: ${U.themes[theme]}`} title={`${U.theme}: ${U.themes[theme]}`}
            onClick={() => { const n = nextTheme(theme); setTheme(n); writePrefs({ theme: n }); }}>
            {theme === "light" ? I.sun : theme === "dark" ? I.moon : I.auto}
          </button>
          <a className="btn" href="/" style={{ textDecoration: "none" }}>{A.watchLive}</a>
        </div>
      </header>

      <main style={{ maxWidth: "none", padding: 0, gap: 0 }}>
        <section className="an-land-hero" aria-labelledby="land-h1">
          <div className="col" style={{ gap: 20 }}>
            <div className="kicker">{A.heroKicker}</div>
            <h1 id="land-h1">{A.heroTitle}</h1>
            <p className="lead">{A.heroSub}</p>
            <div className="an-row" style={{ gap: 14 }}>{watch}<span className="dim">{A.heroNote}</span></div>
            <div className="an-mono-note" style={{ paddingTop: 10, borderTop: "1px solid var(--line)" }}>{A.heroMeta}</div>
          </div>
          <Preview lang={lang} />
        </section>

        <section id="how" className="an-land-sec" aria-labelledby="land-how">
          <div className="hero"><div className="kicker">{A.how}</div><h2 id="land-how">{A.howTitle}</h2></div>
          <div className="an-steps">
            {A.steps.map(([n, title, text, tech]) => (
              <div key={n} className="card an-step">
                <span className="n">{n}</span>
                <h3>{title}</h3>
                <p className="dim" style={{ lineHeight: 1.55 }}>{text}</p>
                <span className="an-mono-note" style={{ marginTop: "auto" }}>{tech}</span>
              </div>
            ))}
          </div>
        </section>

        <section id="product" className="an-land-sec" aria-labelledby="land-product">
          <div className="hero"><div className="kicker">{A.product}</div><h2 id="land-product">{A.productTitle(tabs.length)}</h2><p>{A.productSub}</p></div>
          <div className="an-feat">
            {tabs.map(([g, k]) => (
              <a key={k} className="card" href={`/#${k}`}>
                <div className="an-row" style={{ justifyContent: "space-between" }}>
                  <span className="ic" aria-hidden="true">{I[k]}</span>
                  <span className="tag">{U.tabGroups[g]}</span>
                </div>
                <h3>{U.tabs[k]}</h3>
                <p className="dim" style={{ lineHeight: 1.5, fontSize: 14 }}>{A.tabDesc[k]}</p>
                <span className="kicker" style={{ marginTop: "auto" }}>{AU[lang].open} →</span>
              </a>
            ))}
          </div>
        </section>

        <section id="roles" className="an-land-sec" aria-labelledby="land-roles">
          <div className="hero"><div className="kicker">{A.roles}</div><h2 id="land-roles">{A.rolesTitle}</h2></div>
          <div className="an-roles">
            {A.roleList.map(([r, text]) => (
              <div key={r} className="an-role"><h3>{r}</h3><p className="dim" style={{ fontSize: 16, lineHeight: 1.55 }}>{text}</p></div>
            ))}
          </div>
        </section>

        <section className="an-land-sec" aria-labelledby="land-cta" style={{ paddingTop: 24 }}>
          <div className="card an-km an-cta">
            <div className="col an-grow" style={{ gap: 8, minWidth: "min(100%, 320px)", position: "relative", zIndex: 1 }}>
              <h2 id="land-cta" style={{ fontSize: "clamp(30px, 4vw, 44px)" }}>{A.ctaTitle}</h2>
              <p className="dim" style={{ fontSize: 16 }}>{A.ctaSub}</p>
            </div>
            <div style={{ position: "relative", zIndex: 1 }}>{watch}</div>
          </div>
          <p className="an-small" style={{ maxWidth: 820 }}>{A.disclaimer}</p>
        </section>
      </main>
    </div>
  );
}
