"use client";

// Two Stories: one moment told side by side for both fans, the coach and the analyst.

import { useState } from "react";
import { colorsOf, defaultPlayer, kitBackground, playerShort } from "@/lib/matchday/match";
import { personaLabel, renderInsight, type View } from "@/lib/matchday/perspective";
import type { Moment, SideIdx } from "@/lib/matchday/types";
import { useMD } from "../context";
import { PersonaIcon } from "../PersonaStrip";
import { StateNote } from "../StateNote";

export default function StoriesTab() {
  const { U, meta, lang, clock, moments, ctx, players, view } = useMD();
  const t = clock.t;
  const ms = moments.data.moments.filter((m) => m.t_ms <= t && (m.imp >= 0.3 || m.kind === "goal")).slice(-16);
  const [sel, setSel] = useState<string | null>(null);
  const m = ms.find((x) => x.id === sel) ?? [...ms].reverse().find((x) => x.kind === "goal") ?? ms[ms.length - 1];
  const views: View[] = [{ ...view, persona: "fan", fav: 0 }, { ...view, persona: "fan", fav: 1 }, { ...view, persona: "coach" }, { ...view, persona: "analyst" }];
  // most involved player so far, else the No. 10 / first forward
  const star = (side: SideIdx) => {
    const n = new Map<string, number>();
    for (const x of moments.data.moments) if (x.t_ms <= t && x.side === side && x.player_id) n.set(x.player_id, (n.get(x.player_id) ?? 0) + x.imp);
    const id = [...n.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? defaultPlayer(meta, side);
    const p = id ? players.get(id) : undefined;
    return p ? playerShort(p, lang) : "";
  };
  const focusFor = (v: View) => (v.persona === "coach" ? [U.shapeNow, U.controlChaos, U.rhythm] : v.persona === "analyst" ? ["xG", U.winChance, U.tempo] : [U.winChance, star(v.fav), U.yourFeed].filter(Boolean));
  const tone = (v: View, mm: Moment) => (v.persona !== "fan" || mm.side == null ? (v.persona === "analyst" ? 1 : 2) : mm.side === v.fav ? 5 : 4);
  const accent = (v: View) => (v.persona === "fan" ? (v.fav ? "var(--away)" : "var(--home)") : v.persona === "coach" ? "var(--control)" : "var(--accent)");
  return (
    <div className="col">
      <div className="hero"><div className="kicker">{U.tabs.stories}</div><h2>{U.storiesTitle}</h2><p>{U.storiesSub}</p></div>
      <div>
        <div className="tag" style={{ marginBottom: 8 }}>{U.pickMoment}</div>
        {!ms.length ? (moments.status === "ready" ? <p className="dim">{U.noMoments}</p> : <StateNote status={moments.status} />) : (
          <div className="moments" role="listbox" aria-label={U.pickMoment}>
            {ms.map((x) => {
              const r = renderInsight(x, { persona: "casual", fav: view.fav }, lang, ctx);
              const on = !!m && x.id === m.id;
              return (
                <button key={x.id} className={`moment ${on ? "on" : ""}`} role="option" aria-selected={on} onClick={() => setSel(x.id)}>
                  <span>{x.clock} · {x.kind}</span><b>{r.h}</b>
                </button>
              );
            })}
          </div>
        )}
      </div>
      {m && (
        <div className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))" }}>
          {views.map((v) => {
            const r = renderInsight(m, v, lang, ctx);
            const c = accent(v);
            return (
              <article key={`${v.persona}${v.fav}`} className="card story">
                <div className="band" style={{ background: v.persona === "fan" ? kitBackground(colorsOf(meta, v.fav), true) : c }} />
                <div className="ph"><PersonaIcon view={v} /><div><h3>{personaLabel(v, lang, meta, players)}</h3><div className="tag">{U.personaSub[v.persona]}</div></div></div>
                <div className="card-b">
                  <div className="say">{r.h}</div>
                  <div className="body">{r.b}</div>
                  <div className="tag">{U.sees}</div>
                  <div className="mini-l3" style={{ "--l3c": c } as React.CSSProperties}><div className="mm">{m.clock}</div><div className="tt">{r.h}</div></div>
                  <div className="tag">{U.focusNext}</div>
                  <div className="focus">{focusFor(v).map((f) => <span key={f} className="chip">{f}</span>)}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="tag">{U.tone}</span>
                    <span className="tone" aria-label={`${U.tone} ${tone(v, m)}/5`}>{[1, 2, 3, 4, 5].map((k) => <i key={k} className={k <= tone(v, m) ? "on" : ""} />)}</span>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
