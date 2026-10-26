"use client";

// Coach tab: subs, form, best player per situation and physical load, bounded by the replay clock
// (30 s buckets, physical 5 s).

import { useEffect, useState } from "react";
import { anApi, takePendingCoach, useBucketed, usePhysical, type CoachSection, type PlayerRow, type Situation, type SubOption, type SubsResp } from "@/lib/matchday/analysis";
import type { Polled } from "@/lib/matchday/analysis";
import { askAI, focusPlayer, onHandoff, takePendingSection } from "@/lib/matchday/handoff";
import { clockLabel, teamName, teamShort } from "@/lib/matchday/match";
import { neutral } from "@/lib/matchday/neutral";
import type { SideIdx } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";
import { Card, PanelState, TeamSeg, fx, useA, useNames } from "../analysis/common";

const SECTIONS: CoachSection[] = ["subs", "form", "best", "physical"];
const SITUATIONS: Situation[] = ["penalty", "corner", "free_kick", "counter", "defend"];
const isSection = (s: string | null | undefined): s is CoachSection => !!s && (SECTIONS as string[]).includes(s);

export default function CoachTab() {
  const { U, meta, lang, matchId, clock, view } = useMD();
  const A = useA();
  const [side, setSide] = useState<SideIdx>(view.fav);
  const [section, setSection] = useState<CoachSection>("subs");
  const [situation, setSituation] = useState<Situation>("penalty");
  const [openPlayer, setOpenPlayer] = useState<string | null>(null);

  // handoffs: pending values from before mount, then live events
  useEffect(() => {
    const s = takePendingSection();
    if (isSection(s)) setSection(s);
    const c = takePendingCoach();
    if (c?.teamSide != null) setSide(c.teamSide);
    if (c?.playerId) setOpenPlayer(c.playerId);
    return onHandoff((h) => {
      if (h.type === "coach") {
        setSection(h.section);
        if (h.teamSide != null) setSide(h.teamSide);
        if (h.playerId) setOpenPlayer(h.playerId);
        takePendingSection();
        takePendingCoach();
      } else if (h.type === "tab" && h.tab === "coach" && isSection(h.section)) {
        setSection(h.section);
        takePendingSection();
      }
    });
  }, []);

  const t = clock.t;
  const clk = clockLabel(meta.periods, t);
  const tid = (side ? meta.away : meta.home).team_id;
  const subsOn = section === "subs";
  const subsH = useBucketed<SubsResp>(subsOn ? `sub|${matchId}|${meta.home.team_id}` : null, (at) => anApi.subs(matchId, at, meta.home.team_id), { step: 30000 });
  const subsA = useBucketed<SubsResp>(subsOn ? `sub|${matchId}|${meta.away.team_id}` : null, (at) => anApi.subs(matchId, at, meta.away.team_id), { step: 30000 });
  const form = useBucketed(section === "form" ? `frm|${matchId}|${tid}` : null, (at) => anApi.players(matchId, at, tid), { step: 30000 });
  const best = useBucketed(section === "best" ? `bst|${matchId}|${tid}|${situation}` : null, (at) => anApi.best(matchId, at, tid, situation), { step: 30000 });
  const phys = usePhysical(matchId, section === "physical");
  const subs = side ? subsA : subsH;
  const tName = teamName(side ? meta.away : meta.home, lang);

  return (
    <div className="col">
      <div className="hero">
        <div className="kicker">{U.tabs.coach} · {clk}</div>
        <h2>{A.coachTitle}</h2>
        <p>{A.coachSub}</p>
      </div>
      <div className="an-row">
        <TeamSeg value={side} onChange={setSide} />
        <div className="seg" role="tablist" aria-label={A.section}>
          {SECTIONS.map((k) => (
            <button key={k} role="tab" aria-selected={section === k} className={section === k ? "on" : ""} onClick={() => setSection(k)}>{A.sections[k]}</button>
          ))}
        </div>
      </div>

      {section === "subs" && (
        <>
          <Card title={A.subsTitle(clk)} tag={subs.data ? A.changesLeft(subs.data.remaining, subs.data.made + subs.data.remaining, tName, A.contexts[subs.data.context] ?? subs.data.context) : undefined}>
            {!subs.data ? <PanelState status={subs.status} /> : !subs.data.options.length ? (
              <div className="note" role="status">{neutral(subs.data.note) || A.noChange(tName)}</div>
            ) : (
              <div className="col" style={{ gap: 10 }}>
                {subs.data.options.map((o, i) => <SubCard key={i} o={o} n={i + 1} team={tName} />)}
              </div>
            )}
          </Card>
          <Card title={A.bothTeams} tag={A.subsNote}>
            <div className="grid-2">
              {([0, 1] as const).map((s) => <SubsCompact key={s} side={s} r={s ? subsA : subsH} />)}
            </div>
          </Card>
        </>
      )}

      {section === "form" && (
        <Card title={A.formTitle(clk)} tag={A.formNote}>
          {!form.data ? <PanelState status={form.status} /> : (() => {
            const rows = form.data.teams[tid] ?? [];
            const on = rows.filter((p) => p.on_pitch).sort((a, b) => b.impact_per15 - a.impact_per15);
            const off = rows.filter((p) => !p.on_pitch);
            return (
              <>
                <div className="an-mono-note">{A.onPitchN(on.length)} · {A.impact}</div>
                {!on.length ? <p className="dim">{U.unavailable}</p> : (
                  <div className="col" style={{ gap: 6 }}>
                    {on.map((p) => <PlayerLine key={p.player_id} p={p} side={side} team={tName} open={openPlayer === p.player_id} onToggle={() => setOpenPlayer(openPlayer === p.player_id ? null : p.player_id)} />)}
                  </div>
                )}
                {off.length > 0 && (
                  <details className="an-det">
                    <summary>{A.bench} ({off.length})</summary>
                    {off.map((p) => <BenchLine key={p.player_id} p={p} />)}
                  </details>
                )}
              </>
            );
          })()}
        </Card>
      )}

      {section === "best" && (
        <Card title={A.bestTitle} tag={tName}>
          <div className="ovbar" role="radiogroup" aria-label={A.bestTitle}>
            {SITUATIONS.map((k) => (
              <button key={k} className={`ovbtn ${situation === k ? "on" : ""}`} role="radio" aria-checked={situation === k} onClick={() => setSituation(k)}>{A.situations[k]}</button>
            ))}
          </div>
          {!best.data ? <PanelState status={best.status} /> : (
            <>
              <div className="col" style={{ gap: 6 }}>
                {best.data.ranked.map((r, i) => <BestLine key={r.player_id} r={r} i={i} side={side} />)}
                {!best.data.ranked.length && <p className="dim">{U.unavailable}</p>}
              </div>
              <div className="an-row">
                <button className="btn ghost an-sm" onClick={() => askAI(A.qBest(tName, A.situationQ[situation] ?? situation))}>{A.askAI}</button>
                <span className="an-mono-note an-grow">{A.basis(neutral(best.data.basis))}</span>
              </div>
            </>
          )}
        </Card>
      )}

      {section === "physical" && <Physical r={phys} clk={clk} />}
    </div>
  );
}

function Reasons({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="an-reasons">
      <span className="tag">{title}</span>
      <ul>{items.map((w, i) => <li key={i}>▸ {neutral(w)}</li>)}</ul>
    </div>
  );
}

function SubCard({ o, n, team }: { o: SubOption; n: number; team: string }) {
  const A = useA();
  const { pName } = useNames();
  const off = pName(o.off.player_id, o.off.name);
  const on = o.on ? pName(o.on.player_id, o.on.name) : null;
  return (
    <div className="an-sub">
      <div className="an-row">
        <span className={`an-urg ${o.urgency}`}>{A.urgency[o.urgency] ?? o.urgency}</span>
        <span className="an-mono-note">{A.optionN(n)}</span>
        {o.off.flags.map((f) => <span key={f} className={`an-flag ${f}`}>{A.flags[f] ?? f}</span>)}
      </div>
      <div className="an-swap">
        <button className="pl off" onClick={() => focusPlayer(o.off.player_id, "player")} aria-label={`▼ ${off}`}>
          <span>▼ {off}</span><small>{A.offLine(o.off.role, o.off.minutes.toFixed(0))}</small>
        </button>
        <span className="mute" aria-hidden="true">→</span>
        {o.on && on ? (
          <button className="pl in" onClick={() => focusPlayer(o.on!.player_id, "player")} aria-label={`▲ ${on}`}>
            <span>▲ {on}</span><small>{o.on.role}</small>
          </button>
        ) : <span className="dim" style={{ fontSize: 12 }}>{A.noReplacement}</span>}
      </div>
      <Reasons title={A.whyOff} items={o.why_off} />
      <Reasons title={A.whyOn} items={o.why_on} />
      <button className="btn ghost an-sm" style={{ alignSelf: "flex-start" }} onClick={() => askAI(A.qSub(team, off, on))}>{A.askWeigh}</button>
    </div>
  );
}

function SubsCompact({ side, r }: { side: SideIdx; r: Polled<SubsResp> }) {
  const { meta, lang } = useMD();
  const A = useA();
  const { pName } = useNames();
  const tm = side ? meta.away : meta.home;
  const d = r.data;
  return (
    <div className="an-team-block" style={{ borderLeftColor: teamVar(side) }}>
      <div className="an-sec-h">
        <b style={{ color: teamVar(side), fontFamily: "var(--display)", fontSize: 18, textTransform: "uppercase" }}>{teamName(tm, lang)}</b>
        {d && <span className="an-mono-note">{A.changesLeft(d.remaining, d.made + d.remaining, teamShort(tm, lang), A.contexts[d.context] ?? d.context)}</span>}
      </div>
      {!d ? <PanelState status={r.status} /> : !d.options.length ? <p className="an-small">{neutral(d.note) || A.noChange(teamName(tm, lang))}</p> : (
        d.options.slice(0, 2).map((o, i) => {
          const off = pName(o.off.player_id, o.off.name);
          const on = o.on ? pName(o.on.player_id, o.on.name) : null;
          return (
            <div key={i} className="col" style={{ gap: 4 }}>
              <div className="an-row" style={{ fontSize: 13.5 }}>
                <span className={`an-urg ${o.urgency}`}>{A.urgency[o.urgency] ?? o.urgency}</span>
                <button className="an-link" style={{ color: "#e5576c", fontSize: 13.5 }} onClick={() => focusPlayer(o.off.player_id, "player")}>▼ {off}</button>
                <span className="mute">→</span>
                {o.on && on ? <button className="an-link" style={{ color: "var(--good)", fontSize: 13.5 }} onClick={() => focusPlayer(o.on!.player_id, "player")}>▲ {on}</button> : <span className="dim" style={{ fontSize: 12 }}>{A.noReplacement}</span>}
              </div>
              {o.why_off[0] && <span className="an-small">▸ {neutral(o.why_off[0])}</span>}
              <button className="an-link" style={{ alignSelf: "flex-start" }} onClick={() => askAI(A.qSub(teamName(tm, lang), off, on))}>{A.askWeigh}</button>
            </div>
          );
        })
      )}
    </div>
  );
}

function PlayerLine({ p, side, team, open, onToggle }: { p: PlayerRow; side: SideIdx; team: string; open: boolean; onToggle: () => void }) {
  const A = useA();
  const { pName } = useNames();
  const name = pName(p.player_id, p.name);
  const trend = p.recent_per15 != null && p.earlier_per15 != null ? p.recent_per15 - p.earlier_per15 : null;
  const tcls = trend == null ? "flat" : trend < -0.3 ? "down" : trend > 0.3 ? "up" : "flat";
  const width = Math.max(4, Math.min(100, 30 * Math.max(0, p.impact_per15)));
  const s = p.stats;
  const ph = p.physical;
  return (
    <div className={`an-pform ${open ? "on" : ""}`}>
      <button className="an-pform-h" aria-expanded={open} onClick={onToggle}>
        <span className="nm">{name}<small>{p.jersey != null ? `#${p.jersey} · ` : ""}{p.role}</small></span>
        <span className="an-bar fwd" aria-hidden="true"><span style={{ width: `${width}%`, background: teamVar(side) }} /></span>
        <span className="mono" style={{ textAlign: "right", fontWeight: 700 }}>{p.impact_per15.toFixed(1)}</span>
        <span className={`mono an-trend ${tcls}`} aria-label={tcls === "down" ? A.trendDown : tcls === "up" ? A.trendUp : A.trendFlat}>{trend == null ? "·" : tcls === "down" ? "↓" : tcls === "up" ? "↑" : "→"}</span>
      </button>
      {p.flags.length > 0 && (
        <div className="an-row" style={{ padding: "0 10px 8px" }}>{p.flags.map((f) => <span key={f} className={`an-flag ${f}`}>{A.flags[f] ?? f}</span>)}</div>
      )}
      {open && (
        <div className="an-pform-b">
          {p.reasons.length > 0 && <ul className="an-reasons" style={{ margin: 0, padding: 0 }}>{p.reasons.map((r, i) => <li key={i}>▸ {neutral(r)}</li>)}</ul>}
          <div className="an-statgrid">
            <span>{A.st.g} {s.goals ?? 0} · {A.st.sh} {s.shots ?? 0}</span><span>{A.st.xg} {fx(s.xg ?? 0, 2)}</span><span>{A.st.pass} {fx(s.pass_pct, 0, "%")}</span>
            <span>{A.st.def} {s.def_actions ?? 0}</span><span>{A.st.lost} {s.losses ?? 0}</span><span>{A.st.xt} {fx(s.xt_added, 2)}</span>
          </div>
          {ph && (
            <div className="an-mono-note">
              {A.physLine(fx(ph.distance_km, 1), fx(ph.top_speed_kmh, 1))}
              {ph.recent_hsr_m != null && ` · ${A.hsrLine(String(ph.recent_hsr_m), String(ph.usual_hsr_m ?? "—"))}`}
            </div>
          )}
          {p.history?.matches ? <div className="an-mono-note">{A.beforeToday(p.history.matches ?? 0, p.history.goals ?? 0, fx(p.history.xg ?? 0, 1))}</div> : null}
          <span className="an-mono-note">{A.roleSrc(neutral(p.role_source))}</span>
          <div className="an-row">
            <button className="btn ghost an-sm" onClick={() => askAI(A.qForm(name, team))}>{A.askAbout(name)}</button>
            <button className="an-link" onClick={() => focusPlayer(p.player_id, "player")}>{name} →</button>
          </div>
        </div>
      )}
    </div>
  );
}

function BenchLine({ p }: { p: PlayerRow }) {
  const A = useA();
  const { pName } = useNames();
  return (
    <div className="an-bench">
      <button className="an-link" style={{ textAlign: "left", color: "var(--ink)", textDecoration: "none", fontSize: 12.5 }} onClick={() => focusPlayer(p.player_id, "player")}>{pName(p.player_id, p.name)}</button>
      <span className="mono mute">{p.role}</span>
      <span className="mono mute">{p.minutes > 0 ? A.playedMin(p.minutes.toFixed(0)) : p.history?.matches ? A.apps(p.history.matches ?? 0, p.history.goals ?? 0, fx(p.history.xg ?? 0, 1)) : A.noMinutes}</span>
    </div>
  );
}

function BestLine({ r, i, side }: { r: { player_id: string; name: string; jersey: number | null; role: string; why: string[] }; i: number; side: SideIdx }) {
  const A = useA();
  const { pName } = useNames();
  return (
    <button className="an-best" onClick={() => focusPlayer(r.player_id, "player")}>
      <span className="rk" style={i === 0 ? { background: teamVar(side), color: "#fff" } : undefined}>{i + 1}</span>
      <span style={{ minWidth: 0 }}>
        <b>{pName(r.player_id, r.name)}</b> <small className="mono" style={{ display: "inline" }}>{r.role}{r.jersey != null ? ` · #${r.jersey}` : ""}</small>
        {(r.why.length ? r.why.map(neutral) : [A.noRecord]).map((w, k) => <small key={k}>{w}</small>)}
      </span>
    </button>
  );
}

function Physical({ r, clk }: { r: ReturnType<typeof usePhysical>; clk: string }) {
  const { meta, lang } = useMD();
  const A = useA();
  const { pName } = useNames();
  const d = r.data;
  const rows = (d?.players ?? []).slice().sort((a, b) => Number(b.on_pitch) - Number(a.on_pitch) || b.distance_km - a.distance_km);
  const total = (s: "home" | "away") => rows.filter((x) => x.side === s).reduce((acc, x) => acc + x.distance_km, 0);
  const th = total("home"), ta = total("away");
  return (
    <Card title={A.physTitle} tag={A.cumulative(clk)}>
      {!d ? <PanelState status={r.status} /> : !rows.length ? <PanelState status="ready" empty={A.noPhysical} /> : (
        <>
          <div className="col" style={{ gap: 6 }}>
            <div className="an-sec-h">
              <span className="mono" style={{ color: teamVar(0), fontWeight: 700 }}>{teamShort(meta.home, lang)} {th.toFixed(1)} km</span>
              <span className="tag">{A.teamDistance}</span>
              <span className="mono" style={{ color: teamVar(1), fontWeight: 700 }}>{ta.toFixed(1)} km {teamShort(meta.away, lang)}</span>
            </div>
            <div className="an-split" role="img" aria-label={`${A.teamDistance}: ${teamShort(meta.home, lang)} ${th.toFixed(1)} km, ${teamShort(meta.away, lang)} ${ta.toFixed(1)} km`}>
              <div style={{ flexGrow: Math.max(0.02, th), background: teamVar(0) }} /><div style={{ flexGrow: Math.max(0.02, ta), background: teamVar(1) }} />
            </div>
          </div>
          <div className="scroll-x" style={{ maxHeight: 560, overflowY: "auto" }}>
            <table className="ptable an-num">
              <thead><tr>
                <th scope="col">{A.ph.player}</th><th scope="col" className="n">{A.ph.km}</th><th scope="col" className="n">{A.ph.hsr}</th><th scope="col" className="n">{A.ph.spr}</th><th scope="col" className="n">{A.ph.top}</th>
              </tr></thead>
              <tbody>
                {rows.map((x) => {
                  const s: SideIdx = x.side === "away" ? 1 : 0;
                  return (
                    <tr key={`${x.team_id}-${x.jersey}`} className={x.on_pitch ? "" : "an-faded"}>
                      <th scope="row" style={{ fontWeight: 500, whiteSpace: "nowrap" }}>
                        <span className="mono" style={{ color: teamVar(s), fontWeight: 700 }}>{teamShort(s ? meta.away : meta.home, lang)} {x.jersey}</span> {pName(x.player_id, x.name)}
                      </th>
                      <td className="n">{x.distance_km.toFixed(2)}</td><td className="n">{x.hsr_km.toFixed(2)}</td><td className="n">{x.sprint_km.toFixed(2)}</td><td className="n">{x.top_speed_kmh.toFixed(1)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="an-small">{A.physNote(fx(d.hsr_threshold_mps ?? 5.5, 1), fx(d.sprint_threshold_mps ?? 7, 1))}</p>
        </>
      )}
    </Card>
  );
}
