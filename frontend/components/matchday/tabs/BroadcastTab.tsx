"use client";

// Broadcast cues: 16:9 preview stage, cue sheet and the live JSON payload a graphics renderer would poll.

import { useMemo } from "react";
import { CLOCK } from "@/lib/matchday/clock";
import { cuesFor, highlightJson, livePayload } from "@/lib/matchday/cues";
import { clockLabel, idxOfPlayer, teamShort } from "@/lib/matchday/match";
import { L, OBSERVED_MAX_AGE_MS, W } from "@/lib/matchday/shape";
import { teamVar, useMD } from "../context";
import PersonaStrip from "../PersonaStrip";
import Pitch from "../Pitch";
import { StateNote } from "../StateNote";

export default function BroadcastTab() {
  const md = useMD();
  const { U, meta, lang, view, clock, moments, ctx, score, tracking, idxInfo } = md;
  const t = clock.t;
  const all = moments.data.moments;
  const cues = useMemo(() => cuesFor(all, view, lang, ctx), [all, view, lang, ctx]);
  const active = cues.filter((c) => c.t_in * 1000 <= t && t < c.t_out * 1000 + 20000 && c.relevance >= 0.1);
  const shown = active.filter((c) => c.layer === "lower_third").slice(-1)[0];
  const tag = active.filter((c) => c.layer === "tag").slice(-1)[0];
  const bug = active.filter((c) => c.layer === "bug").slice(-1)[0];
  const list = cues.filter((c) => c.t_in * 1000 <= t && c.t_in * 1000 >= t - 1200000 && c.relevance >= 0.1).slice(-14).reverse();
  const now = clockLabel(meta.periods, t);
  const json = JSON.stringify(livePayload({ ctx, view, lang, t, clock: now, score, active }), null, 2);
  let tagPos: [number, number] | null = null;
  if (tag?.player && md.hasTracking) {
    const idx = idxOfPlayer(idxInfo, tag.player.id);
    const newest = tracking.buffer.newestT;
    const rt = newest != null ? Math.min(CLOCK.view, newest) : 0;
    const fr = idx != null && newest != null ? tracking.buffer.frameAt(rt) : null;
    const pl = fr?.players.find((p) => p.idx === idx);
    if (pl?.observed) tagPos = [pl.x, pl.y];
    else if (idx != null && newest != null) {   // off camera: last seen spot (<= 5 s), else no tag
      const o = tracking.buffer.lastObserved(rt, OBSERVED_MAX_AGE_MS).get(idx);
      if (o) tagPos = [o.x, o.y];
    }
  }
  return (
    <div className="col">
      <div className="hero"><div className="kicker">{U.tabs.broadcast}</div><h2>{U.bcTitle}</h2><p>{U.bcSub}</p></div>
      <PersonaStrip />
      <div className="grid-live wider-side">
        <div className="col">
          <div className="bc-stage">
            <Pitch overlays={{}} shapeTeams={[]} compact fill />
            <div className="bc-safe"><span>{U.safe}</span></div>
            <div className="bc-bug">
              <div style={{ background: "var(--home)", color: "#fff" }}>{teamShort(meta.home, lang)}</div>
              <div style={{ background: "#fff", color: "#0a1020" }}>{score[0]}–{score[1]}</div>
              <div style={{ background: "var(--away)", color: "#fff" }}>{teamShort(meta.away, lang)}</div>
              <div style={{ background: "var(--accent)", color: "#0a1020" }}>{now}</div>
            </div>
            {bug && <div className="bc-tag" style={{ left: "82%", top: "14%", borderLeftColor: "var(--chaos)" }}>{bug.text.headline}</div>}
            {tag && tagPos && (
              <div className="bc-tag" style={{ left: `${(tagPos[0] / L) * 100}%`, top: `${8 + (tagPos[1] / W) * 84}%`, borderLeftColor: teamVar(tag.side) }}>{tag.text.headline}</div>
            )}
            {shown && (
              <div className="bc-l3 lower3" key={shown.cue_id} style={{ position: "absolute", "--l3c": teamVar(shown.side) } as React.CSSProperties}>
                <div className="min">{shown.clock}</div><div className="txt"><b>{shown.text.headline}</b><span>{shown.text.body}</span></div>
              </div>
            )}
          </div>
          <div className="card">
            <div className="card-h"><h3>{U.cueSheet}</h3><span className="tag">{cues.length} {U.cues} · {lang.toUpperCase()}</span></div>
            <div className="card-b scroll-x">
              {moments.status !== "ready" && !cues.length ? <StateNote status={moments.status} /> : (
                <table className="cues">
                  <thead><tr><th>{U.tin}</th><th>{U.tout}</th><th>{U.template}</th><th>{U.layer}</th><th>{U.prio}</th><th>{U.text}</th></tr></thead>
                  <tbody>
                    {list.map((c) => (
                      <tr key={c.cue_id} className={c.t_in * 1000 <= t && t < c.t_out * 1000 ? "active" : ""}>
                        <td className="mono">{c.clock}</td><td className="mono">+{Math.round(c.t_out - c.t_in)}{U.seconds}</td><td className="mono">{c.template}</td>
                        <td>{c.layer}</td><td className="mono">P{c.priority}</td><td style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis" }}>{c.text.headline}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
        <div className="card">
          <div className="card-h"><h3>{U.payload}</h3><span className="tag">application/json</span></div>
          <div className="card-b"><pre className="json" dangerouslySetInnerHTML={{ __html: highlightJson(json) }} /></div>
        </div>
      </div>
    </div>
  );
}
