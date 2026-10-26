"use client";

// Live tab: key message, the pitch stage and live panels, with instruments, commentary and match centre
// alongside. Theatre mode stacks everything under a full-width pitch.

import { useState } from "react";
import { mdApi, useBucketResource } from "@/lib/matchday/api";
import { CLOCK } from "@/lib/matchday/clock";
import { askAI, handoff } from "@/lib/matchday/handoff";
import { clockLabel, playerShort, teamShort } from "@/lib/matchday/match";
import { relevance, renderInsight } from "@/lib/matchday/perspective";
import CommentaryBooth from "../CommentaryBooth";
import { teamVar, useMD } from "../context";
import { ChaosMeter, RhythmStrip, WinChance } from "../Instruments";
import EventTracker from "../live/EventTracker";
import Lineups from "../live/Lineups";
import { useLive } from "../live/LiveCtx";
import { ExplainCard, KeyMessage, MatchMetaLine, ModelCard, StatsCard, TacticalCard } from "../live/Panels";
import Toolbar from "../live/Toolbar";
import PersonaStrip from "../PersonaStrip";
import ShapeCards from "../ShapeCards";
import { StateNote } from "../StateNote";

type Centre = "feed" | "events" | "lineups";

export default function LiveTab() {
  const md = useMD();
  const lv = useLive();
  const { U, view, meta, lang, clock, point, moments, ctx, players, focus, focusId, matchId } = md;
  const pred = useBucketResource(`${matchId}|pred`, 15000, (at) => mdApi.predictions(matchId, at));
  const windows = useBucketResource(`${matchId}|win`, 30000, (at) => mdApi.tacticalWindows(matchId, at));
  const formations = useBucketResource(`${matchId}|form`, 15000, (at) => mdApi.formations(matchId, at));
  const [centre, setCentre] = useState<Centre>("feed");
  const t = clock.t;
  const feed = moments.data.moments.filter((m) => m.t_ms <= t).map((m) => ({ m, r: relevance(m, view) })).filter((x) => x.r >= 0.12).slice(-14).reverse();
  const fp = focus.data;
  const fpl = focusId ? players.get(focusId) : undefined;
  const mv: [string, string, string] | null = !fp ? null
    : view.metric === "speed" ? [fp.top_kmh != null ? fp.top_kmh.toFixed(1) : "–", U.kmh, U.topSpeed]
      : view.metric === "distance" ? [fp.dist_km != null ? fp.dist_km.toFixed(2) : "–", U.km, U.distance]
        : view.metric === "passing" ? [fp.passes ? String(Math.round((100 * fp.passes_ok) / fp.passes)) : "–", "%", U.passes]
          : view.metric === "xg" ? [(fp.xg ?? 0).toFixed(2), "xG", U.shots] : null;
  const flow = point?.flow ?? null;
  const tabs: [Centre, string][] = [["feed", U.centre.feed], ["events", U.centre.events], ["lineups", U.centre.lineups]];
  return (
    <div className="col">
      <KeyMessage pred={pred} />
      <PersonaStrip />
      <div className={`grid-live live-grid ${lv.theatre ? "theatre" : ""}`}>
        <div className="col">
          <div className="stage-slot" ref={lv.setSlot} />
          <Toolbar />
          <MatchMetaLine />
          <div className="grid-3 live-cards">
            <StatsCard />
            <ModelCard pred={pred} />
            <TacticalCard windows={windows} formations={formations} />
          </div>
          <div className="card">
            <div className="card-h"><h3>{U.shapeNow}</h3><span className="tag">{U.compactRef}: {U.length} ≤ 35 m · {U.width} ≤ 40 m</span></div>
            <div className="card-b"><ShapeCards /></div>
          </div>
          <div className="card">
            <div className="card-h">
              <h3>{U.rhythm}</h3>
              {flow && <span className="chip" style={{ background: `var(--p-${flow.pattern})`, color: "#fff", border: 0 }}>{U.rhythmNow}: {U.patterns[flow.pattern] ?? flow.pattern}</span>}
            </div>
            <div className="card-b">{md.series.status === "ready" ? <RhythmStrip /> : <StateNote status={md.series.status} />}</div>
          </div>
        </div>
        <div className="col side">
          {point?.win && (
            <div className="card">
              <div className="card-h"><h3>{U.winChance}</h3><span className="tag">{clockLabel(meta.periods, t)}</span></div>
              <div className="card-b"><WinChance /></div>
            </div>
          )}
          {mv && fpl && view.metric !== "none" && (
            <div className="tile hl">
              <div className="k">{U.metric} · {playerShort(fpl, lang)}</div>
              <div className="v">{mv[0]}<small>{mv[1]}</small></div>
              <div className="s">{mv[2]}</div>
            </div>
          )}
          <ExplainCard />
          <div className="card">
            <div className="card-h"><h3>{U.controlChaos}</h3><span className="tag">5′</span></div>
            <div className="card-b">{flow ? <ChaosMeter flow={flow} /> : <StateNote status={md.series.status === "ready" ? "loading" : md.series.status} />}</div>
          </div>
          <CommentaryBooth />
          <div className="card centre">
            <div className="card-h">
              <h3>{U.centre.title}</h3>
              <div className="seg" role="tablist" aria-label={U.centre.title}>
                {tabs.map(([k, l]) => (
                  <button key={k} role="tab" id={`ct-${k}`} aria-controls="centre-panel" aria-selected={centre === k} className={centre === k ? "on" : ""} onClick={() => setCentre(k)}>{l}</button>
                ))}
              </div>
            </div>
            <div className="card-b" role="tabpanel" id="centre-panel" aria-labelledby={`ct-${centre}`}>
              {centre === "events" && <EventTracker />}
              {centre === "lineups" && <Lineups />}
              {centre === "feed" && (
                <>
                  <span className="tag">{U.feedSub}</span>
                  {moments.status !== "ready" && !feed.length ? <StateNote status={moments.status} /> : !feed.length ? <p className="dim">{U.noMoments}</p> : (
                    <div className="feed" aria-live="polite">
                      {feed.map(({ m, r }) => {
                        const rr = renderInsight(m, view, lang, ctx);
                        const kind = String(m.kind);
                        return (
                          <div className="fi" key={m.id}>
                            <span className="imp" style={{ background: teamVar(m.side), opacity: 0.35 + Math.min(1, r) * 0.65 }} />
                            <div className="m">{m.clock}</div>
                            <div>
                              <h4>{rr.h}</h4><p>{rr.b}</p>
                              <div className="meta">
                                {m.side != null && <span className="chip team" style={{ background: teamVar(m.side) }}>{teamShort(m.side ? meta.away : meta.home, lang)}</span>}
                                <span className="chip">{m.kind}{m.variant ? `·${m.variant}` : ""}</span>
                                <button className="link" onClick={() => CLOCK.seek(m.t_ms - 6000)}>{U.watch}</button>
                                <button className="link" onClick={() => askAI(U.q.moment(m.clock, rr.h))}>{U.askAI}</button>
                                {(kind === "sub" || kind === "card" || ((kind === "speed" || kind === "pass") && m.player_id)) && (
                                  <button className="link" onClick={() => handoff({ type: "coach", section: kind === "sub" ? "subs" : kind === "speed" ? "physical" : "form", teamSide: m.side ?? undefined, playerId: m.player_id ?? undefined })}>{U.coachLink}</button>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
