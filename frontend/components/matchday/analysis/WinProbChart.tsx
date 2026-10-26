"use client";

// Home / draw / away probability (at the end of the phase) over the match, with goal markers.

import type { PredSeries } from "@/lib/matchday/analysis";
import { clockLabel, teamShort } from "@/lib/matchday/match";
import { teamVar, useMD } from "../context";
import TimeChart, { type TMarker } from "./TimeChart";

export default function WinProbChart({ series, label }: { series: PredSeries; label: string }) {
  const { meta, lang, U, events, clock } = useMD();
  const t = clock.t;
  const pts = (xs: { t_ms: number; p: number }[] | undefined): [number, number][] => (xs ?? []).filter((q) => q.t_ms <= t).map((q) => [q.t_ms, 100 * q.p]);
  const markers: TMarker[] = events.data
    .filter((e) => (e.is_goal || e.is_own_goal) && !e.is_shootout && e.match_elapsed_ms <= t)
    .map((e) => {
      const side = e.team_id === meta.away.team_id ? 1 : 0;
      return { t: e.match_elapsed_ms, color: teamVar(side), label: `${clockLabel(meta.periods, e.match_elapsed_ms)} · ${teamShort(side ? meta.away : meta.home, lang)}` };
    });
  return (
    <TimeChart ariaLabel={label} yMin={0} yMax={100} unit="%" markers={markers} yTicks={[0, 25, 50, 75, 100]}
      series={[
        { name: teamShort(meta.home, lang), color: teamVar(0), values: pts(series.win[meta.home.team_id]) },
        { name: U.draw, color: "var(--contested)", values: pts(series.draw), width: 1.6 },
        { name: teamShort(meta.away, lang), color: teamVar(1), values: pts(series.win[meta.away.team_id]) },
      ]} />
  );
}
