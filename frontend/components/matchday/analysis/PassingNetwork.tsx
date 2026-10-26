"use client";

// Passing network: node at mean action location (size ~ passes), edge width ~ completed passes.

import type { TacticalWindow } from "@/lib/matchday/analysis";
import { useMD } from "../context";
import { useA, useNames } from "./common";
import MiniPitch from "./MiniPitch";

export default function PassingNetwork({ data, color }: { data: TacticalWindow; color: string }) {
  const { players } = useMD();
  const A = useA();
  const { pName } = useNames();
  const nodes = new Map(data.network.nodes.map((n) => [n.player_id, n]));
  const maxE = Math.max(1, ...data.network.edges.map((e) => e.passes));
  const maxN = Math.max(1, ...data.network.nodes.map((n) => n.passes));
  const total = data.network.edges.reduce((s, e) => s + e.passes, 0);
  return (
    <MiniPitch label={A.network(total)}>
      {data.network.edges.map((e, i) => {
        const a = nodes.get(e.from), b = nodes.get(e.to);
        if (!a || !b) return null;
        return (
          <line key={i} x1={a.x_m} y1={a.y_m} x2={b.x_m} y2={b.y_m} stroke={color} strokeLinecap="round"
            strokeOpacity={0.25 + (0.6 * e.passes) / maxE} strokeWidth={0.3 + (1.7 * e.passes) / maxE}>
            <title>{`${pName(e.from)} → ${pName(e.to)} · ${A.passesN(e.passes)}`}</title>
          </line>
        );
      })}
      {data.network.nodes.map((n) => {
        const r = 1.8 + (2.1 * n.passes) / maxN;
        const num = players.get(n.player_id)?.number;
        return (
          <g key={n.player_id}>
            <circle cx={n.x_m} cy={n.y_m} r={r} fill={color} stroke="#fff" strokeWidth={0.45}>
              <title>{`${pName(n.player_id)} · ${A.passesN(n.passes)}`}</title>
            </circle>
            <text x={n.x_m} y={n.y_m + 0.95} textAnchor="middle" fontSize={2.6} fontWeight={800} fill="#fff"
              style={{ paintOrder: "stroke", stroke: "rgba(0,0,0,.55)", strokeWidth: 0.5, pointerEvents: "none", fontFamily: "var(--mono)" }}>{num ?? ""}</text>
          </g>
        );
      })}
    </MiniPitch>
  );
}
