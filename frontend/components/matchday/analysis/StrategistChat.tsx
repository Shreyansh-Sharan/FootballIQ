"use client";

// Match Strategist chat. Each question is pinned to the replay clock; the server binds the tools to it.
// Handed-over questions wait until the agent service is ready.

import { useEffect, useRef, useState } from "react";
import { useAgentStatus, useChat, type AgentToolCall } from "@/lib/matchday/analysis";
import { onHandoff, takePendingQuestion, watchAt } from "@/lib/matchday/handoff";
import { clockLabel, playerName, teamName } from "@/lib/matchday/match";
import { neutral } from "@/lib/matchday/neutral";
import { useMD } from "../context";
import AgentText from "./AgentText";
import { useA, useSuggestions } from "./common";

export default function StrategistChat() {
  const { meta, lang, matchId, clock, players } = useMD();
  const A = useA();
  const status = useAgentStatus();
  const configured = !!status.data?.configured;
  const { turns, busy, ask, reset } = useChat(matchId);
  const [q, setQ] = useState("");
  const [queued, setQueued] = useState<string | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const t = clock.t;
  const clk = clockLabel(meta.periods, t);

  useEffect(() => {
    const p = takePendingQuestion();
    if (p) setQueued(p);
    return onHandoff((h) => {
      if (h.type !== "ask") return;
      const p2 = takePendingQuestion();
      if (p2) setQueued(p2);
    });
  }, []);
  useEffect(() => {
    if (!queued || busy || status.status === "loading") return;
    if (configured) { void ask(queued); setQueued(null); }
    else if (status.status !== "error") { setQ(queued); setQueued(null); }
  }, [queued, busy, configured, status.status, ask]);
  useEffect(() => {
    const el = log.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [turns.length, busy, turns[turns.length - 1]?.a]); // eslint-disable-line react-hooks/exhaustive-deps

  const suggestions = useSuggestions();
  // hover title: tool args with ids replaced by names
  const argsText = (c: AgentToolCall) => {
    let s = JSON.stringify(c.arguments ?? {});
    s = s.split(meta.home.team_id).join(teamName(meta.home, lang)).split(meta.away.team_id).join(teamName(meta.away, lang));
    s = s.replace(/p-[a-z0-9]{6}/g, (id) => { const p = players.get(id); return p ? playerName(p, lang) : id; });
    return neutral(s);
  };
  const lastAsked = turns[turns.length - 1]?.askedAt ?? t;
  const send = () => { if (q.trim() && !busy && configured) { void ask(q); setQ(""); } };

  return (
    <section className="card" aria-label={A.strategist}>
      <div className="card-h">
        <h3>{A.strategist}</h3>
        <div className="an-row">
          {turns.length > 0 && <button className="chip" onClick={reset} disabled={busy}>{A.newConv}</button>}
        </div>
      </div>
      <div className="card-b">
        {status.status === "ready" && !configured && (
          <div className="note notrack" role="status"><b>{A.notConfigured}</b><span>{A.notConfiguredSub}</span></div>
        )}
        {(status.status === "error" || status.status === "missing") && <div className="note err" role="status">{A.agentDown}</div>}
        <div ref={log} className="an-chat" aria-live="polite" aria-busy={busy} style={{ maxHeight: 640, overflowY: "auto", paddingRight: 4 }}>
          {turns.length === 0 && (
            <div className="col" style={{ gap: 8 }}>
              <span className="tag">{A.tryAsking}</span>
              <div className="an-sugs">
                {suggestions.map((s) => <button key={s} className="an-sug" disabled={busy || !configured} onClick={() => void ask(s)}>{s}</button>)}
              </div>
            </div>
          )}
          {turns.map((tn) => {
            const askedClk = clockLabel(meta.periods, tn.askedAt);
            return (
              <div key={tn.id} className="an-turn">
                <div className="an-q"><span className="an-mono-note">{A.you(askedClk)}</span><span>{tn.q}</span></div>
                {tn.a && tn.askedAt > t + 1000 && (
                  <div className="note warn small" role="status">
                    <span>{A.futureAns(askedClk)} <button className="an-link" onClick={() => watchAt(tn.askedAt, 0)}>{A.goTo(askedClk)}</button></span>
                  </div>
                )}
                {tn.a && tn.askedAt <= t + 1000 && (
                  <div className="an-a">
                    <AgentText text={tn.a.answer} />
                    <div className="an-row">
                      <span className="an-mono-note">{A.evidence}</span>
                      {tn.a.tool_calls.map((c, k) => (
                        <span key={k} className={`chip ${c.ok ? "" : "an-warn"}`} title={argsText(c)}>{c.ok ? "✓" : "∅"} {A.tools[c.name] ?? c.name.replace(/^get_/, "").replace(/_/g, " ")}</span>
                      ))}
                      <span className="an-grow" />
                      <span className="an-mono-note">{A.answerMeta((tn.a.model ?? "").toUpperCase(), tn.a.seconds.toFixed(0), clockLabel(meta.periods, tn.a.at_ms ?? tn.askedAt))}</span>
                    </div>
                    {Math.abs(t - tn.askedAt) > 60000 && (
                      <div className="note warn small" role="status">
                        <span>{A.stale(askedClk, clk)} <button className="an-link" onClick={() => watchAt(tn.askedAt, 0)}>{A.goBack(askedClk)}</button></span>
                      </div>
                    )}
                  </div>
                )}
                {tn.error && <div className="note err" role="status">{tn.error === "unavailable" ? A.agentNA : A.agentFailed}</div>}
              </div>
            );
          })}
          {busy && <div className="an-a"><div className="an-thinking"><span className="spin" aria-hidden="true" />{A.thinking(clockLabel(meta.periods, lastAsked))}</div></div>}
          {queued && !busy && status.status === "loading" && <div className="an-thinking"><span className="spin" aria-hidden="true" />{A.waitingAgents}</div>}
        </div>
        <form className="an-input" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={2000} disabled={busy || !configured} aria-label={A.question}
            placeholder={configured ? A.placeholder(clk) : A.placeholderOff} />
          <button className="btn" disabled={busy || !q.trim() || !configured}>{busy ? "…" : A.ask}</button>
        </form>
        <p className="an-small">{A.disclaimer}</p>
      </div>
    </section>
  );
}
