"use client";

import { useEffect, useRef } from "react";
import { clockMMSS, teamName, teamShort } from "@/lib/matchday/match";
import { LANGS, UI } from "@/lib/matchday/i18n";
import type { ThemeMode } from "@/lib/matchday/perspective";
import type { Lang, MatchListItem } from "@/lib/matchday/types";
import { useMD } from "./context";
import { I } from "./Icons";
import { useLive } from "./live/LiveCtx";
import { PersonaIcon } from "./PersonaStrip";
import Transport from "./Transport";

export type TabKey =
  | "live" | "stories" | "recaps" | "broadcast"
  | "prematch" | "tactical" | "shape" | "flow" | "shots" | "models"
  | "player" | "coach"
  | "ai";
export type TabGroup = "watch" | "analyse" | "people" | "ai";
export const TAB_GROUPS: [TabGroup, TabKey[]][] = [
  ["watch", ["live", "stories", "recaps", "broadcast"]],
  ["analyse", ["prematch", "tactical", "shape", "flow", "shots", "models"]],
  ["people", ["player", "coach"]],
  ["ai", ["ai"]],
];
export const TABS: TabKey[] = TAB_GROUPS.flatMap(([, ks]) => ks);

export function Logo() {
  return <a className="logo" href="/welcome" aria-label="FootballIQ"><span className="mark" aria-hidden="true" /><span>Football<b>IQ</b></span></a>;
}

export function MatchPicker({ items, value, onChange, lang, wide }: { items: MatchListItem[]; value: string | null; onChange: (id: string) => void; lang: Lang; wide?: boolean }) {
  const groups = new Map<string, MatchListItem[]>();
  for (const m of items) {
    const k = m.competition || "—";
    groups.set(k, [...(groups.get(k) ?? []), m]);
  }
  if (!items.length) return null;
  return (
    <select className={`mpick ${wide ? "wide" : ""}`} aria-label={UI[lang].match} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      {[...groups.entries()].map(([comp, ms]) => (
        <optgroup key={comp} label={comp}>
          {ms.map((m) => (
            <option key={m.match_id} value={m.match_id}>{m.date} · {m.home.name} v {m.away.name}{m.stage ? ` · ${m.stage}` : ""}</option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

export function LangSeg({ lang, onLang }: { lang: Lang; onLang: (l: Lang) => void }) {
  return (
    <div className="seg" role="radiogroup" aria-label={UI[lang].language}>
      {LANGS.map(([k, l]) => (
        <button key={k} className={lang === k ? "on" : ""} role="radio" aria-checked={lang === k} onClick={() => onLang(k)}>{l}</button>
      ))}
    </div>
  );
}

export const nextTheme = (t: ThemeMode): ThemeMode => (t === "dark" ? "light" : t === "light" ? "auto" : "dark");

export default function Header({ items, onMatch, tab, setTab, openDrawer, personaText }: {
  items: MatchListItem[]; onMatch: (id: string) => void; tab: TabKey; setTab: (t: TabKey) => void; openDrawer: () => void; personaText: string;
}) {
  const md = useMD();
  const lv = useLive();
  const { U, meta, lang, view, setView, score, clock, commentary, state } = md;
  const nav = useRef<HTMLElement>(null);
  useEffect(() => { nav.current?.querySelector<HTMLElement>(".tab.on")?.scrollIntoView({ block: "nearest", inline: "nearest" }); }, [tab]);
  const shoot = state.data?.shootout;
  const so = shoot ? [shoot[meta.home.team_id] ?? 0, shoot[meta.away.team_id] ?? 0] : null;
  const mmss = clockMMSS(meta.periods, clock.t);
  const voiceOn = commentary.state.enabled;
  return (
    <header className="top">
      <div className="top-in">
        <Logo />
        <div className="bug" aria-label={`${teamName(meta.home, lang)} ${score[0]}, ${teamName(meta.away, lang)} ${score[1]}, ${mmss}`}>
          <div className="tm"><i style={{ background: "var(--home)" }} />{teamShort(meta.home, lang)}</div>
          <div className="sc">{score[0]}–{score[1]}{so && <small>({so[0]}–{so[1]})</small>}</div>
          <div className="tm">{teamShort(meta.away, lang)}<i style={{ background: "var(--away)" }} /></div>
          <div className="clk">{clock.playing && <span className="live-dot" />}{mmss}</div>
        </div>
        <div className="top-r">
          <button className="searchbtn" onClick={() => lv.setPalette(true)} aria-label={U.searchAria} aria-haspopup="dialog" title={U.searchAria}>
            {I.search}<span className="lbl">{U.search}</span><kbd>⌘K</kbd>
          </button>
          <MatchPicker items={items} value={md.matchId} onChange={onMatch} lang={lang} />
          <LangSeg lang={lang} onLang={(l) => setView({ ...view, lang: l })} />
          <button className={`iconbtn ${voiceOn ? "on" : ""}`} aria-pressed={voiceOn} aria-label={voiceOn ? U.mute : U.unmute} title={voiceOn ? U.mute : U.unmute}
            onClick={() => commentary.setEnabled(!voiceOn)}>{voiceOn ? I.volOn : I.volOff}</button>
          <button className="iconbtn hide-s" aria-label={`${U.theme}: ${U.themes[view.theme]}`} title={`${U.theme}: ${U.themes[view.theme]}`} onClick={() => setView({ ...view, theme: nextTheme(view.theme) })}>
            {view.theme === "light" ? I.sun : view.theme === "dark" ? I.moon : I.auto}
          </button>
          <button className="viewbtn" onClick={openDrawer} aria-haspopup="dialog"><PersonaIcon view={view} /><span className="lbl">{personaText}</span></button>
        </div>
      </div>
      <nav className="tabs" aria-label="Sections" ref={nav}>
        {TAB_GROUPS.map(([g, ks], gi) => (
          <div className={`tabgroup g-${g}`} role="group" aria-labelledby={`tg-${g}`} key={g}>
            {gi > 0 && <span className="tabsep" aria-hidden="true" />}
            <div className="tabgroup-in">
              <span className="tabgroup-l" id={`tg-${g}`}>{U.tabGroups[g]}</span>
              <div className="tabgroup-tabs">
                {ks.map((k) => (
                  <button key={k} className={`tab ${tab === k ? "on" : ""}`} aria-current={tab === k ? "page" : undefined} onClick={() => setTab(k)}>{I[k]}<span>{U.tabs[k]}</span></button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </nav>
      <Transport />
    </header>
  );
}
