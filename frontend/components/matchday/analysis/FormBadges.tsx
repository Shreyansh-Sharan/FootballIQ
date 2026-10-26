"use client";

// W / D / L squares and the recent-form list for the Pre-match tab.

import type { FormRow, HistorySummary } from "@/lib/matchday/analysis";
import { useA } from "./common";

export function ResultSq({ r }: { r: "W" | "D" | "L" }) {
  const A = useA();
  return <span className={`an-wdl ${r}`} role="img" aria-label={A.wdlLong[r]} title={A.wdlLong[r]}>{A.wdl[r]}</span>;
}

/** Oldest to newest, so the latest result sits on the right. */
export function FormStrip({ rows }: { rows: FormRow[] }) {
  if (!rows.length) return null;
  return <div className="an-wdl-strip">{[...rows].reverse().map((r) => <ResultSq key={r.match_id} r={r.result} />)}</div>;
}

export function FormList({ rows, empty }: { rows: FormRow[]; empty: string }) {
  const A = useA();
  if (!rows.length) return <p className="dim" style={{ fontSize: 13 }}>{empty}</p>;
  return (
    <div className="an-form">
      {rows.map((r) => (
        <div key={r.match_id} className="an-form-r">
          <ResultSq r={r.result} />
          <div style={{ minWidth: 0 }}><b>{r.opponent}</b><small>{r.date}{r.stage ? ` · ${r.stage}` : ""}</small></div>
          <span className="mono" style={{ fontWeight: 700 }}>{r.score}{r.pens ? <small className="mute" style={{ fontWeight: 400 }}> ({A.pens(r.pens)})</small> : null}</span>
        </div>
      ))}
    </div>
  );
}

export function FormSummary({ s }: { s: HistorySummary | undefined }) {
  const A = useA();
  if (!s) return null;
  return (
    <div className="stat-row">
      <div className="tile"><div className="k">{A.played}</div><div className="v">{s.played}</div></div>
      <div className="tile"><div className="k">{A.record}</div><div className="v">{s.won}–{s.drawn}–{s.lost}</div></div>
      <div className="tile"><div className="k">{A.goalsFA}</div><div className="v">{s.goals_for}–{s.goals_against}</div></div>
    </div>
  );
}
