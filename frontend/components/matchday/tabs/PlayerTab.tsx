"use client";

// Player Focus: one player's live numbers, actions, heat map and latest moment, with a follow cam.

import { useEffect, useRef } from "react";
import { colorsOf, playerName, sideIdx, teamName } from "@/lib/matchday/match";
import { renderInsight } from "@/lib/matchday/perspective";
import type { PlayerFocus, SideIdx } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";
import { Jersey } from "../Kit";
import Pitch from "../Pitch";
import { NoTracking, StateNote } from "../StateNote";

function Heat({ heat, palKey }: { heat: NonNullable<PlayerFocus["heat"]>; palKey: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;
    const cs = getComputedStyle(cv);
    const pa = cs.getPropertyValue("--pitch-a").trim() || "#123f2b";
    const chalk = cs.getPropertyValue("--chalk").trim() || "rgba(235,245,238,0.72)";
    const w = (cv.width = 420), h = (cv.height = 272);
    ctx.fillStyle = pa; ctx.fillRect(0, 0, w, h); ctx.strokeStyle = chalk; ctx.lineWidth = 1.5;
    ctx.strokeRect(4, 4, w - 8, h - 8); ctx.beginPath(); ctx.moveTo(w / 2, 4); ctx.lineTo(w / 2, h - 4); ctx.stroke();
    ctx.beginPath(); ctx.arc(w / 2, h / 2, 36, 0, 7); ctx.stroke();
    ctx.strokeRect(4, h / 2 - 81, 66, 162); ctx.strokeRect(w - 70, h / 2 - 81, 66, 162);
    const gx = Math.max(1, heat.cols), gy = Math.max(1, heat.rows);
    const mx = Math.max(1, ...heat.counts);
    const cw = (w - 8) / gx, ch = (h - 8) / gy;
    for (let j = 0; j < gy; j++) for (let i = 0; i < gx; i++) {
      const v = (heat.counts[j * gx + i] ?? 0) / mx;
      if (v < 0.04) continue;
      ctx.fillStyle = `rgba(255,197,61,${0.12 + v * 0.75})`;
      ctx.fillRect(4 + i * cw + 1, 4 + j * ch + 1, cw - 2, ch - 2);
    }
  }, [heat, palKey]);
  return <canvas ref={ref} style={{ width: "100%", height: "auto", borderRadius: 10 }} role="img" aria-label="Heat map" />;
}

export default function PlayerTab() {
  const md = useMD();
  const { U, meta, lang, view, setView, focus, focusId, players, moments, clock, ctx, hasTracking } = md;
  const t = clock.t;
  const p = focusId ? players.get(focusId) : undefined;
  const st = focus.data;
  const side: SideIdx = (p ? sideIdx(p.side) : null) ?? view.fav;
  const story = moments.data.moments.filter((m) => m.t_ms <= t && (m.player_id === focusId || m.player2_id === focusId)).slice(-1)[0];
  const hero = <div className="hero"><div className="kicker">{U.tabs.player}</div><h2>{U.playerTitle}</h2><p>{U.playerSub}</p></div>;
  if (!meta.players.length) return <div className="col">{hero}<StateNote status={md.metaStatus === "fallback" ? "missing" : "loading"} /></div>;
  return (
    <div className="col">
      {hero}
      <div className="pgrid">
        <div className="card">
          <div className="card-b plist" role="listbox" aria-label={U.favPlayer}>
            {([0, 1] as const).map((k) => (
              <div key={k}>
                <div className="tag" style={{ margin: "6px 0 2px" }}>{teamName(k ? meta.away : meta.home, lang)}</div>
                {meta.players.filter((x) => x.side === (k ? "away" : "home")).map((x) => (
                  <button key={x.player_id} className={`prow ${x.player_id === focusId ? "on" : ""}`} role="option" aria-selected={x.player_id === focusId}
                    onClick={() => setView({ ...view, favPlayer: x.player_id })}>
                    <span className="no" style={{ background: teamVar(k) }}>{x.number ?? "–"}</span>
                    <span className="nm">{playerName(x, lang)}</span>
                    <span className="ps">{x.position ?? x.role}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
        <div className="col">
          <div className="card"><div className="card-b">
            {p && (
              <div className="pcard">
                <Jersey colors={colorsOf(meta, side)} num={p.number} id={p.player_id} />
                <div className="col" style={{ gap: 6 }}>
                  <div className="kicker">{teamName(side ? meta.away : meta.home, lang)} · {p.position ?? p.role} · {st ? (st.on_pitch ? U.live : U.offPitch) : "—"}</div>
                  <h2>{playerName(p, lang)}</h2>
                  {story && (() => { const r = renderInsight(story, view, lang, ctx); return <div className="dim">{story.clock} · {r.h}: {r.b}</div>; })()}
                </div>
              </div>
            )}
            {!st ? <StateNote status={focus.status} /> : (
              <div className="stat-row">
                <div className="tile hl"><div className="k">{U.distance}</div><div className="v">{st.dist_km != null ? st.dist_km.toFixed(2) : "–"}<small>{U.km}</small></div></div>
                <div className="tile"><div className="k">{U.topSpeed}</div><div className="v">{st.top_kmh != null ? st.top_kmh.toFixed(1) : "–"}<small>{U.kmh}</small></div></div>
                <div className="tile"><div className="k">{U.sprints}</div><div className="v">{st.sprints ?? "–"}</div></div>
                <div className="tile"><div className="k">{U.touches}</div><div className="v">{st.touches}</div></div>
                <div className="tile"><div className="k">{U.passes}</div><div className="v">{st.passes_ok}/{st.passes}</div><div className="s">{st.passes ? Math.round((100 * st.passes_ok) / st.passes) : 0}%</div></div>
                <div className="tile"><div className="k">{U.passDiff}</div><div className="v">{st.pass_diff ?? "–"}<small>/100</small></div></div>
                <div className="tile"><div className="k">{U.shots} · xG</div><div className="v">{st.shots}<small>· {(st.xg ?? 0).toFixed(2)}</small></div></div>
                <div className="tile"><div className="k">{U.duels}</div><div className="v">{st.duels_won}</div></div>
              </div>
            )}
          </div></div>
          <div className="grid-2">
            <div className="card"><div className="card-h"><h3>{U.heat}</h3></div>
              <div className="card-b">{!st ? <StateNote status={focus.status} /> : st.heat ? <Heat heat={st.heat} palKey={md.palKey} /> : <p className="dim">{U.noHeat}</p>}</div></div>
            <div className="card"><div className="card-h"><h3>{U.actions}</h3><span className="tag">{st?.actions.length ?? 0}</span></div>
              <div className="card-b">
                {!st ? <StateNote status={focus.status} /> : !st.actions.length ? <p className="dim">{U.noActions}</p> : (
                  <div className="acts">
                    {st.actions.slice(-40).reverse().map((a, i) => (
                      <div key={`${a.t_ms}-${i}`} className="act">
                        <span className="mono">{a.clock}</span>
                        <span>{a.type.toUpperCase()}{a.detail ? ` · ${a.detail}` : ""}</span>
                        <span className={a.ok === false ? "mute" : ""}>{a.ok == null ? "" : a.ok ? "✓" : "✗"}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div></div>
          </div>
          <div className="card"><div className="card-h"><h3>{U.followCam}</h3></div>
            <div className="card-b">{hasTracking ? <Pitch overlays={{ names: true, speed: true, trail: true }} shapeTeams={[]} focus={focusId} dimOthers /> : <NoTracking />}</div></div>
        </div>
      </div>
    </div>
  );
}
