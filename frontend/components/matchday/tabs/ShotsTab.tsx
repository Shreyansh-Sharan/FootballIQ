"use client";

// Shots tab: shot maps, team table, shot detail and ball flight, up to the replay clock.

import { useEffect, useMemo, useRef, useState } from "react";
import { anApi, useBucketed, type ShotRow, type ShotTeam } from "@/lib/matchday/analysis";
import { focusPlayer, openTab, watchAt } from "@/lib/matchday/handoff";
import { clockLabel, teamName, teamShort } from "@/lib/matchday/match";
import type { SideIdx } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";
import { Card, Kv, PanelState, fx, modelLabel, sgn, useA, useNames } from "../analysis/common";
import FlightCard from "../analysis/FlightCard";
import ShotMap, { xgOf } from "../analysis/ShotMap";

const OUTCOME_COLOR: Record<string, string> = {
  Goal: "var(--good)", Saved: "var(--control)", "Saved To Post": "var(--control)", "Off T": "var(--mute)", Wayward: "var(--mute)",
  Post: "#c9a200", Blocked: "#e5576c", "Saved Off T": "var(--mute)",
};

export default function ShotsTab() {
  const { U, meta, lang, matchId, clock, events } = useMD();
  const A = useA();
  const { pName, sideOf } = useNames();
  const t = clock.t;
  // at_ms = newest shot so far, so /shots refetches only when a new shot is reached
  const lastShotAt = useMemo(() => {
    let best = 0;
    for (const e of events.data) if (e.type === "Shot" && !e.is_shootout && e.match_elapsed_ms <= t && e.match_elapsed_ms > best) best = e.match_elapsed_ms;
    return best;
  }, [events.data, t]);
  const eventsOk = events.status === "ready";
  const atRef = useRef({ lastShotAt, eventsOk });
  atRef.current = { lastShotAt, eventsOk };
  const shots = useBucketed(`sh|${matchId}`, (at) => anApi.shots(matchId, at),
    { atOf: (tt) => (atRef.current.eventsOk ? atRef.current.lastShotAt : Math.floor(tt / 30000) * 30000) });
  const data = shots.data;
  const list = useMemo(() => (data?.shots ?? []).filter((s) => s.match_elapsed_ms <= t).sort((a, b) => b.match_elapsed_ms - a.match_elapsed_ms), [data, t]);
  const [sel, setSel] = useState<string | null>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());
  const pickFromMap = (s: ShotRow) => {
    setSel(s.event_id);
    requestAnimationFrame(() => rowRefs.current.get(s.event_id)?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  };
  useEffect(() => { if (sel && !list.some((s) => s.event_id === sel)) setSel(null); }, [list, sel]);

  const teamRows: [string, (s: ShotTeam) => string][] = [
    [A.shotRows.shots, (s) => `${s.shots} (${s.on_target})`],
    [A.shotRows.accuracy, (s) => fx(s.accuracy_pct, 0, "%")],
    [A.shotRows.xgps, (s) => fx(s.xg_per_shot, 2)],
    [A.shotRows.big, (s) => String(s.big_chances)],
    [A.shotRows.dist, (s) => fx(s.avg_distance_m, 1, " m")],
    [A.shotRows.angle, (s) => fx(s.avg_angle_deg, 1, "°")],
    [A.shotRows.box, (s) => `${(s.zones["six-yard box"] ?? 0) + (s.zones["penalty area"] ?? 0)} / ${s.shots}`],
    [A.shotRows.pressure, (s) => fx(s.under_pressure_pct, 0, "%")],
    [A.shotRows.finishing, (s) => sgn(s.goals_minus_xg, 2)],
  ];
  const xgNote = !list.length ? "" : list.every((x) => xgOf(x) == null) ? A.xgNone : data?.model_version ? A.xgOurs(modelLabel(data.model_version)) : "";
  const outcome = (s: ShotRow) => A.outcomes[s.outcome ?? ""] ?? s.outcome ?? A.shotWord;
  const flightSummary = (s: ShotRow) => {
    const f = s.flight;
    if (!f?.available) return null;
    const curve = f.curve_measurable ? (f.bend === "straight" ? A.straight : A.curls(A.dirs[f.bend ?? ""] ?? f.bend ?? "", Math.abs(f.curve_deg ?? 0).toFixed(0))) : A.curveNA;
    return `${curve}${f.speed_kmh ? ` · ${f.estimated ? "~" : ""}${f.speed_kmh.toFixed(0)} km/h` : ""}`;
  };

  return (
    <div className="col">
      <div className="hero">
        <div className="kicker">{U.tabs.shots} · {clockLabel(meta.periods, t)}</div>
        <h2>{A.shotsTitle}</h2>
        <p>{A.shotsSub}</p>
      </div>

      {!data ? <PanelState status={shots.status} /> : (
        <>
          <div className="grid-2">
            {([0, 1] as const).map((s) => {
              const tm = s ? meta.away : meta.home;
              const mine = list.filter((x) => sideOf(x.team_id) === s);
              return (
                <Card key={s} title={<span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><span className="an-dot" style={{ background: teamVar(s) }} />{teamName(tm, lang)}</span>}
                  tag={`${A.shotMap} · ${A.shotsN(mine.length)}`}>
                  <ShotMap shots={mine} color={teamVar(s)} selected={sel} onSelect={pickFromMap} label={`${A.shotMap} · ${teamName(tm, lang)}`} />
                  <div className="legend">
                    <span><i style={{ background: teamVar(s), borderRadius: "50%" }} />{A.legendGoal}</span>
                    <span><i style={{ border: `2px solid ${teamVar(s)}`, borderRadius: "50%", background: "transparent" }} />{A.legendOn}</span>
                    <span><i style={{ border: `2px dashed ${teamVar(s)}`, borderRadius: "50%", background: "transparent" }} />{A.legendOff}</span>
                    <span>{A.legendSize}</span>
                  </div>
                </Card>
              );
            })}
          </div>

          <div className="grid-live wide-side">
            <Card title={A.everyShot} tag={A.shotsN(list.length)}>
              {!list.length ? <p className="dim">{A.noShots}</p> : (
                <div className="an-shots">
                  {list.map((s) => {
                    const side = sideOf(s.team_id);
                    const open = sel === s.event_id;
                    const xg = xgOf(s);
                    const fs = flightSummary(s);
                    return (
                      <div key={s.event_id} ref={(el) => { if (el) rowRefs.current.set(s.event_id, el); else rowRefs.current.delete(s.event_id); }}
                        className={`an-shot ${open ? "on" : ""}`} style={{ borderLeftColor: teamVar(side) }}>
                        <button className="an-shot-h" aria-expanded={open} onClick={() => setSel(open ? null : s.event_id)}>
                          <span className="mono mute">{clockLabel(meta.periods, s.match_elapsed_ms)}</span>
                          <span className="nm">{pName(s.player_id, s.player_name)}{side != null && <small className="mute mono" style={{ marginLeft: 6, fontWeight: 400 }}>{teamShort(side ? meta.away : meta.home, lang)}</small>}</span>
                          <span className="an-badge" style={{ color: OUTCOME_COLOR[s.outcome ?? ""] ?? "var(--mute)" }}>{outcome(s)}</span>
                          <span className="mono" style={{ textAlign: "right", fontWeight: 700 }}>{xg != null ? xg.toFixed(2) : "—"}</span>
                        </button>
                        <div className="an-shot-meta">
                          <span>{s.distance_m.toFixed(0)} m</span><span>{s.angle_deg.toFixed(0)}° {A.angleSfx}</span><span>{s.zone}</span>
                          {s.difficulty && <span style={{ color: s.difficulty === "big chance" ? "var(--accent-text)" : undefined }}>{s.difficulty}</span>}
                          {s.type && s.type !== "Open Play" && <span>{s.type.toLowerCase()}</span>}
                          {fs && <span style={{ color: "var(--accent-text)" }}>{fs}</span>}
                        </div>
                        {open && <ShotDetail s={s} side={side} />}
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
            <Card title={A.teamTable}>
              <div className="scroll-x">
                <table className="ptable an-num">
                  <thead><tr>
                    <th scope="col"><span className="sr">{A.metric}</span></th>
                    {([0, 1] as const).map((s) => <th key={s} scope="col" className="n" style={{ color: teamVar(s) }}>{teamShort(s ? meta.away : meta.home, lang)}</th>)}
                  </tr></thead>
                  <tbody>
                    {teamRows.map(([label, fn]) => (
                      <tr key={label}>
                        <th scope="row" style={{ fontWeight: 500, color: "var(--dim)" }}>{label}</th>
                        {([0, 1] as const).map((s) => {
                          const v = data.teams[(s ? meta.away : meta.home).team_id];
                          return <td key={s} className="n">{v ? fn(v) : "—"}</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {xgNote && <p className="an-mono-note">{xgNote}</p>}
              <p className="an-small">{A.angleNote}</p>
              {!sel && list.length > 0 && <p className="an-small">{A.pick}</p>}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function ShotDetail({ s, side }: { s: ShotRow; side: SideIdx | null }) {
  const A = useA();
  const freeze = (v: string) => (s.has_360 ? v : A.kv.noFreeze);
  return (
    <div className="an-shot-d">
      <div className="col" style={{ gap: 10 }}>
        <div className="an-kv">
          <Kv k={A.kv.dist} v={fx(s.distance_m, 1, " m")} />
          <Kv k={A.kv.mouth} v={fx(s.angle_deg, 1, "°")} />
          <Kv k={A.kv.offCentre} v={fx(s.centrality_deg, 1, "°")} />
          <Kv k={A.kv.ourXg} v={s.xg == null ? A.kv.notScored : `${s.xg.toFixed(2)}${s.xg_lo != null && s.xg_hi != null ? ` (${s.xg_lo.toFixed(2)}–${s.xg_hi.toFixed(2)})` : ""}`} />
          <Kv k={A.kv.pressure} v={s.under_pressure ? A.yes : A.no} />
          <Kv k={A.kv.cone} v={freeze(String(s.defenders_in_cone ?? 0))} />
          <Kv k={A.kv.nearest} v={freeze(fx(s.nearest_defender_m, 1, " m"))} />
          <Kv k={A.kv.keeper} v={freeze(fx(s.keeper_off_line_m, 1, " m"))} />
          <Kv k={A.kv.placement} v={s.placement ?? (s.on_target ? "—" : A.kv.missed)} />
          <Kv k={A.kv.pattern} v={s.play_pattern ?? "—"} />
          <Kv k={A.kv.type} v={s.type ?? "—"} />
        </div>
        <button className="btn an-sm" style={{ alignSelf: "flex-start" }}
          onClick={() => { watchAt(s.match_elapsed_ms, 5000); if (s.player_id) focusPlayer(s.player_id, "live"); else openTab("live"); }}>
          ▶ {A.watchShot}
        </button>
      </div>
      <FlightCard shot={s} color={teamVar(side)} />
    </div>
  );
}
