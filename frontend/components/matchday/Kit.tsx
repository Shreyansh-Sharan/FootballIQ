"use client";

import { colorsOf, kitBackground, kitInk } from "@/lib/matchday/match";
import type { MatchMeta, SideIdx, TeamColors } from "@/lib/matchday/types";

/** Kit swatch: solid, stripes, hoops or tricolor. */
export function Kit({ meta, side, num }: { meta: MatchMeta | null; side: SideIdx; num?: string | number | null }) {
  const c = colorsOf(meta, side);
  return (
    <span className="kit" aria-hidden="true" style={{ background: kitBackground(c), color: kitInk(c), textShadow: c.pattern === "tricolor" ? "0 1px 2px rgba(0,0,0,.5)" : undefined }}>
      {num ?? ""}
    </span>
  );
}

/** Player-card shirt in the team's kit pattern. */
export function Jersey({ colors, num, id }: { colors: TeamColors; num: number | string | null; id: string }) {
  const pid = `kit-${id.replace(/[^a-z0-9-]/gi, "")}`;
  const { primary: p, secondary: s, ink, pattern } = colors;
  const fill = pattern === "solid" ? p : `url(#${pid})`;
  return (
    <div className="jersey">
      <svg viewBox="0 0 100 110" aria-hidden="true">
        <defs>
          {pattern === "stripes" && (
            <pattern id={pid} width="16" height="10" patternUnits="userSpaceOnUse"><rect width="8" height="10" fill={p} /><rect x="8" width="8" height="10" fill={s} /></pattern>
          )}
          {pattern === "hoops" && (
            <pattern id={pid} width="10" height="16" patternUnits="userSpaceOnUse"><rect width="10" height="8" fill={p} /><rect y="8" width="10" height="8" fill={s} /></pattern>
          )}
          {pattern === "tricolor" && (
            <linearGradient id={pid} x1="0" x2="1" y1="0" y2="0">
              <stop offset="0" stopColor={p} /><stop offset="0.4" stopColor={p} /><stop offset="0.4" stopColor={s} />
              <stop offset="0.6" stopColor={s} /><stop offset="0.6" stopColor={ink} /><stop offset="1" stopColor={ink} />
            </linearGradient>
          )}
        </defs>
        <path d="M30 6 L14 14 L2 36 L18 44 L22 36 L22 104 L78 104 L78 36 L82 44 L98 36 L86 14 L70 6 Q50 20 30 6 Z" fill={fill} stroke="#0a1020" strokeWidth="2" />
        <path d="M30 6 Q50 20 70 6" fill="none" stroke={pattern === "tricolor" ? s : ink} strokeWidth="4" />
        <text x="50" y="76" textAnchor="middle" fontFamily="var(--display)" fontWeight="900" fontSize="40" fill={pattern === "tricolor" ? "#fff" : ink}
          stroke={pattern === "tricolor" ? "#0a1020" : "none"} strokeWidth="1">{num ?? ""}</text>
      </svg>
    </div>
  );
}
