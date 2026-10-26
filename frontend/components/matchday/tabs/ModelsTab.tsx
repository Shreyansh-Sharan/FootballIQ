"use client";

// Predictive tab. Forecasts poll in 15 s buckets, the series in 60 s buckets; 503 means "not available yet".

import { useState } from "react";
import { anApi, useBucketed, useInsights, useOnce, type ModelValues, type PredMode, type Predictions, type TeamValues } from "@/lib/matchday/analysis";
import { openTab, watchAt } from "@/lib/matchday/handoff";
import { clockLabel, teamName, teamShort } from "@/lib/matchday/match";
import { neutral } from "@/lib/matchday/neutral";
import type { SideIdx } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";
import { Card, KeyMessage, PanelState, fx, modelLabel, pc, useA, useNames, type Pillar } from "../analysis/common";
import ForecastCard from "../analysis/ForecastCard";
import ModelCards from "../analysis/ModelCards";
import WinProbChart from "../analysis/WinProbChart";
import XgChart from "../analysis/XgChart";

/** Analyst-only retrospective (cross-fit) switch; production shows the live forecast. */
const SHOW_RETRO = process.env.NEXT_PUBLIC_SHOW_RETRO === "1";

export default function ModelsTab() {
  const { U, meta, lang, matchId, clock } = useMD();
  const A = useA();
  const { pName, sideOf } = useNames();
  const t = clock.t;
  const clk = clockLabel(meta.periods, t);
  const [mode, setMode] = useState<PredMode>("strict");
  const retro = mode === "retrospective";
  const latest = useBucketed<Predictions>(`p|${matchId}|${mode}`, (at) => anApi.predictions(matchId, at, mode), { step: 15000 });
  const series = useBucketed(`ps|${matchId}|${mode}`, (at) => anApi.predSeries(matchId, at, mode), { step: 60000 });
  const values = useBucketed<ModelValues>(`mv|${matchId}|${mode}`, (at) => anApi.modelValues(matchId, at, mode), { step: 15000 });
  const p = latest.data && (latest.data.mode === undefined || latest.data.mode === mode) ? latest.data : null;
  const version = p?.model_version ?? null;
  const cards = useOnce(latest.status === "loading" ? null : `mc|${version ?? "latest"}|${mode}`, () => anApi.models(version, mode));
  const { insights } = useInsights(matchId);
  const danger = insights.filter((i) => i.kind === "danger_window" || i.kind === "win_swing").slice().reverse();

  const H = meta.home, W = meta.away;
  const hs = teamShort(H, lang), as = teamShort(W, lang);
  const wh = p?.teams[H.team_id]?.win_phase?.probability, wa = p?.teams[W.team_id]?.win_phase?.probability, d = p?.draw_phase?.probability;
  const phase = p?.phase ? A.phases[p.phase] ?? p.phase : A.thePhase;
  let headline = latest.status === "missing" ? A.na503 : A.waitingModels;
  if (wh != null && wa != null && d != null) {
    const best = Math.max(wh, wa, d);
    headline = best === d ? A.drawLikely(pc(d)) : A.favourite(best === wh ? teamName(H, lang) : teamName(W, lang), pc(best));
  }
  const sub = wh != null && wa != null && d != null ? A.predSub(hs, pc(wh), pc(d), as, pc(wa), phase) : A.predSubWait;
  const gh = p?.teams[H.team_id]?.goal_next_10m?.probability, ga = p?.teams[W.team_id]?.goal_next_10m?.probability;
  const th: TeamValues | undefined = values.data?.teams[H.team_id], ta: TeamValues | undefined = values.data?.teams[W.team_id];
  const fh = th ? th.goals - th.xg : null, fa = ta ? ta.goals - ta.xg : null;
  const ch = th?.completion_above_expected_pct, ca = ta?.completion_above_expected_pct;
  const sg = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`);
  const pillars: Pillar[] = [
    { title: A.pThreat, tone: gh == null || ga == null ? null : gh >= ga ? 0 : 1,
      value: gh == null || ga == null ? "—" : A.toScore(gh >= ga ? hs : as, pc(Math.max(gh, ga))), detail: `${hs} ${pc(gh)} · ${as} ${pc(ga)}` },
    { title: A.pFinishing, tone: fh == null || fa == null || Math.abs(fh - fa) < 0.3 ? null : fh > fa ? 0 : 1,
      value: fh == null || fa == null ? "—" : Math.abs(fh - fa) < 0.3 ? A.asExpected : A.overPerf(fh > fa ? hs : as),
      detail: th && ta ? `${A.finLine(hs, th.goals, th.xg.toFixed(2))} · ${A.finLine(as, ta.goals, ta.xg.toFixed(2))}` : "—" },
    { title: A.pPassing, tone: ch == null || ca == null || Math.abs(ch - ca) < 1 ? null : ch > ca ? 0 : 1,
      value: ch == null || ca == null ? "—" : Math.abs(ch - ca) < 1 ? A.even : A.sharper(ch > ca ? hs : as), detail: A.caeLine(sg(ch), sg(ca)) },
  ];

  const seg = (v: number, side: SideIdx | null, label: string) => (
    <div className={side == null ? "d" : ""} style={{ flexGrow: Math.max(v, 0.03), background: side == null ? undefined : teamVar(side), justifyContent: side === 1 ? "flex-end" : undefined }}>
      {v >= 0.08 ? `${label} ${pc(v)}` : ""}
    </div>
  );
  return (
    <div className="col">
      <KeyMessage label={U.tabs.models} kicker={A.answer(clk, retro ? A.retroAnalysis : A.modelForecast)} headline={headline} sub={sub} pillars={pillars}>
        <div className="an-row">
          {SHOW_RETRO && (
            <div className="seg" role="radiogroup" aria-label={A.modeLabel}>
              <button role="radio" aria-checked={!retro} className={!retro ? "on" : ""} title={A.modeForecastTitle} onClick={() => setMode("strict")}>{A.modeForecast}</button>
              <button role="radio" aria-checked={retro} className={retro ? "on" : ""} title={A.modeRetroTitle} onClick={() => setMode("retrospective")}>{A.modeRetro}</button>
            </div>
          )}
          <span className="chip an-live">{A.liveAt(clk)}</span>
          {p?.feature_cutoff_ms != null && <span className="chip">{A.featuresCut(clockLabel(meta.periods, p.feature_cutoff_ms))}</span>}
          {p?.model_version && <span className={`chip ${retro ? "an-warn" : ""}`}>{A.modelV(modelLabel(p.model_version))}{retro ? ` · ${A.retroTag}` : ""}</span>}
        </div>
      </KeyMessage>

      {retro && (
        <div className="note warn" role="status"><span><b>{A.retroWarn}.</b> {neutral(p?.mode_note) || A.retroDefault} {A.retroBack}</span></div>
      )}

      {p?.prematch && Object.keys(p.prematch).length > 0 && (
        <section className="card" aria-label={A.strength}>
          <div className="card-b an-row" style={{ gap: "8px 22px" }}>
            <h3 style={{ fontSize: 18 }}>{A.strength}</h3>
            {([0, 1] as const).map((s) => {
              const tm = s ? W : H;
              const v = p.prematch?.[tm.team_id];
              return (
                <span key={s} className="mono" style={{ fontSize: 13 }}>
                  <b style={{ color: teamVar(s) }}>{teamName(tm, lang)}</b> {A.elo} {v?.elo_for != null ? Math.round(v.elo_for) : "—"} · {A.formLbl} {fx(v?.form_ppg_for, 1)} {A.formPpg}
                </span>
              );
            })}
            <span className="an-mono-note">{A.resultsBefore}</span>
          </div>
        </section>
      )}

      <div className="grid-charts">
        <Card title={A.outcome(phase)} tag={p?.phase_remaining_s != null ? A.nominalLeft(Math.round(p.phase_remaining_s / 60)) : undefined}>
          {!p ? <PanelState status={latest.status} na={A.na503} /> : (
            <div className="wc" role="img" aria-label={`${A.outcome(phase)}: ${hs} ${pc(wh)}, ${U.draw} ${pc(d)}, ${as} ${pc(wa)}`}>
              {seg(wh ?? 0, 0, hs)}{seg(d ?? 0, null, U.draw)}{seg(wa ?? 0, 1, as)}
            </div>
          )}
          <div className="tag">{A.winOverTime}</div>
          {series.data ? <WinProbChart series={series.data} label={A.winOverTime} /> : <PanelState status={series.status} na={A.na503} />}
          {p && <p className="an-mono-note">{A.egLeft(hs, fx(p.teams[H.team_id]?.expected_goals_rest?.value, 2), as, fx(p.teams[W.team_id]?.expected_goals_rest?.value, 2))}</p>}
        </Card>
        <Card title={A.forecasts}>
          {!p ? <PanelState status={latest.status} na={A.na503} /> : (
            <>
              <ForecastCard p={p} side={0} />
              <ForecastCard p={p} side={1} />
              <p className="an-small">{A.bandNote}</p>
            </>
          )}
        </Card>
      </div>

      <div className="grid-charts">
        <Card title={A.xgTitle}>
          {series.data ? <XgChart series={series.data} label={A.xgTitle} /> : <PanelState status={series.status} na={A.na503} />}
          {values.data ? (
            <div className="scroll-x">
              <table className="ptable an-num">
                <thead><tr>
                  <th scope="col">{A.team}</th><th scope="col" className="n">{A.goals}</th><th scope="col" className="n">{A.shots}</th>
                  <th scope="col" className="n">{A.xgCol}</th>
                </tr></thead>
                <tbody>
                  {([0, 1] as const).map((s) => {
                    const tm = s ? W : H;
                    const v = values.data?.teams[tm.team_id];
                    return (
                      <tr key={s}>
                        <th scope="row" style={{ color: teamVar(s), fontWeight: 700 }}>{teamName(tm, lang)}</th>
                        <td className="n">{v?.goals ?? 0}</td><td className="n">{v?.shots ?? 0}</td>
                        <td className="n">{(v?.xg ?? 0).toFixed(2)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : <PanelState status={values.status} na={A.na503} />}
          <p className="an-small">{A.xgNote}</p>
        </Card>
        <Card title={A.passThreat}>
          {!values.data ? <PanelState status={values.status} na={A.na503} /> : (
            <>
              {([0, 1] as const).map((s) => {
                const tm = s ? W : H;
                const v = values.data?.teams[tm.team_id];
                return (
                  <div key={s} className="an-pt">
                    <span style={{ color: teamVar(s), fontWeight: 700 }}>{teamName(tm, lang)}</span>
                    <div><div className="k">{A.completion}</div><div className="v">{fx(v?.pass_completion_pct, 1, "%")}</div></div>
                    <div><div className="k">{A.xpass}</div><div className="v">{fx(v?.xpass_pct, 1, "%")}</div></div>
                    <div><div className="k">{A.aboveExp}</div><div className="v">{v?.completion_above_expected_pct != null ? A.ptsN(sg(v.completion_above_expected_pct)) : "—"}</div></div>
                  </div>
                );
              })}
              <div className="tag" style={{ marginTop: 4 }}>{A.topThreat}</div>
              {!values.data.top_xt_players.length ? <p className="dim">{A.noThreat}</p> : (
                <div>
                  {values.data.top_xt_players.map((pl) => {
                    const s = sideOf(pl.team_id);
                    return (
                      <div key={pl.player_id} className="an-threat">
                        <span className="an-dot" style={{ background: teamVar(s) }} />
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{pName(pl.player_id, pl.name)}</span>
                        <span className="mono" style={{ fontWeight: 700 }}>{pl.xt_added.toFixed(2)}</span>
                        <span className="mono mute" style={{ minWidth: 72, textAlign: "right" }}>{A.movesN(pl.actions)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
              <p className="an-small">{A.xpassNote}</p>
            </>
          )}
        </Card>
      </div>

      <Card title={A.danger} tag={A.dangerSub}>
        {!danger.length ? <p className="dim">{A.noDanger}</p> : (
          <div className="col" style={{ gap: 6 }}>
            {danger.map((i) => {
              const s = sideOf(i.team_id);
              return (
                <div key={i.id} className="an-danger" style={{ borderLeftColor: teamVar(s) }}>
                  <span className="mono" style={{ fontWeight: 700 }}>{clockLabel(meta.periods, i.t_ms)}</span>
                  <div style={{ minWidth: 0 }}><b>{i.title}</b><p>{neutral(i.detail)}</p></div>
                  <button className="btn ghost an-sm" aria-label={`${A.watch}: ${i.title}`}
                    onClick={() => { if (i.seek_ms != null) watchAt(i.seek_ms, 0); else watchAt(i.t_ms); openTab("live"); }}>▶ {A.watch}</button>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <Card title={A.modelCards} tag={cards.data ? (cards.data.mode === "retrospective" ? A.oof : A.heldOut) : undefined}>
        {!cards.data ? <PanelState status={cards.status} na={A.na503} /> : <ModelCards cards={cards.data} />}
      </Card>
    </div>
  );
}
