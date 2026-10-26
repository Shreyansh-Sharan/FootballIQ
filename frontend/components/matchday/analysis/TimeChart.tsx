"use client";

// Step-line chart on LineChart's match axis, with benchmark lines and goal markers; stops at the clock.

import { useState } from "react";
import { axisTicks, clockLabel, periodBreaks } from "@/lib/matchday/match";
import { useMD } from "../context";

export interface TSeries { name: string; color: string; values: [number, number][]; dash?: boolean; step?: boolean; width?: number; dots?: [number, number][] }
export interface TMarker { t: number; color: string; label: string }

export default function TimeChart({ series, yMin, yMax, fmt = (v) => v.toFixed(0), unit = "", markers = [], ariaLabel, h = 190, yTicks }: {
  series: TSeries[]; yMin: number; yMax: number; fmt?: (v: number) => string; unit?: string; markers?: TMarker[]; ariaLabel: string; h?: number; yTicks?: number[];
}) {
  const { meta, clock } = useMD();
  const t = clock.t;
  const dur = Math.max(1, meta.duration_ms);
  const [hov, setHov] = useState<{ tt: number; px: number } | null>(null);
  const Wd = 600, Hd = h, ml = 34, mr = 16, mt = 12, mb = 22;
  const xs = (tt: number) => ml + ((Wd - ml - mr) * Math.min(tt, dur)) / dur;
  const ys = (v: number) => mt + (Hd - mt - mb) * (1 - (Math.max(yMin, Math.min(yMax, v)) - yMin) / (yMax - yMin || 1));
  const ticksY = yTicks ?? [yMin, (yMin + yMax) / 2, yMax];
  const visible = (vals: [number, number][]) => vals.filter(([tt]) => tt <= t).sort((a, b) => a[0] - b[0]);
  const path = (s: TSeries) => {
    const v = visible(s.values);
    if (!v.length) return "";
    if (!s.step) return v.map(([tt, y], i) => `${i ? "L" : "M"}${xs(tt).toFixed(1)},${ys(y).toFixed(1)}`).join(" ");
    let d = `M${xs(0).toFixed(1)},${ys(0).toFixed(1)}`;
    let prev = 0;
    for (const [tt, y] of v) { d += ` L${xs(tt).toFixed(1)},${ys(prev).toFixed(1)} L${xs(tt).toFixed(1)},${ys(y).toFixed(1)}`; prev = y; }
    return d + ` L${xs(t).toFixed(1)},${ys(prev).toFixed(1)}`;
  };
  const valueAt = (s: TSeries, tt: number) => {
    const v = visible(s.values);
    if (!v.length) return s.step ? 0 : null;
    if (s.step) { let last = 0; for (const [a, y] of v) { if (a <= tt) last = y; else break; } return last; }
    let best: number | null = null, bd = 1e15;
    for (const [a, y] of v) { const d = Math.abs(a - tt); if (d < bd) { bd = d; best = y; } }
    return best;
  };
  const onMove = (ev: React.PointerEvent<SVGSVGElement>) => {
    const r = ev.currentTarget.getBoundingClientRect();
    const x = ((ev.clientX - r.left) / r.width) * Wd;
    const tt = Math.max(0, Math.min(t, ((x - ml) / (Wd - ml - mr)) * dur));
    setHov({ tt, px: (xs(tt) / Wd) * 100 });
  };
  const ticks = axisTicks(meta.periods, dur);
  const vm = markers.filter((m) => m.t <= t);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${Wd} ${Hd}`} role="img" aria-label={ariaLabel} onPointerMove={onMove} onPointerLeave={() => setHov(null)}>
        <g className="grid">{ticksY.map((v) => <line key={v} x1={ml} x2={Wd - mr} y1={ys(v)} y2={ys(v)} />)}</g>
        <g className="axis">
          {ticksY.map((v) => <text key={v} x={ml - 6} y={ys(v) + 3} textAnchor="end">{fmt(v)}</text>)}
          {ticks.map((k, i) => <text key={`x${i}`} x={xs(k.t)} y={Hd - 6} textAnchor="middle">{k.label}</text>)}
        </g>
        {periodBreaks(meta.periods).map((b) => <line key={b} x1={xs(b)} x2={xs(b)} y1={mt} y2={Hd - mb} stroke="var(--line2)" strokeDasharray="3 3" />)}
        {vm.map((m, i) => (
          <g key={`m${i}`}>
            <line x1={xs(m.t)} x2={xs(m.t)} y1={mt} y2={Hd - mb} stroke={m.color} strokeOpacity={0.5} strokeDasharray="2 3" />
            <circle cx={xs(m.t)} cy={mt - 2} r={4.5} fill={m.color} stroke="var(--panel)" strokeWidth={1.5}><title>{m.label}</title></circle>
          </g>
        ))}
        {series.map((s) => (
          <path key={s.name} d={path(s)} fill="none" stroke={s.color} strokeWidth={s.width ?? (s.dash ? 1.4 : 2.2)} strokeDasharray={s.dash ? "5 4" : undefined}
            strokeOpacity={s.dash ? 0.8 : 1} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {series.flatMap((s) => (s.dots ?? []).filter(([tt]) => tt <= t).map(([tt, v], i) => (
          <circle key={`${s.name}d${i}`} cx={xs(tt)} cy={ys(v)} r={4} fill={s.color} stroke="var(--panel)" strokeWidth={1.5} />
        )))}
        <line x1={xs(t)} x2={xs(t)} y1={mt} y2={Hd - mb} stroke="var(--accent)" strokeDasharray="3 3" />
        {hov && <line x1={xs(hov.tt)} x2={xs(hov.tt)} y1={mt} y2={Hd - mb} stroke="var(--mute)" strokeWidth="1" />}
      </svg>
      {hov && (
        <div className="tip" style={{ left: `min(calc(${hov.px}% + 10px), calc(100% - 170px))`, top: 6 }}>
          <div className="mono mute" style={{ fontSize: 11 }}>{clockLabel(meta.periods, hov.tt)}</div>
          {series.map((s) => {
            const v = valueAt(s, hov.tt);
            return <div key={s.name}><span className="swatch" style={{ background: s.color, opacity: s.dash ? 0.6 : 1 }} />{s.name} <b>{v == null ? "–" : fmt(v) + unit}</b></div>;
          })}
        </div>
      )}
    </div>
  );
}
