"use client";

// Controls under the live pitch: shape team, presets, overlays, legend, cameras and view buttons.

import { useState } from "react";
import { activePreset, CAMS, OVERLAY_KEYS, presetOverlays, PRESETS, TRACKING_OVERLAYS, type Overlays } from "@/lib/matchday/live";
import { teamShort } from "@/lib/matchday/match";
import { useMD } from "../context";
import { I } from "../Icons";
import { useLive } from "./LiveCtx";

const OV_ICON: Record<keyof Overlays, string> = {
  hull: "▱", lines: "≡", shape: "☰", passing: "△", press: "⇉", runs: "〰", heat: "▩", shots: "◎", dims: "↔", ref: "⬚", names: "Aa", speed: "⚡", trail: "◌",
};

export default function Toolbar() {
  const { U, meta, lang, hasTracking } = useMD();
  const lv = useLive();
  const [legend, setLegend] = useState(false);
  const preset = activePreset(lv.ov);
  const keys = hasTracking ? OVERLAY_KEYS : OVERLAY_KEYS.filter((k) => !TRACKING_OVERLAYS.includes(k));
  const on = keys.filter((k) => lv.ov[k]);
  return (
    <div className="ptools">
      <div className="ptools-row">
        {hasTracking && (
          <div className="seg" role="radiogroup" aria-label={U.team}>
            {([[teamShort(meta.home, lang), 0], [teamShort(meta.away, lang), 1], [U.both, 2]] as [string, 0 | 1 | 2][]).map(([l, v]) => (
              <button key={v} className={lv.team === v ? "on" : ""} role="radio" aria-checked={lv.team === v} onClick={() => lv.setTeam(v)}>{l}</button>
            ))}
          </div>
        )}
        {hasTracking && (
          <div className="seg presets" role="radiogroup" aria-label={U.view}>
            {PRESETS.map(([k]) => (
              <button key={k} role="radio" aria-checked={preset === k} className={preset === k ? "on" : ""} title={U.presetTip[k]}
                onClick={() => lv.setOv(presetOverlays(k))}>{U.presets[k]}</button>
            ))}
          </div>
        )}
        <span className="sp" />
        <div className="viewbtns" role="group" aria-label={U.view}>
          <button className={`iconbtn ${lv.captions ? "on" : ""}`} aria-pressed={lv.captions} aria-label={U.liveCaptions} title={U.liveCaptions} onClick={() => lv.setCaptions(!lv.captions)}>{I.cc}</button>
          <button className={`iconbtn ${lv.pipOn ? "on" : ""}`} aria-pressed={lv.pipOn} aria-label={U.pip} disabled={!lv.pipOk || !hasTracking}
            title={!lv.pipOk ? U.pipUnsupported : !hasTracking ? U.camNeedsTracking : U.pip} onClick={lv.togglePip}>{I.pip}</button>
          <button className={`iconbtn ${lv.theatre ? "on" : ""}`} aria-pressed={lv.theatre} aria-label={U.theatre} title={U.theatre} onClick={() => lv.setTheatre(!lv.theatre)}>{I.theatre}</button>
          <button className="iconbtn" aria-label={lv.fullscreen ? U.exitFullscreen : U.fullscreen} title={lv.fullscreen ? U.exitFullscreen : U.fullscreen} onClick={lv.toggleFullscreen}>{lv.fullscreen ? I.exitFull : I.full}</button>
        </div>
      </div>
      <div className="ptools-row">
        <div className="seg cams" role="radiogroup" aria-label={U.camera}>
          {CAMS.map((c) => (
            <button key={c} role="radio" aria-checked={lv.cam === c} className={lv.cam === c ? "on" : ""} disabled={!hasTracking && c !== "top"}
              title={!hasTracking && c !== "top" ? U.camNeedsTracking : c === "free" ? U.dragOrbit : U.cams[c]} onClick={() => lv.setCam(c)}>{U.cams[c]}</button>
          ))}
        </div>
      </div>
      <div className="ptools-row ovbar" role="toolbar" aria-label={U.legend}>
        {keys.map((k) => (
          <button key={k} className={`ovbtn ${lv.ov[k] ? "on" : ""}`} aria-pressed={lv.ov[k]} title={U.ovTip[k]} onClick={() => lv.toggleOv(k)}>
            <span aria-hidden="true" className="ovi">{OV_ICON[k]}</span>{U.overlays[k]}
          </button>
        ))}
        <button className={`ovbtn ${legend ? "on" : ""}`} aria-expanded={legend} aria-controls="pitch-legend" onClick={() => setLegend(!legend)}>? {U.legend}</button>
      </div>
      {!hasTracking && <div className="note small" role="status">{U.noTrackOv}</div>}
      {legend && (
        <div className="ov-legend" id="pitch-legend">
          <span><i style={{ background: "var(--home)" }} />{meta.home.name}</span>
          <span><i style={{ background: "var(--away)" }} />{meta.away.name}</span>
          <span><i style={{ background: "#fff" }} />{U.legendItems.ball}</span>
          <span><i className="faded" />{U.legendItems.faded}</span>
          <span><i className="ring" />{U.legendItems.ring}</span>
          <span><i className="ring gold" />{U.legendItems.carrier}</span>
          <span><i className="ring gold dash" />{U.legendItems.focus}</span>
          {on.map((k) => <span key={k} className="full"><b>{OV_ICON[k]} {U.overlays[k]}:</b> {U.ovTip[k]}</span>)}
        </div>
      )}
    </div>
  );
}
