"use client";

// Occupancy heatmap: tracking samples per 5 m x 4.9 m cell (21 x 14), softened with a blur.

import { useId } from "react";
import type { TacticalWindow } from "@/lib/matchday/analysis";
import { useA } from "./common";
import MiniPitch, { PH } from "./MiniPitch";

export default function HeatGrid({ data, color }: { data: TacticalWindow; color: string }) {
  const A = useA();
  const fid = `heat${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const max = Math.max(1, ...data.heatmap.map((c) => c.samples));
  const ch = PH / 14;
  return (
    <MiniPitch label={A.heat} defs={<filter id={fid}><feGaussianBlur stdDeviation={2.2} /></filter>}>
      <g filter={`url(#${fid})`}>
        {data.heatmap.map((c) => {
          const v = c.samples / max;
          return v < 0.04 ? null : <rect key={`${c.cx}-${c.cy}`} x={c.cx * 5} y={c.cy * ch} width={5} height={ch} fill={color} opacity={Math.min(0.92, 0.2 + 0.8 * v)} />;
        })}
      </g>
    </MiniPitch>
  );
}
