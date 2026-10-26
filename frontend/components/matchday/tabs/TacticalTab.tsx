"use client";

// Tactical Workbench: two completed windows side by side with an A/B table and formation timeline.
// Windows refresh every 30 s of replay time (formations 60 s); a board opens only after its window ends.

import { useMemo, useState } from "react";
import { useTacticalWindow, useTacticalWindows, type FormationSegment, type TacticalMetrics, type TacticalWindow, type TacticalWindowRef } from "@/lib/matchday/analysis";
import type { Status } from "@/lib/matchday/api";
import { axisTicks, clockLabel, teamName, teamShort } from "@/lib/matchday/match";
import { neutral } from "@/lib/matchday/neutral";
import type { SideIdx } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";
import { Card, KeyMessage, PanelState, TeamSeg, fx, sgn, useA, type Pillar } from "../analysis/common";
import HeatGrid from "../analysis/HeatGrid";
import PassingNetwork from "../analysis/PassingNetwork";
import RegainsGrid from "../analysis/RegainsGrid";

const ROWS: [keyof TacticalMetrics, (v: number) => string, number][] = [
  ["possession_pct", (v) => `${v.toFixed(1)}%`, 1],
  ["links_per_sample", (v) => v.toFixed(1), 1], ["lane_clearance_pct", (v) => `${v.toFixed(0)}%`, 0], ["triangles_per_sample", (v) => v.toFixed(1), 1],
  ["quads_per_sample", (v) => v.toFixed(1), 1], ["pentagons_per_sample", (v) => v.toFixed(1), 1], ["viable_triangles_per_sample", (v) => v.toFixed(2), 2],
  ["viable_quads_per_sample", (v) => v.toFixed(2), 2], ["best_motif_score_mean", (v) => v.toFixed(2), 2], ["width_in_possession_m", (v) => `${v.toFixed(1)} m`, 1],
  ["depth_in_possession_m", (v) => `${v.toFixed(1)} m`, 1], ["width_out_of_possession_m", (v) => `${v.toFixed(1)} m`, 1], ["depth_out_of_possession_m", (v) => `${v.toFixed(1)} m`, 1],
  ["regains", (v) => v.toFixed(0), 0],
];
const UNIT: Partial<Record<keyof TacticalMetrics, string>> = { possession_pct: "%", lane_clearance_pct: "%", width_in_possession_m: " m", depth_in_possession_m: " m", width_out_of_possession_m: " m", depth_out_of_possession_m: " m" };
const FORM_COLORS = ["#3987e5", "#d95926", "#199e70", "#9085e9", "#c98500", "#d55181", "#22a699", "#7d8aa6", "#e9475f", "#5b8c2a", "#b06ad9"];

function pick(done: TacticalWindowRef[], chosen: string | null, fromEnd: number) {
  return done.find((w) => w.window_id === chosen) ?? done[Math.max(0, done.length - fromEnd)];
}

export default function TacticalTab() {
  const { meta, lang, matchId, clock, view } = useMD();
  const A = useA();
  const t = clock.t;
  const clk = clockLabel(meta.periods, t);
  const [side, setSide] = useState<SideIdx>(view.fav);
  const [selA, setSelA] = useState<string | null>(null);
  const [selB, setSelB] = useState<string | null>(null);
  const { windows, timeline, formations } = useTacticalWindows(matchId);
  const team = side ? meta.away : meta.home;
  const color = teamVar(side);
  const wins = windows.data?.windows ?? [];
  const done = wins.filter((w) => w.available && w.end_ms <= t);
  const winA = pick(done, selA, 2);
  const winB = pick(done, selB, 1);
  const a = useTacticalWindow(matchId, team.team_id, winA, t);
  const b = useTacticalWindow(matchId, team.team_id, winB, t);
  const current = wins.find((w) => w.in_progress && w.start_ms <= t);
  const tl = (timeline.data?.windows ?? []).filter((r) => r.end_ms <= t);
  const segs = (formations.data?.segments ?? []).filter((s) => s.start_ms <= t);
  const sws = (formations.data?.switches ?? []).filter((s) => s.at_ms <= t);

  const story = useMemo(() => {
    const rows = tl.filter((r) => r.team_id === team.team_id);
    const last = rows[rows.length - 1];
    const tsegs = segs.filter((x) => x.team_id === team.team_id);
    const seg = tsegs[tsegs.length - 1];
    const tsw = sws.filter((x) => x.team_id === team.team_id);
    const lastSw = tsw[tsw.length - 1];
    const shape = seg?.formation ?? last?.formation ?? last?.declared_formation ?? null;
    const poss = last?.possession_pct ?? null;
    const name = teamName(team, lang);
    const pillars: Pillar[] = [
      { title: A.pShape, tone: side, value: shape ?? "—",
        detail: lastSw ? A.switched(lastSw.from_formation, lastSw.to_formation, clockLabel(meta.periods, lastSw.at_ms)) : A.declaredNoChange(last?.declared_formation ?? "—") },
      { title: A.pBall(last?.label ?? A.lastWindow), tone: poss == null || Math.abs(poss - 50) < 4 || poss < 50 ? null : side,
        value: poss == null ? "—" : A.possN(poss.toFixed(0)),
        detail: A.ourPoss },
      { title: A.pSpacing, tone: null,
        value: last?.width_in_possession_m != null ? A.wide(last.width_in_possession_m.toFixed(0)) : "—",
        detail: last?.depth_in_possession_m != null ? A.deep(last.depth_in_possession_m.toFixed(0)) : A.needsTracking },
    ];
    return {
      headline: shape ? A.inShape(name, shape, poss != null ? poss.toFixed(0) : null) : A.waitingWindow(name),
      sub: lastSw ? A.lastChange(clockLabel(meta.periods, lastSw.at_ms)) : A.compareBelow,
      pillars,
    };
  }, [tl, segs, sws, team, side, lang, meta.periods, A]);

  const firstLabel = wins[0]?.label ?? "0–15′";
  return (
    <div className="col">
      <KeyMessage label={A.tacKicker} kicker={A.answer(clk, teamName(team, lang))} headline={story.headline} sub={story.sub} pillars={story.pillars}>
        <div className="an-row">
          <TeamSeg value={side} onChange={setSide} />
          <span className="chip an-live">{A.liveAt(clk)}</span>
          <span className="an-small">{A.windowsOpen}</span>
        </div>
      </KeyMessage>

      <section className="card" aria-label={A.windows}>
        <div className="card-b">
          {windows.status !== "ready" && !wins.length ? <PanelState status={windows.status} /> : (
            <>
              {(["A", "B"] as const).map((slot) => {
                const sel = slot === "A" ? winA : winB;
                const set = slot === "A" ? setSelA : setSelB;
                return (
                  <div key={slot} className="an-winpick">
                    <span className="tag">{A.slot(slot)}</span>
                    <div className="ovbar" role="radiogroup" aria-label={A.slot(slot)}>
                      {wins.map((w) => {
                        const ready = w.available && w.end_ms <= t;
                        const on = sel?.window_id === w.window_id;
                        return (
                          <button key={w.window_id} className={`ovbtn ${on ? "on" : ""} ${w.in_progress ? "an-cur" : ""}`} role="radio" aria-checked={on} disabled={!ready}
                            title={w.in_progress ? A.inProgressTitle : undefined} onClick={() => set(w.window_id)}>
                            {w.label}{w.in_progress ? " ●" : ""}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
              <div className="an-mono-note">{current ? A.inProgressLine(current.label) : done.length ? A.allComplete : ""}</div>
            </>
          )}
        </div>
      </section>

      {windows.status === "ready" && !done.length ? (
        <div className="note notrack" role="status"><b>{A.noWindowYet}</b><span>{A.firstWindow(firstLabel)}</span></div>
      ) : done.length > 0 && (
        <>
          <div className="grid-charts">
            <WindowBoard slot="A" label={winA?.label ?? "—"} data={a.data} status={a.status} color={color} />
            <WindowBoard slot="B" label={winB?.label ?? "—"} data={b.data} status={b.status} color={color} />
          </div>
          <Comparison a={a.data} b={b.data} labelA={winA?.label} labelB={winB?.label} />
        </>
      )}

      <Card title={A.timeline} tag={A.timelineNote}>
        {timeline.status !== "ready" && !tl.length ? <PanelState status={timeline.status} /> : !tl.length ? <p className="dim">{A.noCompleted}</p> : (
          <div className="scroll-x">
            <table className="ptable">
              <thead>
                <tr>
                  <th scope="col">{A.windowCol}</th>
                  {([0, 1] as const).map((s) => (
                    <th key={s} scope="colgroup" colSpan={3} style={{ color: teamVar(s) }}>{teamShort(s ? meta.away : meta.home, lang)}</th>
                  ))}
                </tr>
                <tr>
                  <th scope="col" />
                  {([0, 1] as const).flatMap((s) => [
                    <th key={`${s}f`} scope="col">{A.shapeDeclared}</th>, <th key={`${s}p`} scope="col">{A.possCol}</th>, <th key={`${s}w`} scope="col">{A.wxd}</th>,
                  ])}
                </tr>
              </thead>
              <tbody>
                {done.map((w) => (
                  <tr key={w.window_id}>
                    <th scope="row" className="mono" style={{ fontWeight: 600 }}>{w.label}</th>
                    {([0, 1] as const).flatMap((s) => {
                      const tid = (s ? meta.away : meta.home).team_id;
                      const r = tl.find((x) => x.window_id === w.window_id && x.team_id === tid);
                      const diff = r?.formation && r.declared_formation && r.formation !== r.declared_formation;
                      return [
                        <td key={`${s}f`} className="mono"><b style={{ color: diff ? "var(--accent-text)" : undefined }}>{r?.formation ?? "—"}</b> <span className="mute">/ {r?.declared_formation ?? "—"}</span></td>,
                        <td key={`${s}p`} className="mono">{fx(r?.possession_pct, 0, "%")}</td>,
                        <td key={`${s}w`} className="mono">{r?.width_in_possession_m != null && r.depth_in_possession_m != null ? `${r.width_in_possession_m.toFixed(0)} × ${r.depth_in_possession_m.toFixed(0)} m` : "—"}</td>,
                      ];
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Switches segs={segs} switches={sws} method={formations.data?.method ?? ""} status={formations.status} t={t} />

      {a.data && Object.keys(a.data.definitions ?? {}).length > 0 && (
        <Card title={A.definitions}>
          <div className="defs">
            {Object.entries(a.data.definitions).map(([k, v]) => (
              <div key={k} className="def"><b>{k.replace(/_/g, " ")}</b><span className="dim" style={{ fontSize: 13 }}>{neutral(v)}</span></div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function WindowBoard({ slot, label, data, status, color }: { slot: string; label: string; data: TacticalWindow | null; status: Status; color: string }) {
  const A = useA();
  const m = data?.metrics;
  const det = m?.formation ?? null, dec = m?.declared_formation ?? null;
  const total = data ? data.network.edges.reduce((s, e) => s + e.passes, 0) : 0;
  const regains = data ? data.regains.reduce((s, r) => s + r.regains, 0) : 0;
  return (
    <Card title={`${A.slot(slot)} · ${label}`}>
      {!data ? <PanelState status={status} /> : (
        <>
          <div className="an-vs">
            <div className="tile hl"><div className="k">{A.detected}</div><div className="v">{det ?? "—"}</div><div className="s">{A.detectedHint}</div></div>
            <div className="mid" aria-hidden="true">vs</div>
            <div className="tile"><div className="k">{A.declared}</div><div className="v">{dec ?? "—"}</div><div className="s">{A.declaredHint}</div></div>
          </div>
          {det && dec && <div className={`an-vs-note ${det !== dec ? "diff" : "same"}`}>{det !== dec ? A.shapeDiffers : A.shapeMatches}</div>}
          <div className="an-mini">
            <div className="an-cap">{A.network(total)}</div>
            <PassingNetwork data={data} color={color} />
          </div>
          <div className="an-minis">
            <div className="an-mini"><div className="an-cap">{A.heat}</div><HeatGrid data={data} color={color} /></div>
            <div className="an-mini"><div className="an-cap">{A.regainsN(regains)}</div><RegainsGrid data={data} /></div>
          </div>
          <div className="an-mono-note">{A.attacksLR}</div>
        </>
      )}
    </Card>
  );
}

function Comparison({ a, b, labelA, labelB }: { a: TacticalWindow | null; b: TacticalWindow | null; labelA?: string; labelB?: string }) {
  const A = useA();
  return (
    <Card title={A.comparison}>
      <div className="scroll-x">
        <table className="ptable an-num">
          <thead><tr>
            <th scope="col">{A.metric}</th><th scope="col" className="n">A · {labelA ?? "—"}</th><th scope="col" className="n">B · {labelB ?? "—"}</th><th scope="col" className="n">B − A</th>
          </tr></thead>
          <tbody>
            {ROWS.map(([k, fmt, d]) => {
              const va = a?.metrics[k] as number | null | undefined;
              const vb = b?.metrics[k] as number | null | undefined;
              const dv = va != null && vb != null ? vb - va : null;
              const cls = dv == null || Math.abs(dv) < 1e-9 ? "flat" : dv > 0 ? "up" : "down";
              return (
                <tr key={k}>
                  <th scope="row" style={{ fontWeight: 500 }}>{A.rows[k] ?? k}</th>
                  <td className="n">{va != null ? fmt(va) : "—"}</td>
                  <td className="n">{vb != null ? fmt(vb) : "—"}</td>
                  <td className={`n an-delta ${cls}`}>{dv == null ? "—" : sgn(dv, d, UNIT[k] ?? "")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/** Smoothed formation timeline per team up to the clock, with confirmed switches. */
function Switches({ segs, switches, method, status, t }: { segs: FormationSegment[]; switches: { team_id: string; at_ms: number; from_formation: string; to_formation: string }[]; method: string; status: Status; t: number }) {
  const { meta, lang } = useMD();
  const A = useA();
  const dur = Math.max(1, meta.duration_ms);
  const colorOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of segs) if (s.formation && !m.has(s.formation)) m.set(s.formation, FORM_COLORS[m.size % FORM_COLORS.length]);
    return m;
  }, [segs]);
  const merged = ([0, 1] as const).map((s) => {
    const tid = (s ? meta.away : meta.home).team_id;
    const out: { from: number; to: number; f: string | null }[] = [];
    for (const g of segs.filter((x) => x.team_id === tid).sort((p, q) => p.start_ms - q.start_ms)) {
      const to = Math.min(g.end_ms, t);
      const last = out[out.length - 1];
      if (last && last.f === g.formation && g.start_ms - last.to < 90000) last.to = to;
      else out.push({ from: g.start_ms, to, f: g.formation });
    }
    return out;
  });
  const ticks = axisTicks(meta.periods, dur).filter((k) => k.t <= t);
  const pctX = (v: number) => `${(100 * v) / dur}%`;
  return (
    <Card title={A.switches} tag={neutral(method)}>
      {status !== "ready" && !segs.length ? <PanelState status={status} /> : (
        <>
          {segs.length > 0 && (
            <div className="an-tl">
              {([0, 1] as const).map((s) => (
                <div key={s} className="an-tl-row">
                  <span className="mono" style={{ color: teamVar(s), fontWeight: 700, fontSize: 12 }}>{teamShort(s ? meta.away : meta.home, lang)}</span>
                  <div className="an-tl-track" role="img" aria-label={`${teamName(s ? meta.away : meta.home, lang)}: ${merged[s].map((g) => `${clockLabel(meta.periods, g.from)} ${g.f ?? "—"}`).join(", ")}`}>
                    {merged[s].map((g, i) => (
                      <div key={i} className="an-tl-seg" title={`${clockLabel(meta.periods, g.from)}–${clockLabel(meta.periods, g.to)} · ${g.f ?? "—"}`}
                        style={{ left: pctX(g.from), width: pctX(Math.max(0, g.to - g.from)), background: g.f ? colorOf.get(g.f) : "var(--line2)" }}>
                        {g.to - g.from > dur * 0.06 ? g.f : ""}
                      </div>
                    ))}
                    {switches.filter((x) => x.team_id === (s ? meta.away : meta.home).team_id).map((x) => (
                      <span key={x.at_ms} className="an-tl-sw" style={{ left: pctX(x.at_ms) }} />
                    ))}
                  </div>
                </div>
              ))}
              <div className="an-tl-axis" aria-hidden="true">{ticks.map((k, i) => <span key={i} style={{ left: pctX(k.t) }}>{k.label}</span>)}</div>
              <div className="legend">{[...colorOf.entries()].map(([f, c]) => <span key={f}><i style={{ background: c }} />{f}</span>)}</div>
            </div>
          )}
          {switches.length === 0 ? <p className="dim">{A.noSwitch}</p> : (
            <div>
              {switches.map((s) => {
                const sd: SideIdx = s.team_id === meta.away.team_id ? 1 : 0;
                return (
                  <div key={`${s.team_id}-${s.at_ms}`} className="an-switch">
                    <span className="mono mute">{clockLabel(meta.periods, s.at_ms)}</span>
                    <span style={{ fontWeight: 700, color: teamVar(sd), overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{teamName(sd ? meta.away : meta.home, lang)}</span>
                    <span className="mono">{s.from_formation} → <b>{s.to_formation}</b></span>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </Card>
  );
}
