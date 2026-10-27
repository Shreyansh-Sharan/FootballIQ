"use client";

// AI Analyst tab: Strategist chat or the agent team (mode switch, remembered), Moment Explainer and the insight feed.
// An "ask" handoff opens the single analyst; a "team" handoff opens the agent team.

import { useCallback, useEffect, useState } from "react";
import { useTeamOffered } from "@/lib/matchday/analysis";
import { onHandoff, pendingAiMode } from "@/lib/matchday/handoff";
import { clockLabel } from "@/lib/matchday/match";
import { useMD } from "../context";
import AgentTeam from "../analysis/AgentTeam";
import { KeyMessage, useA } from "../analysis/common";
import ExplainerCard from "../analysis/ExplainerCard";
import InsightFeed from "../analysis/InsightFeed";
import StrategistChat from "../analysis/StrategistChat";

type Mode = "single" | "team";
const MODE_KEY = "fiq.matchday.aiMode";
const saveMode = (m: Mode) => { try { localStorage.setItem(MODE_KEY, m); } catch { /* storage blocked: keep in memory */ } };

/** Pending handoff first (it must pick the mode before the panels mount and consume it), then the remembered mode. */
function initialMode(): Mode {
  if (typeof window === "undefined") return "team";
  const p = pendingAiMode();
  if (p) { saveMode(p); return p; }
  try { const m = localStorage.getItem(MODE_KEY); if (m === "single" || m === "team") return m; } catch { /* storage blocked */ }
  return "team";
}

export default function AITab() {
  const { U, meta, clock } = useMD();
  const A = useA();
  const clk = clockLabel(meta.periods, clock.t);
  const [mode, setModeRaw] = useState<Mode>(initialMode);
  const setMode = useCallback((m: Mode) => { setModeRaw(m); saveMode(m); }, []);
  useEffect(() => onHandoff((h) => {
    if (h.type === "ask") setMode("single");
    else if (h.type === "team") setMode("team");
  }), [setMode]);
  const modes: [Mode, string][] = [["single", A.crew.single], ["team", A.crew.multi]];
  // an API without the agent team (404 / 501 / 503 on the roster) keeps the single analyst and no mode switch
  const offered = useTeamOffered() !== false;
  const shown: Mode = offered ? mode : "single";
  return (
    <div className="col">
      <KeyMessage label={U.tabs.ai} kicker={`${U.tabs.ai} · ${A.liveAt(clk)}`} headline={A.aiTitle} sub={A.aiSub(clk)} />
      <div className="grid-live wider-side">
        <div className="col">
          {offered && (
            <div className="at-mode">
              <span className="tag" id="ai-mode-l">{A.crew.mode}</span>
              <div className="seg" role="radiogroup" aria-labelledby="ai-mode-l">
                {modes.map(([k, l]) => (
                  <button key={k} role="radio" aria-checked={mode === k} className={mode === k ? "on" : ""} onClick={() => setMode(k)}>
                    {l}{k === "team" && <span className="at-new">{A.crew.newBadge}</span>}
                  </button>
                ))}
              </div>
            </div>
          )}
          {shown === "team" ? <AgentTeam /> : <StrategistChat />}
        </div>
        <div className="col">
          <ExplainerCard />
          <InsightFeed />
        </div>
      </div>
    </div>
  );
}
