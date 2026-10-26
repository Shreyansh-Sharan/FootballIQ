"use client";

// Goal (10′), corner (2′) and penalty (5′) forecasts with bootstrap bands and top drivers (▲ raises, ▼ lowers).

import type { Forecast, ForecastKey, Predictions } from "@/lib/matchday/analysis";
import { teamName } from "@/lib/matchday/match";
import type { SideIdx } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";
import { pc, pcAuto, useA } from "./common";

const TARGETS: ForecastKey[] = ["goal_next_10m", "corner_next_2m", "penalty_next_5m"];

export function ForecastCell({ k, f }: { k: ForecastKey; f: Forecast | undefined }) {
  const A = useA();
  return (
    <div className="an-fc">
      <span className="tag">{A.targets[k]}</span>
      <span className="v">{pcAuto(f?.probability)}</span>
      <span className="mono mute" style={{ fontSize: 10.5 }}>{f?.low != null && f.high != null ? A.band(pc(f.low, 1), pc(f.high, 1)) : " "}</span>
      {(f?.drivers ?? []).slice(0, 2).map((d) => (
        <span key={d.feature} className={`an-drv ${d.contribution > 0 ? "up" : "down"}`}>
          {d.contribution > 0 ? "▲" : "▼"} {A.features[d.feature] ?? d.feature.replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}

export default function ForecastCard({ p, side }: { p: Predictions | null; side: SideIdx }) {
  const { meta, lang } = useMD();
  const tm = side ? meta.away : meta.home;
  const f = p?.teams[tm.team_id];
  return (
    <div className="an-team-block" style={{ borderLeftColor: teamVar(side) }}>
      <b style={{ color: teamVar(side), fontFamily: "var(--display)", fontSize: 18, textTransform: "uppercase" }}>{teamName(tm, lang)}</b>
      <div className="an-fc-grid">{TARGETS.map((k) => <ForecastCell key={k} k={k} f={f?.[k]} />)}</div>
    </div>
  );
}
