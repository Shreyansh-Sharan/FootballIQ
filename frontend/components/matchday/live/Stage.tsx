"use client";

// The persistent live pitch. The Shell renders it once via a portal that moves between the Live tab slot, the
// miniplayer dock and an off-screen park, so the canvas and picture-in-picture survive tab switches.

import { useEffect, useRef, useState } from "react";
import { CLOCK } from "@/lib/matchday/clock";
import { askAI, focusPlayer, handoff, openTab } from "@/lib/matchday/handoff";
import { captionAt, MINI_W, type MiniSize } from "@/lib/matchday/live";
import { clockMMSS, playerShort, teamName, teamShort } from "@/lib/matchday/match";
import { OBSERVED_MAX_AGE_MS } from "@/lib/matchday/shape";
import type { SideIdx } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";
import { I } from "../Icons";
import Pitch, { hitPos } from "../Pitch";
import { useLive } from "./LiveCtx";

export type StageVariant = "full" | "mini" | "parked";

interface Insp {
  idx: number; x: number; y: number; name: string; number: string; side: SideIdx; team: string; role: string; pos: string;
  px: number | null; py: number | null; observed: boolean; speed: number | null; playerId: string | null;
}

export default function Stage({ variant }: { variant: StageVariant }) {
  const md = useMD();
  const lv = useLive();
  const { U, meta, lang, clock, score, view } = md;
  const full = variant === "full" || lv.fullscreen;
  const mini = !full;
  const box = useRef<HTMLDivElement>(null);
  const cam = full ? lv.cam : "top";
  const shapeTeams: SideIdx[] = lv.team === 2 ? [0, 1] : [lv.team];
  const cap = full && lv.captions ? captionAt(md.events.data, clock.t, meta, U) : null;
  const lower = full ? lv.lower : null;
  const mmss = clockMMSS(meta.periods, clock.t);
  const atEnd = clock.t >= clock.duration - 1;

  // ---- selected-player inspector, refreshed at 8 Hz
  const [insp, setInsp] = useState<Insp | null>(null);
  const sel = full ? lv.sel : null;
  useEffect(() => {
    if (sel == null || !md.hasTracking) { setInsp(null); return; }
    const tick = () => {
      const b = md.tracking.buffer;
      const newest = b.newestT;
      const who = md.idxInfo.get(sel);
      const pos = hitPos(lv.hitsRef.current, sel);
      if (newest == null || !who) { setInsp(null); return; }
      const rt = Math.min(CLOCK.view, newest);
      const fr = b.frameAt(rt);
      const p = fr?.players.find((q) => q.idx === sel);
      let speed: number | null = null;
      if (p) {
        const prev = b.lastObserved(rt - 1000, OBSERVED_MAX_AGE_MS).get(sel);
        if (p.observed && prev && rt - prev.t > 500) speed = Math.hypot(p.x - prev.x, p.y - prev.y) / ((rt - prev.t) / 1000);
        else speed = Math.hypot(p.vx, p.vy);
        if (!Number.isFinite(speed) || speed > 12) speed = null;
      }
      setInsp({
        idx: sel, x: pos?.x ?? -1, y: pos?.y ?? -1,
        name: who.player ? playerShort(who.player, lang) : who.rosterName ?? `#${who.number}`, number: who.number, side: who.side,
        team: teamName(who.side ? meta.away : meta.home, lang), role: U.insp.roles[who.role], pos: who.player?.position ?? who.role,
        px: p ? p.x : null, py: p ? p.y : null, observed: !!p?.observed, speed, playerId: who.player?.player_id ?? null,
      });
    };
    tick();
    const id = setInterval(tick, 125);
    return () => clearInterval(id);
  }, [sel, md.hasTracking, md.tracking.buffer, md.idxInfo, lang, meta, U, lv.hitsRef]);

  const bw = box.current?.clientWidth ?? 800, bh = box.current?.clientHeight ?? 500;
  const showBug = mini || lv.fullscreen;
  const L3 = lower ? (
    <div className="lower3 in-stage" key={lower.id} style={{ "--l3c": teamVar(lower.side) } as React.CSSProperties}>
      <div className="min">{lower.clock}</div>
      <div className="txt">
        <b>{lower.h}</b><span>{lower.b}</span>
        <span className="l3-act">
          <button className="link" onClick={() => askAI(U.q.moment(lower.clock, lower.h))}>{U.askAI}</button>
          {(lower.kind === "sub" || lower.kind === "card") && (
            <button className="link" onClick={() => handoff({ type: "coach", section: lower.kind === "sub" ? "subs" : "form", teamSide: lower.side ?? undefined, playerId: lower.player ?? undefined })}>{U.coachLink}</button>
          )}
        </span>
      </div>
    </div>
  ) : null;

  return (
    <div ref={box} className={`stage ${full ? "full" : "mini"} ${variant === "parked" ? "parked" : ""}`}
      onClick={mini && variant === "mini" ? () => openTab("live") : undefined}>
      <Pitch overlays={lv.ov} shapeTeams={shapeTeams} focus={view.favPlayer} cam={md.hasTracking ? cam : "top"} fill compact={mini}
        selected={sel} onSelect={full ? lv.setSel : undefined} onCam={full ? lv.setCam : undefined}
        zoomRef={lv.zoomRef} canvasRef={lv.canvasRef} hitsRef={lv.hitsRef} hideTag={mini} paused={variant === "parked" && !lv.pipOn && !lv.fullscreen} />

      {showBug && (
        <div className="sbug" aria-hidden={mini ? undefined : true}>
          <span className="t" style={{ borderLeftColor: "var(--home)" }}>{teamShort(meta.home, lang)}</span>
          <span className="s">{score[0]}–{score[1]}</span>
          <span className="t" style={{ borderRightColor: "var(--away)" }}>{teamShort(meta.away, lang)}</span>
          <span className="c">{clock.playing && <i className="live-dot" />}{mmss}</span>
        </div>
      )}

      {full && !clock.playing && clock.ready && !atEnd && (
        <button className="bigplay" aria-label={U.play} onClick={(e) => { e.stopPropagation(); CLOCK.setPlaying(true); }}>
          <span className="ring" aria-hidden="true" />{I.bigplay}
        </button>
      )}

      {full && (cap || L3) && (
        <div className="stage-bottom">
          {cap && (
            <div className={`caption ${cap.big ? "big" : ""}`} key={cap.id} role="status" style={{ "--l3c": teamVar(cap.side) } as React.CSSProperties}>
              <span className="cm">{cap.min}</span><b>{cap.what}</b><span className="cw">{cap.who}</span>
            </div>
          )}
          {L3}
        </div>
      )}

      {full && insp && insp.x >= 0 && (
        <div className="insp" role="dialog" aria-label={insp.name}
          style={{ left: insp.x + 18 + 270 <= bw ? insp.x + 18 : Math.max(8, insp.x - 18 - 262), top: Math.max(8, Math.min(insp.y - 90, bh - 196)) }}>
          <div className="insp-h">
            <span className="insp-no" style={{ background: teamVar(insp.side) }}>{insp.number}</span>
            <div className="insp-n"><b>{insp.name}</b><small>{insp.team} · {insp.pos}</small></div>
            <button className="iconbtn sm" aria-label={U.insp.close} onClick={() => lv.setSel(null)}>{I.close}</button>
          </div>
          <div className="insp-r"><span>{U.insp.position}</span><b className="mono">{insp.px != null ? `${insp.px.toFixed(1)}, ${insp.py!.toFixed(1)} m` : "—"}</b><em className={insp.observed ? "ok" : "est"}>{insp.observed ? U.insp.observed : U.insp.estimated}</em></div>
          <div className="insp-r"><span>{U.insp.speed}</span><b className="mono">{insp.speed != null ? `${insp.speed.toFixed(1)} m/s` : "—"}</b><em>{U.insp.derived}</em></div>
          <div className="insp-r"><span>{U.insp.line}</span><b>{insp.role}</b><em>{U.insp.roster}</em></div>
          {insp.playerId && (
            <div className="insp-a">
              <button className="btn sm" onClick={() => focusPlayer(insp.playerId!, "player")}>{U.insp.focus}</button>
              <button className="btn sm ghost" onClick={() => handoff({ type: "coach", section: "form", teamSide: insp.side, playerId: insp.playerId! })}>{U.insp.coach}</button>
            </div>
          )}
        </div>
      )}

      {full && cam === "free" && md.hasTracking && (
        <div className="zoom" role="group" aria-label={U.camera}>
          <button aria-label={U.zoomIn} onClick={() => lv.zoomRef.current?.(-12)}>+</button>
          <button aria-label={U.zoomOut} onClick={() => lv.zoomRef.current?.(12)}>−</button>
        </div>
      )}
      {full && cam !== "top" && md.hasTracking && <div className="orbit-hint" aria-hidden="true">{U.dragOrbit}</div>}

      {lv.fullscreen && (
        <div className="fs-ctl" onClick={(e) => e.stopPropagation()}>
          <button className="iconbtn" aria-label={clock.playing ? U.pause : U.play} onClick={() => CLOCK.toggle()}>{clock.playing ? I.pause : I.play}</button>
          <button className="iconbtn" aria-label={U.pipL.back} onClick={() => CLOCK.seekBy(-10000)}>{I.back10}</button>
          <button className="iconbtn" aria-label={U.pipL.fwd} onClick={() => CLOCK.seekBy(10000)}>{I.fwd10}</button>
          <button className="iconbtn" aria-label={U.exitFullscreen} onClick={lv.toggleFullscreen}>{I.exitFull}</button>
        </div>
      )}

      {variant === "mini" && !lv.fullscreen && (
        <div className="mini-ctl" onClick={(e) => e.stopPropagation()}>
          <button className="iconbtn sm" aria-label={clock.playing ? U.pause : U.play} onClick={() => CLOCK.toggle()}>{clock.playing ? I.pause : I.play}</button>
          <span className="sp" />
          {lv.pipOk && md.hasTracking && <button className={`iconbtn sm ${lv.pipOn ? "on" : ""}`} aria-label={U.pip} aria-pressed={lv.pipOn} onClick={lv.togglePip}>{I.pip}</button>}
          <button className="iconbtn sm" aria-label={U.mini.expand} title={U.mini.expand} onClick={() => openTab("live")}>{I.expand}</button>
          <button className="iconbtn sm" aria-label={U.mini.close} title={U.mini.close} onClick={() => lv.setMiniClosed(true)}>{I.close}</button>
        </div>
      )}
      {variant === "mini" && !lv.fullscreen && (
        <div className="mini-size" role="radiogroup" aria-label={U.mini.size} onClick={(e) => e.stopPropagation()}>
          {(Object.keys(MINI_W) as MiniSize[]).map((k) => (
            <button key={k} role="radio" aria-checked={lv.mini === k} className={lv.mini === k ? "on" : ""} onClick={() => lv.setMini(k)}>{k.toUpperCase()}</button>
          ))}
        </div>
      )}
    </div>
  );
}
