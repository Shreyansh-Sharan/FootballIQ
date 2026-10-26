"use client";

// AI Analyst tab: Strategist chat, Moment Explainer and the insight feed.

import { clockLabel } from "@/lib/matchday/match";
import { useMD } from "../context";
import { KeyMessage, useA } from "../analysis/common";
import ExplainerCard from "../analysis/ExplainerCard";
import InsightFeed from "../analysis/InsightFeed";
import StrategistChat from "../analysis/StrategistChat";

export default function AITab() {
  const { U, meta, clock } = useMD();
  const A = useA();
  const clk = clockLabel(meta.periods, clock.t);
  return (
    <div className="col">
      <KeyMessage label={U.tabs.ai} kicker={`${U.tabs.ai} · ${A.liveAt(clk)}`} headline={A.aiTitle} sub={A.aiSub(clk)} />
      <div className="grid-live wider-side">
        <StrategistChat />
        <div className="col">
          <ExplainerCard />
          <InsightFeed />
        </div>
      </div>
    </div>
  );
}
