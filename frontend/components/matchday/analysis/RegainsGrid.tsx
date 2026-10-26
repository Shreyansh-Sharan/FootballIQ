"use client";

// Ball regains per zone: 6 x 4 grid of 17.5 x 17 m cells.

import type { TacticalWindow } from "@/lib/matchday/analysis";
import { useA } from "./common";
import MiniPitch from "./MiniPitch";

export default function RegainsGrid({ data }: { data: TacticalWindow }) {
  const A = useA();
  const max = Math.max(1, ...data.regains.map((r) => r.regains));
  const cells = new Map(data.regains.map((r) => [`${r.zx}-${r.zy}`, r.regains]));
  const total = data.regains.reduce((s, r) => s + r.regains, 0);
  return (
    <MiniPitch label={A.regainsN(total)}>
      {Array.from({ length: 6 }, (_, zx) => Array.from({ length: 4 }, (_, zy) => {
        const n = cells.get(`${zx}-${zy}`) ?? 0;
        return (
          <g key={`${zx}-${zy}`}>
            <rect x={zx * 17.5 + 0.3} y={zy * 17 + 0.3} width={16.9} height={16.4} rx={1} fill="var(--accent)" opacity={n ? 0.18 + (0.62 * n) / max : 0.04} />
            {n > 0 && <text x={zx * 17.5 + 8.75} y={zy * 17 + 10.6} textAnchor="middle" fontSize={5.2} fontWeight={800} fill="#fff"
              style={{ paintOrder: "stroke", stroke: "rgba(0,0,0,.55)", strokeWidth: 0.6, fontFamily: "var(--mono)" }}>{n}</text>}
          </g>
        );
      }))}
    </MiniPitch>
  );
}
