"use client";

// Moment Explainer at the replay clock; an "explain" handoff runs it on arrival.

import { useEffect, useState } from "react";
import { takePendingExplain, useAgentStatus, useExplainer } from "@/lib/matchday/analysis";
import { onHandoff, watchAt } from "@/lib/matchday/handoff";
import { clockLabel } from "@/lib/matchday/match";
import { neutral } from "@/lib/matchday/neutral";
import { useMD } from "../context";
import { useA } from "./common";

const TONE: Record<string, string> = { high: "var(--good)", medium: "var(--warn)", low: "#e5576c" };

export default function ExplainerCard() {
  const { meta, matchId, clock } = useMD();
  const A = useA();
  const status = useAgentStatus();
  const configured = !!status.data?.configured;
  const { res, error, busy, askedAt, run } = useExplainer(matchId);
  const [queued, setQueued] = useState(false);
  useEffect(() => {
    if (takePendingExplain()) setQueued(true);
    return onHandoff((h) => { if (h.type === "explain") { takePendingExplain(); setQueued(true); } });
  }, []);
  useEffect(() => {
    if (!queued || busy || status.status === "loading") return;
    setQueued(false);
    if (configured) void run();
  }, [queued, busy, configured, status.status, run]);

  const t = clock.t;
  const c = res?.card;
  const future = !!res && res.at_ms > t + 1000;
  const head = busy && askedAt != null ? clockLabel(meta.periods, askedAt) : res ? clockLabel(meta.periods, res.at_ms) : clockLabel(meta.periods, t);
  return (
    <section className="card" aria-label={A.explainer} style={{ borderColor: "color-mix(in srgb, var(--accent) 45%, var(--line))" }}>
      <div className="card-h">
        <h3>{A.explainer}</h3>
        <span className="tag">{head}</span>
      </div>
      <div className="card-b" aria-live="polite" aria-busy={busy}>
        <button className="btn" style={{ alignSelf: "flex-start" }} disabled={busy || !configured} onClick={() => void run()}>
          {busy ? A.explThinking : res ? A.explainAgain : A.explain}
        </button>
        {!res && !busy && !error && <p className="dim" style={{ fontSize: 14 }}>{configured || status.status !== "ready" ? A.explIntro : A.notConfiguredSub}</p>}
        {busy && <div className="an-thinking"><span className="spin" aria-hidden="true" />{A.calling(clockLabel(meta.periods, askedAt ?? t))}</div>}
        {error && <div className="note err" role="status">{error === "unavailable" ? A.agentNA : A.agentFailed}</div>}
        {res && future && (
          <div className="note warn small" role="status">
            <span>{A.futureAns(clockLabel(meta.periods, res.at_ms))} <button className="an-link" onClick={() => watchAt(res.at_ms, 0)}>{A.goTo(clockLabel(meta.periods, res.at_ms))}</button></span>
          </div>
        )}
        {res && !future && !c && <p style={{ fontSize: 14 }}>{neutral(res.raw)}</p>}
        {res && !future && c && (
          <>
            <div className="an-ex-head">{neutral(c.headline)}</div>
            <p style={{ fontSize: 14, lineHeight: 1.5 }}>{neutral(c.what_is_happening)}</p>
            <div className="an-ex-row"><b style={{ color: "#e5576c" }}>{A.risk.toUpperCase()}</b><span>{neutral(c.main_risk)}</span></div>
            <div className="an-ex-row"><b style={{ color: "var(--good)" }}>{A.action.toUpperCase()}</b><span>{neutral(c.one_action)}</span></div>
            {c.evidence.length > 0 && (
              <div className="col" style={{ gap: 3 }}>
                <span className="tag">{A.evidence}</span>
                {c.evidence.map((e, i) => <div key={i} className="an-ev">▸ <b>{neutral(e.source).toUpperCase()}</b>: {neutral(e.detail)}</div>)}
              </div>
            )}
            <div className="an-row" style={{ font: "600 10.5px var(--mono)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
              <span style={{ color: TONE[c.confidence] ?? "var(--mute)" }}>{A.confidence(A.confs[c.confidence] ?? c.confidence)}</span>
              <span className="mute">{(res.model ?? "").toUpperCase()} · {res.seconds.toFixed(0)} s · {A.toolCalls(res.tool_calls.length)}</span>
              {Math.abs(t - res.at_ms) > 60000 && <button className="an-link" onClick={() => watchAt(res.at_ms, 0)}>{A.backTo(clockLabel(meta.periods, res.at_ms))}</button>}
            </div>
          </>
        )}
        {res && !future && !c && Math.abs(t - res.at_ms) > 60000 && <button className="an-link" style={{ alignSelf: "flex-start" }} onClick={() => watchAt(res.at_ms, 0)}>{A.backTo(clockLabel(meta.periods, res.at_ms))}</button>}
      </div>
    </section>
  );
}
