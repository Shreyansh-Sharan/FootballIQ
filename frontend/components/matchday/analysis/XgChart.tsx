"use client";

// Cumulative expected goals per team (solid step), dots on goals.

import type { PredSeries } from "@/lib/matchday/analysis";
import { teamShort } from "@/lib/matchday/match";
import { teamVar, useMD } from "../context";
import TimeChart, { type TSeries } from "./TimeChart";

export default function XgChart({ series, label }: { series: PredSeries; label: string }) {
  const { meta, lang, clock } = useMD();
  const t = clock.t;
  const out: TSeries[] = [];
  let max = 1;
  ([0, 1] as const).forEach((s) => {
    const tm = s ? meta.away : meta.home;
    const pts = (series.xg[tm.team_id]?.points ?? []).filter((q) => q.t_ms <= t);
    for (const q of pts) max = Math.max(max, q.ours);
    out.push({ name: `${teamShort(tm, lang)} xG`, color: teamVar(s), step: true, values: pts.map((q) => [q.t_ms, q.ours]), dots: pts.filter((q) => q.goal).map((q) => [q.t_ms, q.ours]) });
  });
  const top = Math.ceil(max * 1.15 * 2) / 2;
  return <TimeChart ariaLabel={label} yMin={0} yMax={top} fmt={(v) => v.toFixed(1)} series={out} yTicks={[0, top / 2, top]} />;
}
