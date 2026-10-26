"use client";

// Line-ups as of the replay clock: XI, subs, bench, goals and cards. Click a player to highlight him.

import { useMemo } from "react";
import { focusPlayer } from "@/lib/matchday/handoff";
import { cardText, isRed, lineupsAt, type Lineup, type LineupRow } from "@/lib/matchday/live";
import { idxOfPlayer, playerName, teamName } from "@/lib/matchday/match";
import { teamVar, useMD } from "../context";
import { StateNote } from "../StateNote";
import { useLive } from "./LiveCtx";

export default function Lineups() {
  const { U, meta, lang, clock, events, state, idxInfo, view, metaStatus } = useMD();
  const lv = useLive();
  const t = clock.t;
  const lus = useMemo(() => lineupsAt(meta, events.data, t), [meta, events.data, t]);
  const period = state.data?.period ?? 1;
  const limit = period >= 3 ? 6 : 5;
  const selPid = lv.sel != null ? idxInfo.get(lv.sel)?.player?.player_id ?? null : null;
  if (!meta.players.length) return <StateNote status={metaStatus === "fallback" ? "missing" : "loading"} />;
  const pick = (pid: string) => {
    const idx = idxOfPlayer(idxInfo, pid);
    if (selPid === pid) { lv.setSel(null); return; }
    lv.setSel(idx);
    focusPlayer(pid);
  };
  const row = (lu: Lineup, r: LineupRow, note: React.ReactNode, faded: boolean) => {
    const on = selPid === r.p.player_id || view.favPlayer === r.p.player_id;
    return (
      <li key={r.p.player_id}>
        <button className={`lu-row ${on ? "on" : ""} ${faded ? "faded" : ""}`} aria-pressed={on} title={U.lu.highlight} onClick={() => pick(r.p.player_id)}>
          <span className="lu-num" style={on ? { background: teamVar(lu.side), color: "#fff" } : undefined}>{r.p.number ?? "–"}</span>
          <span className="lu-name">{playerName(r.p, lang)}</span>
          <span className="lu-tags">
            {r.goals > 0 && <span aria-label={`${r.goals} × ${U.evt.kinds.goal}`}>{"⚽".repeat(Math.min(3, r.goals))}</span>}
            {r.card && <span className={`lu-card ${isRed(r.card) ? "red" : ""}`} title={cardText(U, r.card)} aria-label={cardText(U, r.card)} />}
            {note}
          </span>
        </button>
      </li>
    );
  };
  return (
    <div className="lus">
      <p className="tag">{U.lu.hint}</p>
      {lus.map((lu) => (
        <div key={lu.side} className="lu" style={{ borderTopColor: teamVar(lu.side) }}>
          <div className="lu-h">
            <b style={{ color: teamVar(lu.side) }}>{teamName(lu.side ? meta.away : meta.home, lang)}</b>
            <span className="tag">{lu.shape ? `${lu.shape} · ` : ""}{period >= 5 ? U.lu.shootout : U.lu.subsLeft(Math.max(0, limit - lu.subsMade), limit)}</span>
          </div>
          <div className="tag">{U.lu.xi}</div>
          <ul>{lu.xi.map((r) => row(lu, r, r.off ? <span className="lu-off">▼ {r.off}</span> : null, !!r.off))}</ul>
          {lu.cameOn.length > 0 && <div className="tag">{U.lu.cameOn}</div>}
          <ul>{lu.cameOn.map((r) => row(lu, r, <span className="lu-on">▲ {r.on}{r.off ? ` ▼ ${r.off}` : ""}</span>, !!r.off))}</ul>
          {lu.bench.length > 0 && (
            <details>
              <summary className="tag">{U.lu.bench(lu.bench.length)}</summary>
              <ul>{lu.bench.map((r) => row(lu, r, null, true))}</ul>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}
