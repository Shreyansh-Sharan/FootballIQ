"use client";

// Line chart over the whole match (meta.periods, extra time included); lines stop at the clock.

import { useState } from "react";
import { axisTicks, clockLabel, periodBreaks } from "@/lib/matchday/match";
import { useMD } from "./context";

export interface ChartSeries { name: string; color: string; values: [number, number | null][] }
interface Band { from: number; to: number; fill: string; label: string }
interface Ref { y: number; label: string; color?: string }

/** Trailing mean over k points, skipping nulls. */
export function smooth(vals: [number, number | null][], k = 4): [number, number | null][] {
  return vals.map(([tt], i) => {
    let a = 0, n = 0;
    for (let j = Math.max(0, i - k + 1); j <= i; j++) { const v = vals[j][1]; if (v != null) { a += v; n++; } }
    return [tt, n ? a / n : null];
  });
}

export default function LineChart({ series, yMin, yMax, bands = [], refs = [], unit = "", h = 170, fmt = (v: number) => String(Math.round(v)), ariaLabel }: {
  series: ChartSeries[]; yMin: number; yMax: number; bands?: Band[]; refs?: Ref[]; unit?: string; h?: number; fmt?: (v: number) => string; ariaLabel: string;
}) {
  const { meta, clock } = useMD();
  const t = clock.t;
  const dur = Math.max(1, meta.duration_ms);
  const [hov, setHov] = useState<{ tt: number; px: number } | null>(null);
  const Wd = 600, Hd = h, ml = 34, mr = 54, mt = 10, mb = 22;
  const xs = (tt: number) => ml + ((Wd - ml - mr) * tt) / dur;
  const ys = (v: number) => mt + (Hd - mt - mb) * (1 - (v - yMin) / (yMax - yMin));
  const cl = (v: number) => Math.max(yMin, Math.min(yMax, v));
  const ticksY = [yMin, (yMin + yMax) / 2, yMax];
  const pts = (vals: [number, number | null][]) => vals.filter(([tt, v]) => tt <= t && v != null).map(([tt, v]) => `${xs(tt).toFixed(1)},${ys(cl(v!)).toFixed(1)}`).join(" ");
  const onMove = (ev: React.PointerEvent<SVGSVGElement>) => {
    const r = ev.currentTarget.getBoundingClientRect();
    const x = ((ev.clientX - r.left) / r.width) * Wd;
    const tt = Math.max(0, Math.min(t, ((x - ml) / (Wd - ml - mr)) * dur));
    setHov({ tt, px: (xs(tt) / Wd) * 100 });
  };
  const near = (vals: [number, number | null][], tt: number) => {
    let best: number | null = null, bd = 1e15;
    for (const [a, v] of vals) { const d = Math.abs(a - tt); if (d < bd && a <= t) { bd = d; best = v; } }
    return best;
  };
  const ticks = axisTicks(meta.periods, dur);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${Wd} ${Hd}`} role="img" aria-label={ariaLabel} onPointerMove={onMove} onPointerLeave={() => setHov(null)}>
        {bands.map((b, i) => (
          <g key={`b${i}`}>
            <rect x={ml} width={Wd - ml - mr} y={ys(Math.min(yMax, b.to))} height={Math.max(0, ys(Math.max(yMin, b.from)) - ys(Math.min(yMax, b.to)))} fill={b.fill} opacity="0.13" />
            <text x={Wd - mr + 6} y={(ys(Math.min(yMax, b.to)) + ys(Math.max(yMin, b.from))) / 2 + 3} style={{ font: "600 9px var(--mono)", fill: "var(--mute)" }}>{b.label}</text>
          </g>
        ))}
        <g className="grid">{ticksY.map((v) => <line key={v} x1={ml} x2={Wd - mr} y1={ys(v)} y2={ys(v)} />)}</g>
        <g className="axis">
          {ticksY.map((v) => <text key={v} x={ml - 6} y={ys(v) + 3} textAnchor="end">{Math.round(v)}</text>)}
          {ticks.map((k, i) => <text key={`x${i}`} x={xs(k.t)} y={Hd - 6} textAnchor="middle">{k.label}</text>)}
        </g>
        {periodBreaks(meta.periods).map((b) => <line key={b} x1={xs(b)} x2={xs(b)} y1={mt} y2={Hd - mb} stroke="var(--line2)" strokeDasharray="3 3" />)}
        {refs.map((r, i) => (
          <g key={`r${i}`}>
            <line x1={ml} x2={Wd - mr} y1={ys(r.y)} y2={ys(r.y)} stroke={r.color || "var(--accent)"} strokeWidth="1.5" strokeDasharray="6 4" />
            <text x={Wd - mr + 6} y={ys(r.y) + 3} style={{ font: "700 9px var(--mono)", fill: r.color || "var(--accent-text)" }}>{r.label}</text>
          </g>
        ))}
        {series.map((s) => <polyline key={s.name} points={pts(s.values)} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />)}
        {series.map((s) => {
          const last = [...s.values].reverse().find(([tt, v]) => tt <= t && v != null);
          if (!last) return null;
          const y = ys(cl(last[1]!));
          return (
            <g key={`l${s.name}`}>
              <circle cx={xs(last[0])} cy={y} r="4" fill={s.color} stroke="var(--panel)" strokeWidth="2" />
              <text x={Math.min(xs(last[0]) + 8, Wd - 50)} y={y + 4} style={{ font: "700 10px var(--mono)", fill: "var(--ink)" }}>{s.name} {fmt(last[1]!)}{unit}</text>
            </g>
          );
        })}
        {hov && <line x1={xs(hov.tt)} x2={xs(hov.tt)} y1={mt} y2={Hd - mb} stroke="var(--mute)" strokeWidth="1" />}
      </svg>
      {hov && (
        <div className="tip" style={{ left: `min(calc(${hov.px}% + 10px), calc(100% - 150px))`, top: 6 }}>
          <div className="mono mute" style={{ fontSize: 11 }}>{clockLabel(meta.periods, hov.tt)}</div>
          {series.map((s) => {
            const v = near(s.values, hov.tt);
            return <div key={s.name}><span className="swatch" style={{ background: s.color }} />{s.name} <b>{v == null ? "–" : fmt(v) + unit}</b></div>;
          })}
        </div>
      )}
    </div>
  );
}
