"use client";

// Live shape per team. Measured when 8+ outfield players were seen in the last 5 s;
// otherwise estimated positions fill in and values show as approximate.

import { CLOCK } from "@/lib/matchday/clock";
import { teamShort } from "@/lib/matchday/match";
import { shapesAt } from "@/lib/matchday/shape";
import { teamVar, useMD } from "./context";
import { NoTracking, StateNote } from "./StateNote";

/** Metres: "~" and grey when estimated, "–" when missing. */
export function Approx({ v, est, tip, warnAbove }: { v: number | null | undefined; est: boolean; tip: string; warnAbove?: number }) {
  if (v == null || !Number.isFinite(v)) return <>–</>;
  const r = Math.round(v);
  if (est) return <span className="approx" title={tip}>~{r}</span>;
  return <span style={warnAbove != null ? { color: r <= warnAbove ? "var(--good)" : "var(--warn)" } : undefined}>{r}</span>;
}

export default function ShapeCards({ compact }: { compact?: boolean }) {
  const md = useMD();
  const { U, meta, lang, tracking, hasTracking } = md;
  if (!hasTracking) return <NoTracking />;
  const newest = tracking.buffer.newestT;
  if (tracking.status !== "ready" || newest == null) return <StateNote status={tracking.status === "none" ? "missing" : tracking.status === "ready" ? "loading" : tracking.status} />;
  const shapes = shapesAt(tracking.buffer, md.idxInfo, Math.min(CLOCK.view, newest));
  return (
    <div className="grid-2" style={{ gap: 10 }}>
      {([0, 1] as const).map((ti) => {
        const sh = shapes[ti];
        const est = !!sh?.estimated;
        return (
          <div key={ti} className="tile" style={{ borderTop: `4px solid ${teamVar(ti)}` }}>
            <div className="k">{teamShort(ti ? meta.away : meta.home, lang)} · {U.shapeNow}</div>
            <div className="stat-row" style={{ gridTemplateColumns: "repeat(3,1fr)", gap: 6, marginTop: 4 }}>
              <div><div className="v"><Approx v={sh?.length} est={est} tip={U.estTip} warnAbove={35} /><small>m</small></div><div className="k">{U.length}</div></div>
              <div><div className="v"><Approx v={sh?.width} est={est} tip={U.estTip} warnAbove={40} /><small>m</small></div><div className="k">{U.width}</div></div>
              <div><div className="v"><Approx v={sh?.def?.height} est={est} tip={U.estTip} /><small>m</small></div><div className="k">{U.defLine}</div></div>
            </div>
            {!sh && <div className="s">{U.shapeNA}</div>}
            {sh && est && <div className="s approx-note" title={U.estTip}>◐ {U.shapeEst(sh.observed, sh.n)}</div>}
            {sh && !compact && (
              <div className="s mono">
                {U.gapDM} <Approx v={sh.gapDM} est={est} tip={U.estTip} /> m · {U.gapMA} <Approx v={sh.gapMA} est={est} tip={U.estTip} /> m · {U.area} <Approx v={sh.area} est={est} tip={U.estTip} /> m²
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
