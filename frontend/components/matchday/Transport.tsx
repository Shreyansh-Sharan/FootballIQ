"use client";

// Transport bar: play/pause, ±10 s, timeline with pins and hover preview, Go live, speed.
// Seeking never passes the live edge.

import { useRef, useState } from "react";
import { CLOCK, SPEEDS } from "@/lib/matchday/clock";
import { minuteOf } from "@/lib/matchday/live";
import { clockLabel, periodAt } from "@/lib/matchday/match";
import type { MatchEvent } from "@/lib/matchday/types";
import { useMD } from "./context";
import { I } from "./Icons";

const NOMINAL: Record<number, number> = { 1: 45, 2: 45, 3: 15, 4: 15 };
const pad = (n: number) => String(n).padStart(2, "0");

export default function Transport() {
  const { U, clock, meta, events } = useMD();
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const dur = Math.max(1, clock.duration || meta.duration_ms);
  // regulation always shows; extra time and penalties appear once started
  const visible = meta.periods.filter((p) => p.period <= 2 || p.start_ms <= clock.edge);
  const lastP = visible[visible.length - 1];
  const span = Math.max(1, lastP ? Math.min(dur, lastP.start_ms + lastP.duration_ms) : dur);
  const pct = (tt: number) => `${((100 * Math.max(0, Math.min(span, tt))) / span).toFixed(2)}%`;
  const pins = events.data.filter((e) => e.match_elapsed_ms <= clock.edge && e.match_elapsed_ms <= span && !e.is_shootout && (e.is_goal || e.is_own_goal || !!e.card));
  const atLive = clock.edge - clock.t < 3000;
  const labels: { t: number; l: string }[] = visible.filter((p) => p.period < 5).map((p) => ({ t: p.start_ms, l: `${p.base_minute}′` }));
  const lastReg = visible.filter((p) => p.period < 5).slice(-1)[0];
  if (lastReg && lastReg === lastP) labels.push({ t: span, l: `${lastReg.base_minute + (NOMINAL[lastReg.period] ?? 45)}′` });
  const at = (clientX: number) => {
    const r = ref.current?.getBoundingClientRect();
    return r ? Math.max(0, Math.min(span, ((clientX - r.left) / r.width) * span)) : 0;
  };
  const onDown = (ev: React.PointerEvent) => {
    if (ev.button > 0) return;
    const move = (e: PointerEvent | React.PointerEvent) => CLOCK.seek(at(e.clientX));
    move(ev);
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Home") { e.preventDefault(); CLOCK.seek(0); }
    else if (e.key === "End") { e.preventDefault(); CLOCK.goLive(); }
  };
  const behind = Math.round((clock.edge - clock.t) / 1000);

  // hover preview: nearest goal / card / sub already played (no spoilers)
  let tip: { left: string; when: string; near: MatchEvent | null; future: boolean } | null = null;
  if (hover != null) {
    const p = periodAt(meta.periods, hover);
    const el = p ? Math.max(0, hover - p.start_ms) : hover;
    const base = p?.base_minute ?? 0;
    const when = p && p.period >= 5 ? U.periodTag[5] : `${p ? `${U.periodTag[p.period] ?? ""} ` : ""}${base + Math.floor(el / 60000)}:${pad(Math.floor((el % 60000) / 1000))}`;
    let near: MatchEvent | null = null, nd = span / 90;
    for (const e of events.data) {
      if (e.match_elapsed_ms > clock.edge || e.is_shootout || !(e.is_goal || e.is_own_goal || e.card || e.type === "Substitution")) continue;
      const d = Math.abs(e.match_elapsed_ms - hover);
      if (d < nd) { nd = d; near = e; }
    }
    tip = { left: pct(hover), when, near, future: hover > clock.edge };
  }
  return (
    <div className="transport">
      <div className="tr-l">
        <button className="tbtn" aria-label={clock.playing ? U.pause : U.play} onClick={() => CLOCK.toggle()} disabled={!clock.ready}>{clock.playing ? I.pause : I.play}</button>
        <button className="tbtn2 hide-s" aria-label={U.pipL.back} title={`${U.pipL.back} (J)`} onClick={() => CLOCK.seekBy(-10000)} disabled={!clock.ready}>{I.back10}</button>
        <button className="tbtn2 hide-s" aria-label={U.pipL.fwd} title={`${U.pipL.fwd} (L)`} onClick={() => CLOCK.seekBy(10000)} disabled={!clock.ready}>{I.fwd10}</button>
      </div>
      <div className="tl" ref={ref} onPointerDown={onDown} onKeyDown={onKey} role="slider" tabIndex={0} aria-label={U.timeline}
        onPointerMove={(e) => setHover(at(e.clientX))} onPointerLeave={() => setHover(null)}
        aria-valuemin={0} aria-valuemax={Math.round(span / 1000)} aria-valuenow={Math.round(clock.t / 1000)} aria-valuetext={clockLabel(meta.periods, clock.t)}>
        <div className="track" />
        {visible.map((p) => (
          <div key={p.period} className={`seg-p ${p.period >= 3 ? "et" : ""}`} style={{ left: pct(p.start_ms), width: `calc(${pct(p.duration_ms)} - 3px)` }}>
            {p.period >= 3 && <span className="seg-tag">{U.periodTag[p.period]}</span>}
          </div>
        ))}
        <div className="edge" style={{ width: pct(clock.edge) }} />
        <div className="fill" style={{ width: pct(clock.t) }} />
        {visible.filter((p) => p.start_ms > 0).map((p) => <div key={p.start_ms} className="ht" style={{ left: pct(p.start_ms) }} />)}
        {pins.map((e) => (
          <span key={e.event_id} className={`pin ${e.card && !e.is_goal && !e.is_own_goal ? `card ${/red|second/i.test(e.card) ? "red" : ""}` : ""}`}
            style={{ left: pct(e.match_elapsed_ms), background: e.is_goal || e.is_own_goal ? (e.team_id === meta.home.team_id ? "var(--home)" : "var(--away)") : undefined }} />
        ))}
        {hover != null && <div className="hov" style={{ width: pct(Math.min(hover, clock.edge)) }} />}
        <div className="head" style={{ left: pct(clock.t) }} />
        {labels.map((k) => <span key={k.t} className="lbl" style={{ left: pct(k.t) }}>{k.l}</span>)}
        {tip && (
          <div className="tl-tip" style={{ left: tip.left }} role="tooltip">
            <b className="mono">{tip.when}</b>
            {tip.future ? <span className="mute">{U.notPlayed}</span>
              : tip.near && <span>{minuteOf(tip.near.clock_label)} {tip.near.is_goal || tip.near.is_own_goal ? "⚽" : tip.near.card ? "▮" : "⇄"} {tip.near.type === "Substitution" ? tip.near.recipient_name ?? "" : tip.near.player_name ?? ""}</span>}
          </div>
        )}
      </div>
      <div className="tr-r">
        <button className={`golive ${atLive ? "at" : ""}`} onClick={() => CLOCK.goLive()}>
          <span className="live-dot" style={{ animation: atLive && clock.playing ? undefined : "none", background: atLive ? "#ff3b3b" : "var(--mute)" }} />
          {atLive ? U.live : `${U.goLive} · −${behind}${U.seconds}`}
        </button>
        <div className="speeds" role="radiogroup" aria-label={U.speed}>
          {SPEEDS.map((s) => (
            <button key={s} className={clock.speed === s ? "on" : ""} role="radio" aria-checked={clock.speed === s} onClick={() => CLOCK.setSpeed(s)}>{s}×</button>
          ))}
        </div>
      </div>
    </div>
  );
}
