"use client";

// Ctrl/⌘+K palette: a minute ("67", "67:30") seeks; otherwise search screens, actions, moments and matches.

import { useEffect, useMemo, useRef, useState } from "react";
import type { TabKey } from "../Header";
import { TABS } from "../Header";
import { nextTheme } from "../Header";
import { CLOCK } from "@/lib/matchday/clock";
import { LANGS } from "@/lib/matchday/i18n";
import { keyMoments } from "@/lib/matchday/live";
import { msOfMinute } from "@/lib/matchday/match";
import type { MatchListItem } from "@/lib/matchday/types";
import { useMD } from "../context";
import { I } from "../Icons";
import { useLive } from "./LiveCtx";

interface Item { id: string; group: string; label: string; hint?: string; run: () => void }

export default function Palette({ items: matches, onMatch, setTab }: { items: MatchListItem[]; onMatch: (id: string) => void; setTab: (t: TabKey) => void }) {
  const md = useMD();
  const { U, meta, view, setView, clock, events, commentary } = md;
  const lv = useLive();
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const close = () => lv.setPalette(false);

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    input.current?.focus();
    return () => { prev?.focus?.(); };
  }, []);

  const all = useMemo<Item[]>(() => {
    const out: Item[] = [];
    const ql = q.trim().toLowerCase();
    const m = /^(\d{1,3})(?:[:'.](\d{1,2}))?$/.exec(ql);
    if (m) {
      const min = parseInt(m[1], 10), sec = Math.min(59, m[2] ? parseInt(m[2], 10) : 0);
      const target = msOfMinute(meta.periods, min) + sec * 1000;
      const mmss = `${min}:${String(sec).padStart(2, "0")}`;
      out.push({ id: "seek", group: U.pal.jump, label: U.pal.goTo(mmss), hint: target > clock.edge ? U.pal.notPlayed : U.pal.clockHint, run: () => CLOCK.seek(target) });
    }
    for (const k of TABS) out.push({ id: `s-${k}`, group: U.pal.screens, label: U.tabs[k], run: () => setTab(k) });
    const act = (id: string, label: string, hint: string, run: () => void) => out.push({ id: `a-${id}`, group: U.pal.player, label, hint, run });
    act("play", clock.playing ? U.pal.pause : U.pal.play, "Space / K", () => CLOCK.toggle());
    if (lv.pipOk && md.hasTracking) act("pip", U.pal.pip, "I", () => lv.togglePip());
    act("theatre", lv.theatre ? U.pal.theatreOff : U.pal.theatreOn, "T", () => { lv.setTheatre(!lv.theatre); setTab("live"); });
    act("captions", lv.captions ? U.pal.captionsOff : U.pal.captionsOn, "C", () => lv.setCaptions(!lv.captions));
    const nt = nextTheme(view.theme);
    act("theme", U.pal.theme(U.themes[nt]), "", () => setView({ ...view, theme: nt }));
    act("help", U.pal.shortcuts, "?", () => lv.setHelp(true));
    act("comm", commentary.state.enabled ? U.pal.commOff : U.pal.commOn, "", () => commentary.setEnabled(!commentary.state.enabled));
    for (const [k, , name] of LANGS) if (k !== view.lang) act(`lang-${k}`, U.pal.lang(name), k.toUpperCase(), () => setView({ ...view, lang: k }));
    for (const e of keyMoments(events.data, clock.t, U)) out.push({ id: `e-${e.id}`, group: U.pal.moments, label: e.label, run: () => { CLOCK.seek(Math.max(0, e.t_ms - 8000)); setTab("live"); } });
    for (const mm of matches) {
      out.push({ id: `m-${mm.match_id}`, group: U.pal.matches, label: `${mm.home.name} ${U.vs} ${mm.away.name}`,
        hint: `${mm.competition}${mm.stage ? ` · ${mm.stage}` : ""} · ${mm.date}`, run: () => { onMatch(mm.match_id); setTab("live"); } });
    }
    if (!ql || m) return out.slice(0, 60);
    return out.filter((x) => `${x.label} ${x.hint ?? ""} ${x.group}`.toLowerCase().includes(ql)).slice(0, 60);
  }, [q, meta.periods, clock.edge, clock.playing, clock.t, U, lv, md.hasTracking, view, setView, commentary, events.data, matches, onMatch, setTab]);

  const cur = Math.min(i, Math.max(0, all.length - 1));
  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-k="${cur}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cur]);
  const run = (it?: Item) => { if (!it) return; close(); it.run(); };
  let lastGroup = "";
  return (
    <div className="pal-bg" onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}>
      <div className="pal" role="dialog" aria-modal="true" aria-label={U.pal.title}>
        <div className="pal-in">
          {I.search}
          <input ref={input} value={q} placeholder={U.pal.placeholder} aria-label={U.pal.title} role="combobox" aria-expanded="true"
            aria-controls="pal-list" aria-activedescendant={all[cur] ? `pal-${cur}` : undefined} autoComplete="off" spellCheck={false}
            onChange={(e) => { setQ(e.target.value); setI(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setI(Math.min(all.length - 1, cur + 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setI(Math.max(0, cur - 1)); }
              else if (e.key === "Enter") { e.preventDefault(); run(all[cur]); }
              else if (e.key === "Escape") { e.preventDefault(); close(); }
              else if (e.key === "Tab") e.preventDefault();
            }} />
          <kbd>Esc</kbd>
        </div>
        <div className="pal-list" id="pal-list" role="listbox" ref={list} aria-label={U.pal.title}>
          {all.length === 0 && <div className="pal-empty">{U.pal.nothing(q)}</div>}
          {all.map((it, k) => {
            const head = it.group !== lastGroup ? (lastGroup = it.group) : null;
            return (
              <div key={it.id} role="presentation">
                {head && <div className="pal-group" role="presentation">{head}</div>}
                <div id={`pal-${k}`} data-k={k} role="option" aria-selected={k === cur} className={`pal-item ${k === cur ? "on" : ""}`}
                  onMouseMove={() => { if (k !== cur) setI(k); }} onMouseDown={(e) => e.preventDefault()} onClick={() => run(it)}>
                  <span>{it.label}</span>{it.hint && <span className="mute">{it.hint}</span>}
                </div>
              </div>
            );
          })}
        </div>
        <div className="pal-foot mono">{U.pal.foot}</div>
      </div>
    </div>
  );
}
