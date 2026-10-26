"use client";

// Insight feed up to the clock (10 s buckets), newest first. AI takes are queued one at a time and cached.

import { useState } from "react";
import { useAiTake, useInsights, type Insight } from "@/lib/matchday/analysis";
import { askAI, handoff, openTab, watchAt } from "@/lib/matchday/handoff";
import { clockLabel, teamShort } from "@/lib/matchday/match";
import { neutral } from "@/lib/matchday/neutral";
import type { AStrings } from "@/lib/matchday/i18n-analysis";
import { teamVar, useMD } from "../context";
import { PanelState, useA, useNames } from "./common";

export const CATEGORY: Record<string, { color: string; icon: string }> = {
  event: { color: "var(--accent)", icon: "●" }, momentum: { color: "#4FC3F7", icon: "↗" }, pressing: { color: "#FF8A65", icon: "⇉" },
  model: { color: "#B39DDB", icon: "◆" }, tactical: { color: "#81C784", icon: "▦" }, physical: { color: "#FFB74D", icon: "⚡" },
  player: { color: "#F06292", icon: "◉" }, discipline: { color: "#F5C518", icon: "▮" }, set_piece: { color: "#4DD0E1", icon: "⚑" },
};
const ORDER = Object.keys(CATEGORY);

/** Strategist question for an insight. */
export function questionFor(i: Insight, team: string, A: AStrings, pName: (pid: string | null | undefined, fallback?: string | null) => string): string {
  const s = i.subject;
  if (s?.type === "substitution") {
    const o = s.options[0];
    return A.qInsSub(team, o ? pName(o.off.player_id, o.off.name) : "—", o?.on ? pName(o.on.player_id, o.on.name) : null);
  }
  if (s?.type === "best_player") return A.qInsBest(A.situationQ[s.situation] ?? s.situation.replace("_", " "), team);
  if (s?.type === "player") return A.qInsPlayer(pName(s.player_id, s.name), team, neutral(s.reasons[0] ?? i.title));
  return A.qInsGeneric(neutral(i.title), i.minute, team);
}

export default function InsightFeed() {
  const { meta, lang, matchId, clock } = useMD();
  const A = useA();
  const { pName, sideOf, tName } = useNames();
  const { list, insights, status } = useInsights(matchId);
  const { takes, request } = useAiTake(matchId);
  const [cat, setCat] = useState("all");
  const [open, setOpen] = useState<string | null>(null);
  const cats = ORDER.filter((c) => insights.some((i) => i.category === c)).concat([...new Set(insights.map((i) => i.category))].filter((c) => !ORDER.includes(c)));
  const rows = insights.filter((i) => cat === "all" || i.category === cat).slice().reverse();
  const clk = clockLabel(meta.periods, clock.t);
  return (
    <section className="card" aria-label={A.feedTitle(clk)}>
      <div className="card-h">
        <h3>{A.feedTitle(clk)}</h3>
        <span className="tag">{A.soFar(insights.length)}{list?.sources?.length ? ` · ${list.sources.join(" + ")}` : ""}{list?.partial ? ` · ${A.warming}` : ""}</span>
      </div>
      <div className="card-b">
        {insights.length > 0 && (
          <div className="ovbar" role="radiogroup" aria-label={A.filterBy}>
            <button className={`ovbtn ${cat === "all" ? "on" : ""}`} role="radio" aria-checked={cat === "all"} onClick={() => setCat("all")}>{A.all}</button>
            {cats.map((c) => (
              <button key={c} className={`ovbtn an-catbtn ${cat === c ? "on" : ""}`} role="radio" aria-checked={cat === c} onClick={() => setCat(c)}>
                <span className="ic" style={{ color: CATEGORY[c]?.color ?? "var(--mute)" }} aria-hidden="true">{CATEGORY[c]?.icon ?? "●"}</span>{A.cats[c] ?? c}
              </button>
            ))}
          </div>
        )}
        {!list && status !== "ready" ? <PanelState status={status} /> : !rows.length ? <p className="dim">{A.noInsights}</p> : (
          <div className="an-feed">
            {rows.map((i) => {
              const side = sideOf(i.team_id);
              const c = CATEGORY[i.category] ?? CATEGORY.event;
              const isOpen = open === i.id;
              const take = takes[i.id];
              const card = take?.data?.card;
              const s = i.subject;
              const team = tName(i.team_id) || A.theTeam;
              return (
                <div key={i.id} className={`an-ins p${i.priority}`} style={{ borderLeftColor: c.color }}>
                  <button className="an-ins-h" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : i.id)}>
                    <span className="mono mute">{clockLabel(meta.periods, i.t_ms)}</span>
                    <span style={{ color: c.color }} aria-label={A.cats[i.category] ?? i.category}>{c.icon}</span>
                    <span className="ttl">{side != null && <b style={{ color: teamVar(side) }}>{teamShort(side ? meta.away : meta.home, lang)} </b>}{neutral(i.title)}</span>
                    {i.priority === 1 ? <span className="an-urg high">{A.keyBadge}</span> : <span />}
                  </button>
                  {isOpen && (
                    <div className="an-ins-b">
                      <span>{neutral(i.detail)}</span>
                      {i.evidence.length > 0 && <span className="an-ev">{A.evidenceLbl}: {i.evidence.map(neutral).join(" · ")}</span>}
                      {take && (
                        <div className="an-take" aria-live="polite">
                          <span className="an-mono-note" style={{ color: "var(--accent-text)" }}>{A.aiTake}{take.data?.model ? ` · ${take.data.model.toUpperCase()}` : ""}</span>
                          {take.state === "loading" && <span className="an-thinking"><span className="spin" aria-hidden="true" />{A.aiChecking}</span>}
                          {take.state === "error" && <span className="dim">{A.aiTakeNA}</span>}
                          {card && <><span><b style={{ color: "#e5576c" }}>{A.riskLbl}</b> {neutral(card.main_risk)}</span><span><b style={{ color: "var(--good)" }}>{A.doLbl}</b> {neutral(card.one_action)}</span></>}
                          {take.state === "done" && !card && take.data?.raw && <span>{neutral(take.data.raw)}</span>}
                        </div>
                      )}
                      <div className="an-row">
                        <button className="btn ghost an-sm" onClick={() => { if (i.seek_ms != null) watchAt(i.seek_ms, 0); else watchAt(i.t_ms); openTab("live"); }}>▶ {A.watch}</button>
                        {(!take || take.state === "error") && <button className="btn ghost an-sm" onClick={() => request(i.id)}>{A.aiTake}</button>}
                        {s && (
                          <button className="btn ghost an-sm" onClick={() => handoff({
                            type: "coach", section: s.type === "substitution" ? "subs" : s.type === "best_player" ? "best" : "form",
                            teamSide: sideOf(s.team_id) ?? undefined, playerId: s.type === "player" ? s.player_id : undefined,
                          })}>{A.coachDetails}</button>
                        )}
                        <button className="btn ghost an-sm" onClick={() => askAI(questionFor(i, team, A, pName))}>{A.askAI}</button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
