"use client";

// Shape tab: live pitch, unit table from the current frame and series charts (backend 30 s medians).

import { useState } from "react";
import { CLOCK } from "@/lib/matchday/clock";
import { clockLabel, teamName, teamShort } from "@/lib/matchday/match";
import { shapesAt, type UnitLine } from "@/lib/matchday/shape";
import type { ShapeStat, SideIdx } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";
import LineChart, { smooth, type ChartSeries } from "../LineChart";
import Pitch from "../Pitch";
import ShapeCards, { Approx } from "../ShapeCards";
import { NoTracking, StateNote } from "../StateNote";

export default function ShapeTab() {
  const md = useMD();
  const { U, meta, lang, clock, series, hasTracking, tracking } = md;
  const [team, setTeam] = useState<0 | 1 | 2>(0);
  const sel: SideIdx[] = team === 2 ? [0, 1] : [team];
  const ser = (key: keyof ShapeStat): ChartSeries[] => sel.map((k) => ({
    name: teamShort(k ? meta.away : meta.home, lang), color: teamVar(k),
    values: smooth(series.data.points.map((p): [number, number | null] => [p.t_ms, p.shape?.[k]?.[key] ?? null])),
  }));
  const newest = tracking.buffer.newestT;
  const shapes = hasTracking && newest != null ? shapesAt(tracking.buffer, md.idxInfo, Math.min(CLOCK.view, newest)) : [null, null];
  const rows = sel.flatMap((ti) => {
    const sh = shapes[ti];
    const r: [string, UnitLine | null | undefined, number | null | undefined][] = [["def", sh?.def, sh?.gapDM], ["mid", sh?.mid, sh?.gapMA], ["att", sh?.att, null]];
    return r.map(([k, ln, gap]) => ({ ti, k: k as "def" | "mid" | "att", ln, gap, est: !!sh?.estimated }));
  });
  const anyShape = series.data.points.some((p) => p.shape?.some((s) => s));
  return (
    <div className="col">
      <div className="hero"><div className="kicker">{U.tabs.shape}</div><h2>{U.shapeTitle}</h2><p>{U.shapeSub}</p></div>
      <div className="seg" style={{ alignSelf: "flex-start" }} role="radiogroup" aria-label={U.team}>
        {([0, 1, 2] as const).map((v) => (
          <button key={v} className={team === v ? "on" : ""} role="radio" aria-checked={team === v} onClick={() => setTeam(v)}>
            {v < 2 ? teamName(v ? meta.away : meta.home, lang) : U.both}
          </button>
        ))}
      </div>
      {!hasTracking ? (
        <div className="card"><div className="card-b"><NoTracking /></div></div>
      ) : (
        <div className="grid-live wide-side">
          <Pitch overlays={{ shape: true, hull: true, dims: true, ref: true, names: false, speed: false, trail: false }} shapeTeams={sel} />
          <div className="card">
            <div className="card-h"><h3>{U.lineW} · {U.height}</h3><span className="tag">{clockLabel(meta.periods, clock.t)}</span></div>
            <div className="card-b scroll-x">
              <table className="ptable">
                <thead><tr><th>{U.team}</th><th>{U.unit}</th><th>{U.height}</th><th>{U.lineW}</th><th>{U.gapUp}</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.ti}${r.k}`}>
                      <td><span className="swatch" style={{ background: teamVar(r.ti) }} />{teamShort(r.ti ? meta.away : meta.home, lang)}</td>
                      <td>{U[r.k]}</td>
                      <td className="mono"><Approx v={r.ln?.height} est={r.est} tip={U.estTip} />{r.ln ? " m" : ""}</td>
                      <td className="mono"><Approx v={r.ln?.width} est={r.est} tip={U.estTip} />{r.ln ? " m" : ""}</td>
                      <td className="mono" style={{ color: !r.est && r.gap != null && r.gap > 14 ? "var(--warn)" : "inherit" }}><Approx v={r.gap} est={r.est} tip={U.estTip} />{r.gap != null ? " m" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <ShapeCards compact />
              <div className="defs">
                <div className="def"><b>{U.length}</b><span className="dim">{U.defLen}</span><code>max(x) − min(x), outfield, team frame</code></div>
                <div className="def"><b>{U.width}</b><span className="dim">{U.defWid}</span><code>max(y) − min(y)</code></div>
                <div className="def"><b>{U.lineW}</b><span className="dim">{U.defLineW}</span><code>max(y) − min(y) within DEF / MID / ATT</code></div>
                <div className="def"><b>{U.compactRef}</b><span className="dim">{U.defRef}</span><code>length ≤ 35 m · width ≤ 40 m · unit gaps ≤ 14 m</code></div>
              </div>
            </div>
          </div>
        </div>
      )}
      {hasTracking && (series.status !== "ready" ? <StateNote status={series.status} /> : !anyShape ? <StateNote status="ready" empty={U.shapeNAsub} /> : (
        <div className="grid-charts">
          <div className="card"><div className="card-h"><h3>{U.length}</h3><span className="tag">{U.overTime}</span></div>
            <div className="card-b"><LineChart ariaLabel={U.length} series={ser("length")} yMin={20} yMax={70} unit=" m" bands={[{ from: 20, to: 35, fill: "var(--good)", label: U.compactLbl }]} /></div></div>
          <div className="card"><div className="card-h"><h3>{U.width}</h3><span className="tag">{U.overTime}</span></div>
            <div className="card-b"><LineChart ariaLabel={U.width} series={ser("width")} yMin={20} yMax={68} unit=" m" bands={[{ from: 20, to: 40, fill: "var(--good)", label: U.compactLbl }]} /></div></div>
          <div className="card"><div className="card-h"><h3>{U.defLine}</h3><span className="tag">{U.own}</span></div>
            <div className="card-b"><LineChart ariaLabel={U.defLine} series={ser("def")} yMin={0} yMax={70} unit=" m" refs={[{ y: 52.5, label: U.halfway, color: "var(--mute)" }]} /></div></div>
          <div className="card"><div className="card-h"><h3>{U.gapDM}</h3><span className="tag">{U.overTime}</span></div>
            <div className="card-b"><LineChart ariaLabel={U.gapDM} series={ser("gap_dm")} yMin={0} yMax={30} unit=" m" refs={[{ y: 14, label: U.refGap }]} /></div></div>
        </div>
      ))}
    </div>
  );
}
