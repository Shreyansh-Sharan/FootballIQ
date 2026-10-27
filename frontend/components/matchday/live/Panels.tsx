"use client";

// Live tab panels, all cut at the replay clock; 404 / 503 show as "not available".

import { useMemo } from "react";
import { useKeyed, type Status } from "@/lib/matchday/api";
import { mdApi } from "@/lib/matchday/api";
import { CLOCK } from "@/lib/matchday/clock";
import { useTeamOffered } from "@/lib/matchday/analysis";
import { askTeam, handoff, openTab } from "@/lib/matchday/handoff";
import { AU } from "@/lib/matchday/i18n-analysis";
import { buildStory, declaredShapes, scorersAt, type Story, type Tone } from "@/lib/matchday/live";
import { clockLabel, teamName, teamShort } from "@/lib/matchday/match";
import type { FormationsResp, Predictions, SideIdx, TacticalWindowRef, TeamStats } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";
import { I } from "../Icons";
import { StateNote } from "../StateNote";

const toneVar = (t: Tone) => (t === "n" ? "var(--contested)" : teamVar(t));
const pc = (v: number | null | undefined) => (v == null ? "—" : `${(100 * v).toFixed(v < 0.1 ? 1 : 0)}%`);

// ------------------------------------------------------------------ key message
export function KeyMessage({ pred }: { pred: { data: Predictions | null; status: Status } }) {
  const { U, meta, lang, clock, score, state, events } = useMD();
  const story: Story = buildStory({
    U, meta, t: clock.t, clock: clockLabel(meta.periods, clock.t), score, state: state.data, events: events.data, pred: pred.data, predStatus: pred.status,
    short: [teamShort(meta.home, lang), teamShort(meta.away, lang)], name: [teamName(meta.home, lang), teamName(meta.away, lang)],
  });
  return (
    <section className="answer card" aria-labelledby="answer-h">
      <div className="answer-main">
        <div className="kicker">{story.kicker}</div>
        <h2 id="answer-h">{story.headline}</h2>
        <p>{story.sub}</p>
      </div>
      <div className="pillars">
        {story.pillars.map((p) => (
          <div className="pillar" key={p.title} style={{ "--pc": toneVar(p.tone) } as React.CSSProperties}>
            <div className="tag">{p.title}</div>
            <b>{p.value}</b>
            {p.detail && <span className="mono">{p.detail}</span>}
          </div>
        ))}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ meta line
export function MatchMetaLine() {
  const { U, meta, lang, clock, events } = useMD();
  const sc = useMemo(() => scorersAt(events.data, clock.t, meta), [events.data, clock.t, meta]);
  const line = (k: SideIdx) => sc[k].map((g) => `${g.name ? g.name.split(" ").slice(-1)[0] : U.ev.ownGoalBy} ${g.min}${g.pen ? ` (${U.pen})` : ""}${g.og ? ` (${U.og})` : ""}`).join(", ");
  const where = [meta.competition, meta.stage, meta.stadium].filter(Boolean).join(" · ");
  return (
    <div className="mmeta">
      <span className="mm-teams">
        <b style={{ color: "var(--home)" }}>{teamName(meta.home, lang)}</b> <span className="mute">{U.vs}</span> <b style={{ color: "var(--away)" }}>{teamName(meta.away, lang)}</b>
      </span>
      {where && <span className="dim">{where}</span>}
      <span className="sp" />
      {(sc[0].length > 0 || sc[1].length > 0) && (
        <span className="mm-sc">
          {sc[0].length > 0 && <span><i className="dot" style={{ background: "var(--home)" }} />{line(0)}</span>}
          {sc[1].length > 0 && <span><i className="dot" style={{ background: "var(--away)" }} />{line(1)}</span>}
        </span>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ split rows
export function SplitRow({ label, a, b, av, bv }: { label: string; a: string; b: string; av: number; bv: number }) {
  const tot = av + bv || 1;
  return (
    <div className="split">
      <div className="split-l"><b className="mono" style={{ color: "var(--home)" }}>{a}</b><span>{label}</span><b className="mono" style={{ color: "var(--away)" }}>{b}</b></div>
      <div className="split-bar" aria-hidden="true">
        <i style={{ flexGrow: Math.max(0.02, av / tot), background: "var(--home)" }} />
        <i style={{ flexGrow: Math.max(0.02, bv / tot), background: "var(--away)" }} />
      </div>
    </div>
  );
}

const n = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? 0 : v);
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(0)}%`);

export function StatsCard() {
  const { U, meta, lang, clock, state } = useMD();
  const s = state.data?.stats;
  const h: TeamStats | undefined = s?.[meta.home.team_id];
  const a: TeamStats | undefined = s?.[meta.away.team_id];
  const acc = (x?: TeamStats) => (x && x.shots ? (100 * n(x.shots_on_target)) / x.shots : 0);
  return (
    <div className="card">
      <div className="card-h"><h3>{U.statsL.title}</h3><span className="tag">{U.statsL.upTo(clockLabel(meta.periods, clock.t))}</span></div>
      <div className="card-b">
        {!h || !a ? <StateNote status={state.status === "ready" ? "loading" : state.status} empty={U.statsL.waiting} /> : (
          <>
            <div className="split-head"><b style={{ color: "var(--home)" }}>{teamShort(meta.home, lang)}</b><b style={{ color: "var(--away)" }}>{teamShort(meta.away, lang)}</b></div>
            <SplitRow label={U.statsL.possession} a={pct(h.possession_pct)} b={pct(a.possession_pct)} av={n(h.possession_pct)} bv={n(a.possession_pct)} />
            <SplitRow label={U.statsL.shots} a={`${n(h.shots)}`} b={`${n(a.shots)}`} av={n(h.shots)} bv={n(a.shots)} />
            <SplitRow label={U.statsL.onTarget} a={`${n(h.shots_on_target)}`} b={`${n(a.shots_on_target)}`} av={n(h.shots_on_target)} bv={n(a.shots_on_target)} />
            <SplitRow label={U.statsL.xg} a={n(h.provider_xg).toFixed(2)} b={n(a.provider_xg).toFixed(2)} av={n(h.provider_xg)} bv={n(a.provider_xg)} />
            <SplitRow label={U.statsL.passes} a={`${n(h.passes_completed)}/${n(h.passes_attempted)}`} b={`${n(a.passes_completed)}/${n(a.passes_attempted)}`} av={n(h.passes_attempted)} bv={n(a.passes_attempted)} />
            <SplitRow label={U.statsL.passAcc} a={pct(h.pass_accuracy_pct)} b={pct(a.pass_accuracy_pct)} av={n(h.pass_accuracy_pct)} bv={n(a.pass_accuracy_pct)} />
            <SplitRow label={U.statsL.tacklesWon} a={`${n(h.tackles_won)}/${n(h.tackles)}`} b={`${n(a.tackles_won)}/${n(a.tackles)}`} av={n(h.tackles_won)} bv={n(a.tackles_won)} />
            <SplitRow label={U.statsL.corners} a={`${n(h.corners)}`} b={`${n(a.corners)}`} av={n(h.corners)} bv={n(a.corners)} />
            <SplitRow label={U.statsL.yellows} a={`${n(h.yellow_cards)}`} b={`${n(a.yellow_cards)}`} av={n(h.yellow_cards)} bv={n(a.yellow_cards)} />
            <div className="acc">
              <AccCard label={U.statsL.shotAcc} a={acc(h)} b={acc(a)} as={U.statsL.onTargetOf(n(h.shots_on_target), n(h.shots))} bs={U.statsL.onTargetOf(n(a.shots_on_target), n(a.shots))} />
              <AccCard label={U.statsL.passAcc} a={n(h.pass_accuracy_pct)} b={n(a.pass_accuracy_pct)} as={U.statsL.completedOf(n(h.passes_completed), n(h.passes_attempted))} bs={U.statsL.completedOf(n(a.passes_completed), n(a.passes_attempted))} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function AccCard({ label, a, b, as, bs }: { label: string; a: number; b: number; as: string; bs: string }) {
  return (
    <div className="acc-card">
      <div className="acc-top"><b className="mono" style={{ color: "var(--home)" }}>{a.toFixed(0)}%</b><span className="tag">{label}</span><b className="mono" style={{ color: "var(--away)" }}>{b.toFixed(0)}%</b></div>
      <div className="acc-bars" aria-hidden="true">
        <div><i style={{ width: `${Math.min(100, a)}%`, background: "var(--home)", marginLeft: "auto" }} /></div>
        <div><i style={{ width: `${Math.min(100, b)}%`, background: "var(--away)" }} /></div>
      </div>
      <div className="acc-sub mono"><span>{as}</span><span>{bs}</span></div>
    </div>
  );
}

// ------------------------------------------------------------------ model outputs
export function ModelCard({ pred }: { pred: { data: Predictions | null; status: Status } }) {
  const { U, meta, lang } = useMD();
  const d = pred.data;
  const h = d?.teams[meta.home.team_id] ?? {}, a = d?.teams[meta.away.team_id] ?? {};
  const phase = d?.phase ? U.model.phases[d.phase] ?? d.phase : U.model.phase;
  return (
    <div className="card">
      <div className="card-h"><h3>{U.model.title}</h3><span className="tag">{U.model.live}</span></div>
      <div className="card-b">
        {pred.status === "missing" ? <StateNote status="ready" empty={U.model.notScored} /> : !d ? <StateNote status={pred.status} /> : (
          <>
            <div className="split-head"><b style={{ color: "var(--home)" }}>{teamShort(meta.home, lang)}</b><b style={{ color: "var(--away)" }}>{teamShort(meta.away, lang)}</b></div>
            <SplitRow label={U.model.win(phase)} a={pc(h.win_phase?.probability)} b={pc(a.win_phase?.probability)} av={n(h.win_phase?.probability)} bv={n(a.win_phase?.probability)} />
            <div className="tag" style={{ textAlign: "center" }}>{U.model.draw} {pc(d.draw_phase?.probability)}</div>
            <SplitRow label={U.model.goal10} a={pc(h.goal_next_10m?.probability)} b={pc(a.goal_next_10m?.probability)} av={n(h.goal_next_10m?.probability)} bv={n(a.goal_next_10m?.probability)} />
            <SplitRow label={U.model.corner2} a={pc(h.corner_next_2m?.probability)} b={pc(a.corner_next_2m?.probability)} av={n(h.corner_next_2m?.probability)} bv={n(a.corner_next_2m?.probability)} />
          </>
        )}
        <button className="btn ghost sm" style={{ alignSelf: "flex-start" }} onClick={() => openTab("models")}>{U.model.open}</button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ tactical window + formation now
export function TacticalCard({ windows, formations }: { windows: { data: { windows: TacticalWindowRef[] } | null; status: Status }; formations: { data: FormationsResp | null; status: Status } }) {
  const { U, meta, lang, clock, events, matchId } = useMD();
  const t = clock.t;
  const allWin = windows.data?.windows ?? [];
  const done = allWin.filter((w) => w.available && w.end_ms <= t);
  const last = done[done.length - 1];
  const key = (tid: string) => (last ? `${matchId}|${tid}|${last.window_id}` : null);
  const hw = useKeyed(key(meta.home.team_id), () => mdApi.tacticalWindow(matchId, meta.home.team_id, last!.window_id, last!.end_ms));
  const aw = useKeyed(key(meta.away.team_id), () => mdApi.tacticalWindow(matchId, meta.away.team_id, last!.window_id, last!.end_ms));
  const declared = declaredShapes(events.data, t, meta);
  const now: [string | null, string | null] = [null, null];
  for (const s of formations.data?.segments ?? []) {
    if (s.end_ms > t || !s.formation) continue;
    const k = s.team_id === meta.home.team_id ? 0 : s.team_id === meta.away.team_id ? 1 : null;
    if (k != null) now[k] = s.formation;
  }
  type M = NonNullable<typeof hw.data>["metrics"];
  const rows: [string, (m: M) => string][] = [
    [U.tac.detected, (m) => m.formation ?? "—"],
    [U.tac.declared, (m) => m.declared_formation ?? "—"],
    [U.tac.possession, (m) => (m.possession_pct == null ? "—" : `${m.possession_pct.toFixed(0)}%`)],
    [U.tac.links, (m) => m.links_per_sample?.toFixed(1) ?? "—"],
    [U.tac.lanes, (m) => (m.lane_clearance_pct == null ? "—" : `${m.lane_clearance_pct.toFixed(0)}%`)],
    [U.tac.triangles, (m) => m.triangles_per_sample?.toFixed(1) ?? "—"],
    [U.tac.regains, (m) => (m.regains == null ? "—" : `${m.regains}`)],
  ];
  return (
    <div className="card">
      <div className="card-h"><h3>{U.tac.title}</h3><span className="tag">{last ? U.tac.lastWindow(last.label) : clockLabel(meta.periods, t)}</span></div>
      <div className="card-b">
        <div className="fnow" aria-label={U.tac.formationNow}>
          {([0, 1] as SideIdx[]).map((k) => (
            <div key={k} className="fchip" style={{ borderColor: teamVar(k) }} title={U.tac.detectedHint}>
              <span className="tag">{teamShort(k ? meta.away : meta.home, lang)} · {U.tac.formationNow}</span>
              <b>{now[k] ?? "—"}</b>
              <small>{U.tac.declaredShort} {declared[k] ?? "—"}</small>
            </div>
          ))}
        </div>
        {windows.status !== "ready" && !windows.data ? <StateNote status={windows.status} small />
          : !last ? (allWin.length && allWin[0].end_ms > t ? <p className="dim" style={{ fontSize: 13 }}>{U.tac.firstWindow}</p> : <StateNote status="missing" small />) : (
          <table className="ptable tac-t">
            <thead><tr><th style={{ color: "var(--home)" }}>{teamShort(meta.home, lang)}</th><th /><th style={{ color: "var(--away)", textAlign: "right" }}>{teamShort(meta.away, lang)}</th></tr></thead>
            <tbody>
              {rows.map(([label, f]) => (
                <tr key={label}>
                  <td className="mono">{hw.data ? f(hw.data.metrics) : hw.status === "loading" ? "…" : "—"}</td>
                  <td className="dim" style={{ textAlign: "center" }}>{label}</td>
                  <td className="mono" style={{ textAlign: "right" }}>{aw.data ? f(aw.data.metrics) : aw.status === "loading" ? "…" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button className="btn ghost sm" style={{ alignSelf: "flex-start" }} onClick={() => openTab("tactical")}>{U.tac.open}</button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ explain this moment
export function ExplainCard() {
  const { U, clock, meta, lang } = useMD();
  const T = AU[lang].crew;
  const clk = clockLabel(meta.periods, clock.t);
  const team = useTeamOffered() !== false;
  return (
    <div className="card explain">
      <div className="card-b">
        <div className="explain-h"><span className="av">{I.spark}</span><div><b>{U.explain.title}</b><span className="dim">{U.explain.sub}</span></div></div>
        <button className="btn" onClick={() => handoff({ type: "explain" })}>{I.spark}<span>{U.explain.title} · {clk}</span></button>
        {team && (
          <button className="btn ghost explain-team" onClick={() => askTeam(T.live.q(clockLabel(meta.periods, CLOCK.t)))} title={T.live.sub}>
            {I.ai}<span>{T.live.btn} · {clk}</span>
          </button>
        )}
      </div>
    </div>
  );
}
