"use client";

// Control & Rhythm tab. Calibration ranges follow docs/MATCHDAY_API.md.

import { clockLabel, teamShort } from "@/lib/matchday/match";
import type { Pattern } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";
import { ChaosMeter, RhythmStrip } from "../Instruments";
import LineChart, { smooth } from "../LineChart";
import { StateNote } from "../StateNote";

const norm = (v: number, a: number, b: number) => Math.max(0, Math.min(1, (v - a) / (b - a)));
const RULES: Pattern[] = ["stop_start", "end_to_end", "siege", "settled", "high_tempo", "balanced"];

export default function FlowTab() {
  const { U, meta, lang, clock, point, points, series } = useMD();
  const w = point?.flow ?? null;
  const hero = <div className="hero"><div className="kicker">{U.tabs.flow}</div><h2>{U.flowTitle}</h2><p>{U.flowSub}</p></div>;
  if (!w) return <div className="col">{hero}<StateNote status={series.status === "ready" ? "loading" : series.status} /></div>;
  const c = w.comp;
  const comps: [keyof typeof U.compNames, number, string, number][] = [
    ["turnovers", 0.3, c.turnovers.toFixed(1), norm(c.turnovers, 0.2, 1.0)],
    ["duels", 0.2, c.duels.toFixed(1), norm(c.duels, 0.6, 2.0)],
    ["transitions", 0.2, c.transitions.toFixed(1), norm(c.transitions, 0, 0.4)],
    ["longShare", 0.15, `${Math.round(100 * c.long_share)}%`, norm(c.long_share, 0.05, 0.2)],
    ["avgSeq", 0.15, c.avg_seq.toFixed(1), 1 - norm(c.avg_seq, 3.4, 10)],
  ];
  const fp = (k: (p: (typeof points)[number]) => number | null | undefined) => points.map((p): [number, number | null] => [p.t_ms, p.flow ? k(p) ?? null : null]);
  return (
    <div className="col">
      {hero}
      <div className="grid-2">
        <div className="card">
          <div className="card-h"><h3>{U.controlChaos}</h3><span className="tag">{clockLabel(meta.periods, clock.t)} · 5′</span></div>
          <div className="card-b">
            <ChaosMeter flow={w} />
            <div className="tag">{U.howDefined}</div>
            <div className="def"><b>{U.chaos}</b><code>chaos = 100 × (0.30·turnovers + 0.20·duels + 0.20·transitions + 0.15·long balls + 0.15·(1 − passes per possession))</code>
              <span className="dim" style={{ fontSize: 13 }}>{U.chaosNote}</span></div>
            <div className="def"><b>{U.control}</b><code>control(team) = 100 × (0.35·possession + 0.25·pass accuracy (0.58–0.925) + 0.25·settled possessions + 0.15·final-third share)</code>
              <span className="dim" style={{ fontSize: 13 }}>{U.controlNote}</span></div>
            <div className="tag">{U.components}</div>
            <div>
              {comps.map(([k, wt, val, n]) => (
                <div key={k} className="comp"><span>{U.compNames[k]}</span><span className="mono">{val}</span>
                  <span className="bar"><i style={{ width: `${Math.round(n * 100)}%`, background: "var(--chaos)" }} /></span><span className="mono mute">×{wt}</span></div>
              ))}
            </div>
            <div className="stat-row">
              {([0, 1] as const).map((k) => (
                <div key={k} className="tile" style={{ borderTop: `4px solid ${teamVar(k)}` }}>
                  <div className="k">{U.control} {teamShort(k ? meta.away : meta.home, lang)}</div>
                  <div className="v">{Math.round(w.control?.[k] ?? 0)}<small>/100</small></div>
                  <div className="s">{Math.round(100 * (w.poss_share?.[k] ?? 0))}% · {w.pass_acc?.[k] != null ? `${Math.round(100 * w.pass_acc[k]!)}%` : "–"}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="card">
          <div className="card-h"><h3>{U.rhythm}</h3><span className="chip" style={{ background: `var(--p-${w.pattern})`, color: "#fff", border: 0 }}>{U.patterns[w.pattern] ?? w.pattern}</span></div>
          <div className="card-b">
            <div className="stat-row">
              <div className="tile"><div className="k">{U.tempo}</div><div className="v">{w.tempo.toFixed(1)}<small>/{U.perMin}</small></div></div>
              <div className="tile"><div className="k">{U.bip}</div><div className="v">{Math.round(100 * w.bip)}<small>%</small></div></div>
              <div className="tile"><div className="k">{U.stops}</div><div className="v">{w.stops}<small>/5′</small></div></div>
              <div className="tile"><div className="k">{U.seq}</div><div className="v">{c.avg_seq.toFixed(1)}</div></div>
              <div className="tile"><div className="k">{U.tilt}</div><div className="v">{Math.round(100 * w.tilt)}<small>% {teamShort(meta.home, lang)}</small></div></div>
            </div>
            <div className="dim">{U.patternDesc[w.pattern]}</div>
            <div className="tag">{U.rules}</div>
            <div className="scroll-x">
              <table className="ptable">
                <thead><tr><th>{U.pattern}</th><th>{U.rule}</th></tr></thead>
                <tbody>
                  {RULES.map((k) => (
                    <tr key={k} className={w.pattern === k ? "now" : ""}>
                      <td><span className="swatch" style={{ background: `var(--p-${k})` }} />{U.patterns[k]}</td>
                      <td className="mono" style={{ fontSize: 12 }}>{U.ruleText[k]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="dim" style={{ fontSize: 12 }}>{U.rulesNote}</div>
          </div>
        </div>
      </div>
      <div className="card"><div className="card-h"><h3>{U.rhythm}</h3><span className="tag">{U.overTime}</span></div><div className="card-b"><RhythmStrip /></div></div>
      <div className="grid-charts">
        <div className="card"><div className="card-h"><h3>{U.chaosOver}</h3></div><div className="card-b">
          <LineChart ariaLabel={U.chaosOver} yMin={0} yMax={100} series={[{ name: U.chaos, color: "var(--chaos)", values: fp((p) => p.flow?.chaos) }]}
            bands={[{ from: 0, to: 35, fill: "var(--control)", label: U.control.toUpperCase() }, { from: 65, to: 100, fill: "var(--chaos)", label: U.chaos.toUpperCase() }]} /></div></div>
        <div className="card"><div className="card-h"><h3>{U.controlOver}</h3></div><div className="card-b">
          <LineChart ariaLabel={U.controlOver} yMin={0} yMax={100}
            series={([0, 1] as const).map((k) => ({ name: teamShort(k ? meta.away : meta.home, lang), color: teamVar(k), values: smooth(fp((p) => p.flow?.control?.[k])) }))} /></div></div>
        <div className="card"><div className="card-h"><h3>{U.tempoOver}</h3></div><div className="card-b">
          <LineChart ariaLabel={U.tempoOver} yMin={8} yMax={28} fmt={(v) => v.toFixed(1)} series={[{ name: U.tempo, color: "var(--p-high_tempo)", values: fp((p) => p.flow?.tempo) }]}
            refs={[{ y: 17.5, label: U.high }]} /></div></div>
        <div className="card"><div className="card-h"><h3>{U.bipOver}</h3></div><div className="card-b">
          <LineChart ariaLabel={U.bipOver} yMin={0} yMax={100} unit="%" series={[{ name: U.bip, color: "var(--p-stop_start)", values: fp((p) => (p.flow ? 100 * p.flow.bip : null)) }]}
            refs={[{ y: 47, label: U.patterns.stop_start.toUpperCase() }]} /></div></div>
      </div>
    </div>
  );
}
