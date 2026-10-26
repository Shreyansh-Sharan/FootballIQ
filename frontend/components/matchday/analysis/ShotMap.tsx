"use client";

// Half-pitch shot map; shots are mirrored so the team always attacks the top goal.
// Circle area ~ xG; filled = goal, solid ring = on target, dashed = off target or blocked.

import { clockLabel } from "@/lib/matchday/match";
import type { ShotRow } from "@/lib/matchday/analysis";
import { useMD } from "../context";
import { useA, useNames } from "./common";

export const xgOf = (s: ShotRow) => s.xg;

/** Pitch metres (105 x 68) -> half-pitch SVG coords, attacked goal at the top. */
function toHalf(s: ShotRow): [number, number] {
  const flip = s.x_m < 52.5;
  const x = flip ? 105 - s.x_m : s.x_m;
  const y = flip ? 68 - s.y_m : s.y_m;
  return [y, Math.max(0, 105 - x)];
}

export default function ShotMap({ shots, color, selected, onSelect, label }: { shots: ShotRow[]; color: string; selected: string | null; onSelect: (s: ShotRow) => void; label: string }) {
  const { meta } = useMD();
  const A = useA();
  const { pName } = useNames();
  const outcome = (s: ShotRow) => A.outcomes[s.outcome ?? ""] ?? s.outcome ?? A.shotWord;
  return (
    <div className="an-shotmap">
      <svg viewBox="-3 -4 74 60" role="group" aria-label={label}>
        <rect x={-3} y={-4} width={74} height={60} fill="var(--pitch-edge)" />
        {Array.from({ length: 6 }, (_, i) => <rect key={i} x={0} y={i * 8.75} width={68} height={8.76} fill={i % 2 ? "var(--pitch-b)" : "var(--pitch-a)"} />)}
        <g fill="none" stroke="var(--chalk)" strokeWidth={0.35}>
          <rect x={0} y={0} width={68} height={52.5} />
          <rect x={13.84} y={0} width={40.32} height={16.5} />
          <rect x={24.84} y={0} width={18.32} height={5.5} />
          <rect x={30.34} y={-1.8} width={7.32} height={1.8} />
          <path d={`M ${34 - 7.3} 16.5 A 9.15 9.15 0 0 0 ${34 + 7.3} 16.5`} />
          <path d={`M ${34 - 9.15} 52.5 A 9.15 9.15 0 0 1 ${34 + 9.15} 52.5`} />
        </g>
        <circle cx={34} cy={11} r={0.35} fill="var(--chalk)" />
        {shots.map((s) => {
          const [cx, cy] = toHalf(s);
          const xg = xgOf(s);
          const r = 0.9 + 4.5 * Math.sqrt(Math.max(0, xg ?? 0.03));
          const on = selected === s.event_id;
          const txt = `${clockLabel(meta.periods, s.match_elapsed_ms)} ${pName(s.player_id, s.player_name)} · ${outcome(s)} · xG ${xg != null ? xg.toFixed(2) : "—"} · ${s.distance_m.toFixed(0)} m, ${s.angle_deg.toFixed(0)}°`;
          return (
            <circle key={s.event_id} cx={cx} cy={cy} r={r} role="button" tabIndex={0} aria-label={txt} aria-pressed={on}
              fill={s.is_goal ? color : "transparent"} fillOpacity={s.is_goal ? 0.92 : 0} stroke={on ? "var(--accent)" : color}
              strokeWidth={on ? 1 : 0.6} strokeDasharray={s.on_target ? undefined : "1 0.8"}
              onClick={() => onSelect(s)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(s); } }}>
              <title>{txt}</title>
            </circle>
          );
        })}
      </svg>
    </div>
  );
}
