"use client";

// Pre-match tab: form and head-to-head as of kick-off, Elo strength, starting XIs and the tournament
// profile (polled until ready).

import { useMemo } from "react";
import { anApi, useBucketed, useHistory, usePrematchProfile, type PrematchProfile, type TeamProfile } from "@/lib/matchday/analysis";
import { playerName, teamName, teamShort } from "@/lib/matchday/match";
import { neutral } from "@/lib/matchday/neutral";
import type { SideIdx } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";
import { Card, PanelState, fx, useA, useNames } from "../analysis/common";
import { FormList, FormStrip, FormSummary } from "../analysis/FormBadges";

const LINE_ORDER = { G: 0, D: 1, M: 2, F: 3 } as const;
function lineOf(pg: string | null | undefined): keyof typeof LINE_ORDER {
  const p = (pg ?? "").toUpperCase();
  if (p === "GK" || /GOAL/.test(p)) return "G";
  if (/CB|LB|RB|WB|DEF|BACK/.test(p)) return "D";
  if (/CF|ST|LW|RW|SS|ATT|FW|F$/.test(p)) return "F";
  return "M";
}
const ROLE_LINE = { GK: "G", DEF: "D", MID: "M", ATT: "F" } as const;

const METRICS: [string, (v: number) => string][] = [
  ["goals", (v) => v.toFixed(1)], ["xg", (v) => v.toFixed(2)], ["shots", (v) => v.toFixed(1)], ["corners", (v) => v.toFixed(1)],
  ["pass_pct", (v) => `${v.toFixed(0)}%`], ["pressures", (v) => v.toFixed(0)], ["def_actions", (v) => v.toFixed(0)],
];

interface XIRow { key: string; no: string; name: string; pos: string; line: keyof typeof LINE_ORDER }

export default function PreMatchTab() {
  const md = useMD();
  const { U, meta, lang, matchId, tracking, idxInfo } = md;
  const A = useA();
  const history = useHistory(matchId);
  const profile = usePrematchProfile(matchId);
  const pred = useBucketed(`pm|${matchId}`, (at) => anApi.predictions(matchId, at), { step: 15 * 60000 });
  const h = history.data;

  // ---- starting XIs: tracking roster, else the team sheet
  const xis = useMemo(() => {
    const out: [XIRow[], XIRow[]] = [[], []];
    let fromRoster = false;
    if (tracking.roster.length) {
      for (const r of tracking.roster) {
        if (!r.started) continue;
        const info = idxInfo.get(r.idx);
        const side: SideIdx = info?.side ?? (r.side === "away" ? 1 : 0);
        out[side].push({ key: `r${r.idx}`, no: r.jersey, name: info?.player ? playerName(info.player, lang) : r.name ?? "—", pos: r.position_group ?? "", line: lineOf(r.position_group) });
      }
      fromRoster = out[0].length + out[1].length > 0;
    }
    if (!fromRoster) {
      for (const p of meta.players) {
        if (!p.starter) continue;
        out[p.side === "away" ? 1 : 0].push({ key: p.player_id, no: p.number != null ? String(p.number) : "–", name: playerName(p, lang), pos: p.position ?? p.role, line: ROLE_LINE[p.role] ?? "M" });
      }
    }
    for (const xs of out) xs.sort((a, b) => LINE_ORDER[a.line] - LINE_ORDER[b.line] || (parseInt(a.no, 10) || 99) - (parseInt(b.no, 10) || 99));
    return { rows: out, fromRoster };
  }, [tracking.roster, idxInfo, meta.players, lang]);

  const strength = pred.data?.prematch;
  const formCard = (s: SideIdx) => {
    const tm = s ? meta.away : meta.home;
    const rows = h?.teams[tm.team_id]?.form ?? [];
    return (
      <Card title={<span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><span className="an-dot" style={{ background: teamVar(s) }} />{teamName(tm, lang)}</span>} tag={A.tourForm}>
        {!h ? <PanelState status={history.status} /> : (
          <>
            <FormStrip rows={rows} />
            <FormSummary s={h.teams[tm.team_id]?.summary} />
            <FormList rows={rows} empty={A.noEarlier} />
          </>
        )}
      </Card>
    );
  };
  return (
    <div className="col">
      <div className="hero">
        <div className="kicker">{U.tabs.prematch}</div>
        <h2>{A.pmTitle}</h2>
        <p>{A.pmSub}</p>
        <div className="an-row" style={{ marginTop: 4 }}>
          <span className="chip an-accent">{A.formAsOf}</span>
          {h && <span className="chip">{h.cutoff_date}</span>}
          {h && <span className="an-small">{neutral(h.cutoff_rule)}</span>}
        </div>
      </div>

      <div className="grid-3">
        {formCard(0)}
        <Card title={A.h2h} tag={`${teamShort(meta.home, lang)} ${A.vs} ${teamShort(meta.away, lang)}`}>
          <p className="an-small">{A.h2hSub}</p>
          {!h ? <PanelState status={history.status} /> : <FormList rows={h.head_to_head} empty={A.noH2H} />}
          {h?.coverage && <p className="an-small"><b>{A.coverage}:</b> {neutral(h.coverage)}</p>}
        </Card>
        {formCard(1)}
      </div>

      <div className="grid-2">
        <Card title={A.strength} tag={A.resultsBefore}>
          {!strength || !Object.keys(strength).length ? <PanelState status={pred.status === "ready" ? "missing" : pred.status} na={A.na503} /> : (
            <div className="stat-row" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 200px), 1fr))" }}>
              {([0, 1] as const).map((s) => {
                const tm = s ? meta.away : meta.home;
                const v = strength[tm.team_id];
                return (
                  <div key={s} className="tile" style={{ borderTop: `4px solid ${teamVar(s)}` }}>
                    <div className="k">{teamName(tm, lang)}</div>
                    <div className="v">{v?.elo_for != null ? Math.round(v.elo_for) : "—"}<small>{A.elo}</small></div>
                    <div className="s">{A.formLbl} {fx(v?.form_ppg_for, 1)} {A.formPpg}</div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
        <Card title={A.xis} tag={xis.fromRoster ? A.xisRoster : A.xisSheet}>
          {!xis.rows[0].length && !xis.rows[1].length ? <p className="dim">{A.noXI}</p> : (
            <div className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))", gap: 14 }}>
              {([0, 1] as const).map((s) => (
                <div key={s} className="an-xi">
                  <div className="tag" style={{ color: teamVar(s), marginBottom: 4 }}>{teamName(s ? meta.away : meta.home, lang)}</div>
                  {xis.rows[s].map((r) => (
                    <div key={r.key} className="an-xi-r">
                      <span className="no" style={{ background: teamVar(s) }}>{r.no}</span>
                      <span className="nm">{r.name}</span>
                      <span className="mono mute" style={{ fontSize: 11 }}>{r.pos}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title={A.profile} tag={profile.data?.status === "ready" && (profile.data.teams_in_reference ?? 0) > 0 ? A.profileFoot(meta.competition, profile.data.teams_in_reference ?? 0) : undefined}>
        <ProfileBars profile={profile.data} status={profile.status} />
      </Card>
      <Card title={A.keyPlayers}>
        <KeyPlayers profile={profile.data} status={profile.status} />
        <p className="an-small">{A.keyFoot}</p>
      </Card>
    </div>
  );

}

function profileReady(profile: PrematchProfile | null, status: ReturnType<typeof usePrematchProfile>["status"], A: ReturnType<typeof useA>) {
  if (!profile) return <PanelState status={status} />;
  if (profile.status === "failed") return <PanelState status="ready" empty={A.profileFailed} />;
  if (profile.status !== "ready") return <div className="note" role="status"><span className="spin" aria-hidden="true" /><span>{A.building(profile.status)}</span></div>;
  return null;
}

function ProfileBars({ profile, status }: { profile: PrematchProfile | null; status: ReturnType<typeof usePrematchProfile>["status"] }) {
  const { meta, lang } = useMD();
  const A = useA();
  const wait = profileReady(profile, status, A);
  if (wait || !profile) return wait;
  const H: TeamProfile | undefined = profile.teams[meta.home.team_id];
  const W: TeamProfile | undefined = profile.teams[meta.away.team_id];
  if (!H?.matches && !W?.matches) return <PanelState status="ready" empty={A.noProfile} />;
  const avg = profile.tournament_average ?? {};
  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="an-sec-h">
        <span className="tag" style={{ color: teamVar(0) }}>{teamName(meta.home, lang)} · {A.matchesN(H?.matches ?? 0)}</span>
        <span className="tag" style={{ color: teamVar(1) }}>{teamName(meta.away, lang)} · {A.matchesN(W?.matches ?? 0)}</span>
      </div>
      {METRICS.map(([k, fmt]) => {
        const hv = H?.for[k] ?? null, av = W?.for[k] ?? null, ref = avg[k] ?? null;
        const max = Math.max(hv ?? 0, av ?? 0, ref ?? 0, 1e-6) * 1.15;
        return (
          <div key={k} className="an-mirror" role="group" aria-label={`${A.pmMetrics[k]}: ${hv == null ? "—" : fmt(hv)} / ${av == null ? "—" : fmt(av)}${ref != null ? ` · ${A.tourAvg} ${fmt(ref)}` : ""}`}>
            <span className="mono" style={{ textAlign: "right", color: teamVar(0), fontWeight: 700 }}>{hv == null ? "—" : fmt(hv)}</span>
            <span className="an-bar rev"><span style={{ width: `${(100 * (hv ?? 0)) / max}%`, background: teamVar(0) }} />{ref != null && <i style={{ right: `${(100 * ref) / max}%` }} title={`${A.tourAvg} ${fmt(ref)}`} />}</span>
            <span className="lbl">{A.pmMetrics[k]}</span>
            <span className="an-bar fwd"><span style={{ width: `${(100 * (av ?? 0)) / max}%`, background: teamVar(1) }} />{ref != null && <i style={{ left: `${(100 * ref) / max}%` }} title={`${A.tourAvg} ${fmt(ref)}`} />}</span>
            <span className="mono" style={{ color: teamVar(1), fontWeight: 700 }}>{av == null ? "—" : fmt(av)}</span>
          </div>
        );
      })}
      <div className="legend"><span><i style={{ background: "var(--ink)", width: 3 }} />{A.tourAvg}</span></div>
      <div className="an-mono-note">
        {A.concededPer} · {teamName(meta.home, lang)} {A.goalsN(fx(H?.against.goals, 1))}, xG {fx(H?.against.xg, 2)} · {teamName(meta.away, lang)} {A.goalsN(fx(W?.against.goals, 1))}, xG {fx(W?.against.xg, 2)}
      </div>
    </div>
  );
}

function KeyPlayers({ profile, status }: { profile: PrematchProfile | null; status: ReturnType<typeof usePrematchProfile>["status"] }) {
  const { meta, lang } = useMD();
  const A = useA();
  const { pName } = useNames();
  const wait = profileReady(profile, status, A);
  if (wait || !profile) return wait;
  return (
    <div className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 300px), 1fr))" }}>
      {([0, 1] as const).map((s) => {
        const tm = s ? meta.away : meta.home;
        const tp = profile.teams[tm.team_id];
        return (
          <div key={s} className="col" style={{ gap: 4 }}>
            <div className="tag" style={{ color: teamVar(s) }}>{teamName(tm, lang)}</div>
            {!tp?.matches && <p className="dim" style={{ fontSize: 13 }}>{A.noMatchesShort}</p>}
            {tp?.key_players.map((p) => (
              <div key={p.player_id} className="an-kp">
                <span>{pName(p.player_id, p.name)}</span>
                <span className="mono dim">{p.goals} {A.kp.g} · {A.kp.xg} {p.xg.toFixed(1)} · {p.def_actions} {A.kp.def}</span>
              </div>
            ))}
            {tp && tp.yellow_carriers.length > 0 && (
              <div className="col" style={{ gap: 2, marginTop: 6 }}>
                <span className="tag" style={{ color: "#c9a200" }}><span className="an-yellow" />{A.carrying}</span>
                {tp.yellow_carriers.map((p) => <span key={p.player_id} style={{ fontSize: 13 }}>{pName(p.player_id, p.name)} · {A.yellowsN(p.yellows)}</span>)}
              </div>
            )}
            {tp && tp.matches > 0 && tp.yellow_carriers.length === 0 && <span className="an-mono-note">{A.noCarrier}</span>}
          </div>
        );
      })}
    </div>
  );
}
