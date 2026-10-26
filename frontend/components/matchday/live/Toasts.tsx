"use client";

// Insight pop-ups: at most three, 16 s each; hover or focus pauses them.

import { useEffect, useRef, useState } from "react";
import { askAI, handoff, openTab, watchAt } from "@/lib/matchday/handoff";
import type { AiTake, Insight } from "@/lib/matchday/analysis";
import { insightQuestion, sideOfTeam, TOAST_LIFE_MS } from "@/lib/matchday/live";
import { teamName, teamShort } from "@/lib/matchday/match";
import { neutral } from "@/lib/matchday/neutral";
import { teamVar, useMD } from "../context";
import { I } from "../Icons";
import { useLive } from "./LiveCtx";

const CAT_ICON: Record<string, string> = { event: "●", momentum: "↗", pressing: "⇉", model: "◆", tactical: "▦", physical: "⚡", player: "◉", discipline: "▮", set_piece: "⚑" };
const CAT_COLOR: Record<string, string> = {
  event: "var(--accent)", momentum: "#4fc3f7", pressing: "#ff8a65", model: "#b39ddb", tactical: "#81c784", physical: "#ffb74d", player: "#f06292", discipline: "#f5c518", set_piece: "#4dd0e1",
};

export default function Toasts() {
  const { U } = useMD();
  const lv = useLive();
  const { toasts, takes } = lv.insights;
  if (!toasts.length) return null;
  return (
    <section className="itoasts" aria-live="polite" aria-label={U.toast.region}>
      {toasts.map((x) => <Toast key={x.id} t={x} take={takes[x.id]} />)}
    </section>
  );
}

function Toast({ t, take }: { t: Insight; take: AiTake | undefined }) {
  const { U, meta, lang } = useMD();
  const lv = useLive();
  const [hold, setHold] = useState(false);
  const [left, setLeft] = useState(TOAST_LIFE_MS);
  const leftRef = useRef(left);
  leftRef.current = left;
  const { dismiss } = lv.insights;
  useEffect(() => {
    if (hold) return;
    const started = Date.now(), from = leftRef.current;
    const id = setInterval(() => {
      const rest = from - (Date.now() - started);
      setLeft(rest);
      if (rest <= 0) { clearInterval(id); dismiss(t.id); }
    }, 200);
    return () => clearInterval(id);
  }, [hold, dismiss, t.id]);
  const side = sideOfTeam(meta, t.team_id);
  const team = side == null ? "" : teamName(side ? meta.away : meta.home, lang);
  const cat = t.category in CAT_COLOR ? t.category : "event";
  const s = t.subject;
  const card = take?.data?.card;
  const coach = s?.type === "substitution" || s?.type === "player" || s?.type === "best_player";
  return (
    <div className={`itoast p${t.priority}`} style={{ "--cat": CAT_COLOR[cat] } as React.CSSProperties}
      onMouseEnter={() => setHold(true)} onMouseLeave={() => setHold(false)} onFocus={() => setHold(true)} onBlur={() => setHold(false)}>
      <div className="it-h">
        <span className="it-cat">{CAT_ICON[cat]} {U.cats[cat] ?? cat}</span>
        <span className="mono mute">{t.minute}</span>
        {side != null && <span className="chip team" style={{ background: teamVar(side) }}>{teamShort(side ? meta.away : meta.home, lang)}</span>}
        <span className="sp" />
        <button className="iconbtn sm" aria-label={U.toast.dismiss} onClick={() => dismiss(t.id)}>{I.close}</button>
      </div>
      <b className="it-t">{neutral(t.title)}</b>
      <p className="it-d">{neutral(t.detail)}</p>
      {s?.type === "substitution" && s.options[0] && (
        <div className="it-sub"><b className="off">▼ {s.options[0].off.name}</b>{s.options[0].on && <b className="on">▲ {s.options[0].on.name}</b>}</div>
      )}
      {s?.type === "best_player" && s.ranked[0] && (
        <div className="it-sub"><b className="on">★ {s.ranked[0].name}</b>{s.ranked[1] && <span className="dim">{U.toast.then(s.ranked[1].name)}</span>}</div>
      )}
      {take && (
        <div className="it-ai">
          <span className="tag">{U.toast.aiTake}</span>
          {take.state === "loading" && <span className="dim"><span className="spin" aria-hidden="true" /> {U.toast.checking}</span>}
          {take.state === "error" && <span className="dim">{U.toast.aiNA}</span>}
          {take.state === "done" && card && (
            <>
              <span><b className="risk">{U.toast.risk}:</b> {neutral(card.main_risk)}</span>
              <span><b className="do">{U.toast.do}:</b> {neutral(card.one_action)}</span>
            </>
          )}
          {take.state === "done" && !card && <span className="dim">{U.toast.aiNA}</span>}
        </div>
      )}
      <div className="it-a">
        <button onClick={() => { openTab("live"); watchAt(t.seek_ms ?? t.t_ms, t.seek_ms == null ? 6000 : 0); }}>{U.toast.watch}</button>
        {coach && s && (
          <button onClick={() => handoff({ type: "coach", section: s.type === "substitution" ? "subs" : s.type === "best_player" ? "best" : "form", teamSide: sideOfTeam(meta, s.team_id) ?? undefined, playerId: s.type === "player" ? s.player_id : undefined })}>{U.toast.coach}</button>
        )}
        <button onClick={() => askAI(insightQuestion(U, t, team || meta.home.name))}>{U.toast.ask}</button>
      </div>
      <div className="it-life" style={{ width: `${Math.max(0, (100 * left) / TOAST_LIFE_MS)}%` }} aria-hidden="true" />
    </div>
  );
}
