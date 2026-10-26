"use client";

// Win chance bar, control-vs-chaos meter and rhythm strip.

import { axisTicks, clockLabel, teamName, teamShort } from "@/lib/matchday/match";
import { PATTERNS, type Flow } from "@/lib/matchday/types";
import { useMD } from "./context";

export function WinChance() {
  const { point, meta, lang, U } = useMD();
  const win = point?.win;
  if (!win) return null;
  const [a, d, b] = win;
  const pc = (v: number) => Math.round(v * 100);
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="wc" role="img" aria-label={`${U.winChance}: ${teamName(meta.home, lang)} ${pc(a)}%, ${U.draw} ${pc(d)}%, ${teamName(meta.away, lang)} ${pc(b)}%`}>
        <div style={{ flexGrow: Math.max(a, 0.04), background: "var(--home)" }}>{teamShort(meta.home, lang)} {pc(a)}%</div>
        <div className="d" style={{ flexGrow: Math.max(d, 0.04) }}>{pc(d)}%</div>
        <div style={{ flexGrow: Math.max(b, 0.04), background: "var(--away)", justifyContent: "flex-end" }}>{pc(b)}% {teamShort(meta.away, lang)}</div>
      </div>
    </div>
  );
}

export function ChaosMeter({ flow }: { flow: Flow }) {
  const { U, meta, lang } = useMD();
  const chaos = Math.round(flow.chaos);
  const state = chaos >= 65 ? U.chaos : chaos <= 35 ? U.control : U.contested;
  const k = (flow.control?.[0] ?? 0) >= (flow.control?.[1] ?? 0) ? 0 : 1;
  return (
    <div className="col" style={{ gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div className="big">{chaos}<small>/100 · {state}</small></div>
        <span className="chip team" style={{ background: k ? "var(--away)" : "var(--home)" }}>{U.controlledBy} {teamShort(k ? meta.away : meta.home, lang)} {Math.round(flow.control?.[k] ?? 0)}</span>
      </div>
      <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={chaos} aria-label={U.controlChaos}>
        <div className="needle" style={{ left: `${Math.max(0, Math.min(100, chaos))}%` }} />
      </div>
      <div className="meter-l"><span>{U.control}</span><span>{U.contested}</span><span>{U.chaos}</span></div>
    </div>
  );
}

/** Pattern per 30 s step, placed on the whole match axis. */
export function RhythmStrip() {
  const { U, points, meta, series } = useMD();
  const dur = Math.max(1, meta.duration_ms);
  const step = series.data.step_ms || 30000;
  const pct = (v: number) => `${(100 * v) / dur}%`;
  return (
    <div className="col" style={{ gap: 6 }}>
      <div className="strip abs" role="img" aria-label={U.rhythm}>
        {points.filter((p) => p.flow).map((p) => (
          <div key={p.t_ms} title={`${p.clock || clockLabel(meta.periods, p.t_ms)} · ${U.patterns[p.flow!.pattern] ?? p.flow!.pattern}`}
            style={{ left: pct(Math.max(0, p.t_ms - step)), width: pct(step), background: `var(--p-${p.flow!.pattern})` }} />
        ))}
      </div>
      <div className="strip-axis">{axisTicks(meta.periods, dur).map((k, i) => <span key={i} style={{ left: pct(k.t) }}>{k.label}</span>)}</div>
      <div className="legend">{PATTERNS.map((k) => <span key={k}><i style={{ background: `var(--p-${k})` }} />{U.patterns[k]}</span>)}</div>
    </div>
  );
}
