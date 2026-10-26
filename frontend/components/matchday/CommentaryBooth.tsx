"use client";

// Commentary booth: current line, captions up to the clock and voice controls.
// Voice starts off (browser autoplay policy); captions always show.

import { useEffect, useRef } from "react";
import { CLOCK } from "@/lib/matchday/clock";
import { useMD } from "./context";
import { I } from "./Icons";
import { StateNote } from "./StateNote";

export default function CommentaryBooth() {
  const { U, commentary, clock, lang } = useMD();
  const { state, lines, status } = commentary;
  const t = clock.t;
  const shown = lines.filter((l) => l.t_ms <= t);
  const recent = shown.slice(-40);
  const latest = shown[shown.length - 1];
  const bubble = state.speaking && state.speaking.t_ms <= t ? state.speaking : latest && t - latest.t_ms < 12000 ? latest : null;
  const list = useRef<HTMLOListElement>(null);
  const pinned = useRef(true);
  useEffect(() => {
    const el = list.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [recent.length, recent[recent.length - 1]?.id]);
  const voiceLabel = !state.enabled ? (state.blocked ? U.voiceBlocked : U.voiceOff)
    : state.mode === "studio" ? U.voiceStudio : state.mode === "browser" ? U.voiceBrowser : !state.speechAvailable && commentary.tts === "none" ? U.voiceNone : U.voice;
  return (
    <div className="card booth">
      <div className="card-h">
        <h3>{U.commentary}</h3>
        <span className="tag">{voiceLabel}</span>
      </div>
      <div className="card-b">
        {!state.enabled ? (
          <button className="btn booth-on" onClick={() => commentary.setEnabled(true)}>
            {I.volOn}<span>{U.turnOn}</span>
          </button>
        ) : (
          <div className="booth-ctl">
            <button className="iconbtn" aria-pressed={state.enabled} aria-label={U.mute} title={U.mute} onClick={() => commentary.setEnabled(false)}>{I.volOn}</button>
            <label className="vol">
              <span className="sr">{U.volume}</span>
              <input type="range" min={0} max={1} step={0.05} value={state.volume} aria-label={U.volume}
                onChange={(e) => commentary.setVolume(parseFloat(e.target.value))} />
            </label>
            <span className="mono mute" style={{ fontSize: 11 }}>{Math.round(state.volume * 100)}%</span>
          </div>
        )}
        {status !== "ready" && !shown.length ? (
          <StateNote status={status} small />
        ) : (
          <>
            <div className={`bubble ${bubble?.speaker === "colour" ? "colour" : "pbp"} ${bubble && state.speaking?.id === bubble.id ? "speaking" : ""}`} aria-live="polite" lang={lang}>
              {bubble ? (
                <>
                  <div className="who">
                    <span className="spk">{bubble.speaker === "colour" ? U.speakers.colour : U.speakers.pbp}</span>
                    <span className="mono">{bubble.clock}</span>
                    {state.speaking?.id === bubble.id && <span className="eq" aria-hidden="true"><i /><i /><i /></span>}
                  </div>
                  <p className={bubble.excitement >= 3 ? "loud" : ""}>{bubble.text}</p>
                </>
              ) : (
                <p className="dim">{U.noLines}</p>
              )}
            </div>
            <div className="tag">{U.captions}</div>
            <ol className="captions" ref={list} role="log" aria-label={U.captions} lang={lang}
              onScroll={(e) => { const el = e.currentTarget; pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24; }}>
              {recent.map((l) => (
                <li key={l.id} className={`${l.speaker} p${l.priority}`}>
                  <button className="cap-t mono" onClick={() => CLOCK.seek(l.t_ms - 3000)} title={U.watch}>{l.clock}</button>
                  <span><b>{l.speaker === "colour" ? U.speakers.colour : U.speakers.pbp}</b> {l.text}</span>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}
