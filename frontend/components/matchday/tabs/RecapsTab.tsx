"use client";

// Recaps built client-side from the moments for the current perspective and language.

import { useState } from "react";
import { mdApi, useKeyed } from "@/lib/matchday/api";
import { clockLabel, halfTimeMs } from "@/lib/matchday/match";
import { personaLabel, renderInsight } from "@/lib/matchday/perspective";
import { buildRecap, RECAP_FORMATS, RECAP_SCOPES, type RecapFormat, type RecapStats } from "@/lib/matchday/recaps";
import type { RecapScope } from "@/lib/matchday/templates";
import { useMD } from "../context";
import PersonaStrip from "../PersonaStrip";
import { StateNote } from "../StateNote";

export default function RecapsTab() {
  const md = useMD();
  const { U, meta, lang, view, setView, clock, moments, ctx, players, notify, matchId } = md;
  const [scope, setScope] = useState<RecapScope>("now");
  const [fmt, setFmt] = useState<RecapFormat>("studio");
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const t = clock.t;
  const ht = halfTimeMs(meta.periods);
  const ft = meta.duration_ms;
  const avail: Record<RecapScope, boolean> = { now: true, ht: ht != null && clock.edge >= ht, ft: clock.edge >= ft };
  const end = scope === "ht" && ht != null ? ht : scope === "ft" ? ft : t;
  // team counters at the end of the scope ("so far" in 10 s steps)
  const at = scope === "now" ? Math.floor(t / 10000) * 10000 : end;
  const stState = useKeyed(avail[scope] ? `${matchId}|${at}` : null, () => mdApi.state(matchId, at));
  const sd = stState.data;
  const h = meta.home.team_id, a = meta.away.team_id;
  const stats: RecapStats | null = sd?.stats?.[h] && sd.stats[a] ? {
    sh: [sd.stats[h].shots ?? 0, sd.stats[a].shots ?? 0], xg: [sd.stats[h].provider_xg ?? 0, sd.stats[a].provider_xg ?? 0],
    po: [Math.round(sd.stats[h].possession_pct ?? 50), Math.round(sd.stats[a].possession_pct ?? 50)],
  } : null;
  const r = avail[scope] && moments.status === "ready"
    ? buildRecap({ moments: moments.data.moments, end, endLabel: clockLabel(meta.periods, end), scope, fmt, view, lang, excluded, ctx, stats, points: md.series.data.points })
    : null;
  const words = r ? r.text.split(/\s+/).filter(Boolean).length : 0;
  const copy = () => {
    if (!r) return;
    const fail = () => notify(U.selectToCopy);
    try { navigator.clipboard?.writeText(r.text).then(() => notify(U.copied), fail); } catch { fail(); }
  };
  const toggle = (id: string) => { const s = new Set(excluded); if (s.has(id)) s.delete(id); else s.add(id); setExcluded(s); };
  return (
    <div className="col">
      <div className="hero"><div className="kicker">{U.tabs.recaps}</div><h2>{U.recapsTitle}</h2><p>{U.recapsSub}</p></div>
      <PersonaStrip />
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        <div className="seg" role="radiogroup" aria-label={U.scope.now}>
          {RECAP_SCOPES.map((k) => (
            <button key={k} className={scope === k ? "on" : ""} role="radio" aria-checked={scope === k} disabled={!avail[k]} style={{ opacity: avail[k] ? 1 : 0.45 }} onClick={() => setScope(k)}>{U.scope[k]}</button>
          ))}
        </div>
        <div className="seg" role="radiogroup" aria-label={U.format.studio}>
          {RECAP_FORMATS.map((k) => <button key={k} className={fmt === k ? "on" : ""} role="radio" aria-checked={fmt === k} onClick={() => setFmt(k)}>{U.format[k]}</button>)}
        </div>
        <label className="switch" style={{ gap: 8 }}>
          <input type="checkbox" checked={view.spoiler} onChange={(e) => setView({ ...view, spoiler: e.target.checked })} /> {U.spoiler}
        </label>
      </div>
      <div className="grid-live">
        {!avail[scope] ? <div className="recap-card"><div className="dim">{U.notYet}</div></div>
          : !r ? <div className="recap-card"><StateNote status={moments.status} /></div>
            : fmt === "push" ? (
              <div className="phone">
                <div className="notif">
                  <span className="logo" style={{ fontSize: 12 }}><span className="mark" style={{ width: 30, height: 30 }} /></span>
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}><b style={{ fontSize: 13 }}>FootballIQ</b><span className="mute" style={{ fontSize: 11 }}>{U.now}</span></div>
                    <div className="recap push" style={{ fontSize: 14 }} lang={lang}>{r.text}</div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="recap-card">
                <div className="kicker">{personaLabel(view, lang, meta, players)} · {U.format[fmt]} · {U.scope[scope]}</div>
                <div className={`recap ${fmt}`} lang={lang}>{r.text}</div>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <button className="btn" onClick={copy}>{U.copy}</button>
                  <span className="mono mute">{words} {U.words} · ~{Math.max(5, Math.round(words / 2.6))} {U.seconds} {U.readTime}</span>
                </div>
              </div>
            )}
        <div className="card">
          <div className="card-h"><h3>{U.builtFrom}</h3></div>
          <div className="card-b srcs">
            {r && !r.ranked.length && <p className="dim">{U.noMoments}</p>}
            {r && r.ranked.slice(0, 12).map(({ m, r: rel }) => {
              const rr = renderInsight(m, view, lang, ctx);
              return (
                <label key={m.id} className="src">
                  <input type="checkbox" checked={!excluded.has(m.id)} onChange={() => toggle(m.id)} />
                  <span className="mono">{m.clock}</span><span style={{ minWidth: 0 }}>{rr.h}</span>
                  <span className="bar"><i style={{ width: `${Math.min(100, Math.round(rel * 100))}%`, background: r.used.includes(m.id) ? "var(--accent)" : "var(--mute)" }} /></span>
                </label>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
