"use client";

// "My view" drawer: perspective, favourites, language, metric, alerts, spoiler mode.

import { useEffect, useRef } from "react";
import { playerName, teamName } from "@/lib/matchday/match";
import type { Metric, Persona, ThemeMode } from "@/lib/matchday/perspective";
import type { MatchListItem, SideIdx } from "@/lib/matchday/types";
import { useMD } from "./context";
import { LangSeg, MatchPicker } from "./Header";
import { I } from "./Icons";
import { Kit } from "./Kit";
import { useLive } from "./live/LiveCtx";

const PERSONAS: Persona[] = ["fan", "casual", "coach", "analyst", "player"];
const METRICS: Metric[] = ["none", "xg", "speed", "distance", "passing"];
const THEMES: ThemeMode[] = ["dark", "light", "auto"];

export default function Drawer({ close, items, onMatch }: { close: () => void; items: MatchListItem[]; onMatch: (id: string) => void }) {
  const { U, view, setView, meta, lang, matchId } = useMD();
  const lv = useLive();
  const ins = lv.insights.settings;
  const setIns = lv.insights.setSettings;
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>("button")?.focus();
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", k);
    return () => { window.removeEventListener("keydown", k); prev?.focus?.(); };
  }, [close]);
  const teams: SideIdx[] = [0, 1];
  return (
    <>
      <div className="scrim" onClick={close} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={U.myView} ref={panel}>
        <div className="drawer-h">
          <div><div className="kicker">{U.myView}</div><h2 style={{ fontSize: 30 }}>{U.pick}</h2><div className="dim" style={{ fontSize: 13 }}>{U.pickSub}</div></div>
          <button className="iconbtn" aria-label={U.close} onClick={close}>✕</button>
        </div>
        <div className="drawer-b">
          <div className="field"><div className="lab">{U.myView}</div>
            <div className="opts">
              {PERSONAS.map((p) => (
                <button key={p} className={`opt ${view.persona === p ? "on" : ""}`} aria-pressed={view.persona === p} onClick={() => setView({ ...view, persona: p })}>
                  {p === "fan" ? <Kit meta={meta} side={view.fav} /> : <span className="av">{p === "player" ? I.player : I[p]}</span>}
                  <span>{U.personas[p]}<small className="mute" style={{ display: "block", fontWeight: 400 }}>{U.personaSub[p]}</small></span>
                </button>
              ))}
            </div>
          </div>
          <div className="field"><div className="lab">{U.favTeam}</div>
            <div className="opts">
              {teams.map((k) => (
                <button key={k} className={`opt ${view.fav === k ? "on" : ""}`} aria-pressed={view.fav === k} onClick={() => setView({ ...view, fav: k })}>
                  <Kit meta={meta} side={k} />{teamName(k ? meta.away : meta.home, lang)}
                </button>
              ))}
            </div>
          </div>
          {meta.players.length > 0 && (
            <div className="field"><label htmlFor="favp">{U.favPlayer}</label>
              <select id="favp" className="inp" value={view.favPlayer ?? ""} onChange={(e) => setView({ ...view, favPlayer: e.target.value || null })}>
                <option value="">{U.none}</option>
                {teams.map((k) => (
                  <optgroup key={k} label={teamName(k ? meta.away : meta.home, lang)}>
                    {meta.players.filter((p) => p.side === (k ? "away" : "home")).map((p) => (
                      <option key={p.player_id} value={p.player_id}>{p.number ?? "–"} · {playerName(p, lang)}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
          )}
          <div className="field"><div className="lab">{U.language}</div><LangSeg lang={lang} onLang={(l) => setView({ ...view, lang: l })} /></div>
          <div className="field"><div className="lab">{U.theme}</div>
            <div className="seg" role="radiogroup" aria-label={U.theme}>
              {THEMES.map((k) => <button key={k} className={view.theme === k ? "on" : ""} role="radio" aria-checked={view.theme === k} onClick={() => setView({ ...view, theme: k })}>{U.themes[k]}</button>)}
            </div>
          </div>
          <div className="field"><div className="lab">{U.match}</div><MatchPicker items={items} value={matchId} onChange={onMatch} lang={lang} wide /></div>
          <div className="field"><div className="lab">{U.metric}</div>
            <div className="seg" style={{ flexWrap: "wrap" }}>
              {METRICS.map((k) => <button key={k} className={view.metric === k ? "on" : ""} aria-pressed={view.metric === k} onClick={() => setView({ ...view, metric: k })}>{U.metrics[k]}</button>)}
            </div>
          </div>
          <div className="field"><div className="lab">{U.alerts}</div>
            <label className="switch">{U.alertGoal}<input type="checkbox" checked={view.alerts.goal} onChange={(e) => setView({ ...view, alerts: { ...view.alerts, goal: e.target.checked } })} /></label>
            <label className="switch">{U.alertWin}<input type="checkbox" checked={view.alerts.win} onChange={(e) => setView({ ...view, alerts: { ...view.alerts, win: e.target.checked } })} /></label>
            <label className="switch">{U.spoiler}<input type="checkbox" checked={view.spoiler} onChange={(e) => setView({ ...view, spoiler: e.target.checked })} /></label>
          </div>
          <div className="field"><div className="lab">{U.popups.title}</div>
            <label className="switch">{U.popups.autoPop}<input type="checkbox" checked={ins.autoPop} onChange={(e) => setIns({ ...ins, autoPop: e.target.checked })} /></label>
            <label className="switch">{U.popups.aiTakes}<input type="checkbox" checked={ins.aiTakes} onChange={(e) => setIns({ ...ins, aiTakes: e.target.checked })} /></label>
            <div className="lab" id="pop-th" style={{ marginTop: 4 }}>{U.popups.threshold}</div>
            <div className="seg" role="radiogroup" aria-labelledby="pop-th" style={{ flexWrap: "wrap" }}>
              {([1, 2, 3] as const).map((k) => (
                <button key={k} role="radio" aria-checked={ins.minPriority === k} className={ins.minPriority === k ? "on" : ""} disabled={!ins.autoPop}
                  onClick={() => setIns({ ...ins, minPriority: k })}>{U.popups.levels[k]}</button>
              ))}
            </div>
            <label className="switch">{U.liveCaptions}<input type="checkbox" checked={lv.captions} onChange={(e) => lv.setCaptions(e.target.checked)} /></label>
          </div>
          <button className="btn" onClick={close}>{U.save}</button>
        </div>
      </aside>
    </>
  );
}
