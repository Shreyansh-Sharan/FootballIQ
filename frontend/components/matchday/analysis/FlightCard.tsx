"use client";

// Ball flight for one shot: sideways scaled x3 to show the bend; hollow dots are estimated.
// Requested at the clock, capped 4 s after the shot, so it never reads past the replay.

import { anApi, useBucketed, type ShotRow } from "@/lib/matchday/analysis";
import { neutral } from "@/lib/matchday/neutral";
import { useMD } from "../context";
import { Kv, PanelState, fx, useA } from "./common";

export default function FlightCard({ shot, color }: { shot: ShotRow; color: string }) {
  const { matchId } = useMD();
  const A = useA();
  const t0 = shot.match_elapsed_ms;
  const r = useBucketed(`fl|${matchId}|${shot.event_id}`, (at) => anApi.flight(matchId, shot.event_id, at),
    { atOf: (t) => Math.max(t0, Math.min(t0 + 4000, Math.floor(t / 1000) * 1000)) });
  const f = r.data;
  const head = <div className="an-cap" style={{ color: "var(--accent-text)" }}>{A.flight}</div>;
  if (!f) return <div className="an-flight col" style={{ gap: 6 }}>{head}<PanelState status={r.status} empty={A.flightNA} /></div>;
  if (!f.available) return <div className="an-flight col" style={{ gap: 6 }}>{head}<p className="an-small">{neutral(f.reason) || A.flightNA}</p></div>;
  const pts = f.path ?? [];
  let svg: React.ReactNode = null;
  if (pts.length > 1) {
    const [, x0, y0] = pts[0], [, x1, y1] = pts[pts.length - 1];
    const ang = Math.atan2(y1 - y0, x1 - x0), L = Math.hypot(x1 - x0, y1 - y0) || 1;
    const P = pts.map(([, x, y, , o]) => {
      const dx = x - x0, dy = y - y0;
      return { u: (dx * Math.cos(ang) + dy * Math.sin(ang)) / L, v: (-dx * Math.sin(ang) + dy * Math.cos(ang)) / L, o };
    });
    const W = 300, H = 80, sx = (u: number) => 12 + u * (W - 24), sy = (v: number) => H / 2 + v * 3 * (W - 24);
    svg = (
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={A.pathCaption}>
        <line x1={sx(0)} y1={H / 2} x2={sx(1)} y2={H / 2} stroke="var(--line2)" strokeDasharray="3 3" />
        <polyline fill="none" stroke={color} strokeWidth={2} points={P.map((p) => `${sx(p.u)},${sy(p.v)}`).join(" ")} />
        {P.map((p, i) => <circle key={i} cx={sx(p.u)} cy={sy(p.v)} r={2} fill={p.o ? color : "var(--bg2)"} stroke={color} strokeWidth={0.8} />)}
        <text x={W - 8} y={12} textAnchor="end" style={{ font: "600 9px var(--mono)", fill: "var(--mute)" }}>{A.pathCaption}</text>
      </svg>
    );
  }
  const dir = (d: string | null | undefined) => A.dirs[d ?? ""] ?? d ?? "";
  return (
    <div className="an-flight col" style={{ gap: 8 }}>
      {head}
      {svg}
      <div className="an-kv">
        <Kv k={A.fl.curve} v={!f.curve_measurable ? A.fl.notMeasurable : f.bend === "straight" ? A.straightDeg(fx(f.curve_deg, 1)) : A.toThe(Math.abs(f.curve_deg ?? 0).toFixed(1), dir(f.bend))} />
        {f.curve_measurable && <Kv k={A.fl.swerve} v={fx(f.swerve_m, 2, " m")} />}
        <Kv k={A.fl.speed} v={f.speed_kmh != null ? `${f.estimated ? "~" : ""}${f.speed_kmh.toFixed(0)} km/h` : "—"} />
        <Kv k={A.fl.launch} v={fx(f.launch_deg, 0, "°")} />
        <Kv k={A.fl.peak} v={fx(f.peak_height_m, 1, " m")} />
        <Kv k={A.fl.line} v={fx(f.height_at_line_m, 1, " m")} />
        <Kv k={A.fl.flight} v={A.flightDist(fx(f.distance_m, 0), ((f.flight_ms ?? 0) / 1000).toFixed(2))} />
        <Kv k={A.fl.conf} v={A.confLine(A.confs[f.confidence ?? ""] ?? f.confidence ?? "—", f.samples ?? 0, fx(f.observed_pct, 0))} />
      </div>
      {!f.curve_measurable && f.curve_reason && <p className="an-small">{neutral(f.curve_reason)}</p>}
      {f.note && <div className="note warn small">{neutral(f.note)}</div>}
    </div>
  );
}
