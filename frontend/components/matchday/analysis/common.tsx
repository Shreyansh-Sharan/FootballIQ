"use client";

// Shared helpers for the analysis tabs: strings, formatting, name lookups and small building blocks.

import "@/app/matchday-analysis.css";
import type { Status } from "@/lib/matchday/api";
import { AU, type AStrings } from "@/lib/matchday/i18n-analysis";
import { playerName, teamName, teamShort } from "@/lib/matchday/match";
import type { MetaTeam, SideIdx } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";

export function useA(): AStrings {
  const { lang } = useMD();
  return AU[lang];
}

// ------------------------------------------------------------------ formatting
const ok = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);
export const pc = (v: number | null | undefined, d = 0) => (ok(v) ? `${(100 * v).toFixed(d)}%` : "—");
/** Percentage with one decimal below 10 %. */
export const pcAuto = (v: number | null | undefined) => (ok(v) ? pc(v, v < 0.1 ? 1 : 0) : "—");
export const fx = (v: number | null | undefined, d = 1, unit = "") => (ok(v) ? `${v.toFixed(d)}${unit}` : "—");
export const sgn = (v: number | null | undefined, d = 2, unit = "") => (ok(v) ? `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}${unit}` : "—");
/** Drops the training-cutoff suffix ("-c20221120"). */
export const modelLabel = (v: string | null | undefined) => (v ?? "").replace(/-c\d{8}$/, "");

// ------------------------------------------------------------------ names
export function useNames() {
  const { meta, lang, players } = useMD();
  const sideOf = (teamId: string | null | undefined): SideIdx | null => (teamId === meta.home.team_id ? 0 : teamId === meta.away.team_id ? 1 : null);
  const team = (s: SideIdx): MetaTeam => (s === 0 ? meta.home : meta.away);
  const tName = (teamId: string | null | undefined, short = false) => {
    const s = sideOf(teamId);
    return s == null ? "" : short ? teamShort(team(s), lang) : teamName(team(s), lang);
  };
  /** Localised name from meta, else the fallback. */
  const pName = (pid: string | null | undefined, fallback?: string | null) => {
    const p = pid ? players.get(pid) : undefined;
    return p ? playerName(p, lang) : fallback ?? "—";
  };
  return { sideOf, team, tName, pName };
}

/** Suggested questions for the AI analysts at the replay clock (score-aware); shared by the Strategist and the agent team. */
export function useSuggestions(): string[] {
  const { meta, lang, score } = useMD();
  const A = useA();
  const behind = score[0] < score[1] ? meta.home : score[1] < score[0] ? meta.away : null;
  return [A.sug.top, behind ? A.sug.trailing(teamName(behind, lang)) : A.sug.level, A.sug.where, A.sug.shape, A.sug.chances];
}

// ------------------------------------------------------------------ building blocks
export interface Pillar { title: string; value: string; detail: string; tone: SideIdx | null }

/** Headline answer, then up to three supporting pillars. */
export function KeyMessage({ kicker, headline, sub, pillars, children, label }: {
  kicker: string; headline: string; sub?: string; pillars?: Pillar[]; children?: React.ReactNode; label: string;
}) {
  return (
    <section className="card an-km" aria-label={label}>
      <div className="card-b">
        <div className="hero">
          <div className="kicker">{kicker}</div>
          <h2>{headline}</h2>
          {sub && <p className="sub">{sub}</p>}
        </div>
        {pillars && pillars.length > 0 && (
          <div className="an-pillars">
            {pillars.map((p) => (
              <div key={p.title} className="an-pillar" style={{ borderTopColor: teamVar(p.tone) }}>
                <span className="k">{p.title}</span>
                <span className="v" style={{ color: p.tone == null ? undefined : teamVar(p.tone) }}>{p.value}</span>
                <span className="s">{p.detail}</span>
              </div>
            ))}
          </div>
        )}
        {children}
      </div>
    </section>
  );
}

export function TeamSeg({ value, onChange, short }: { value: SideIdx; onChange: (s: SideIdx) => void; short?: boolean }) {
  const { meta, lang, U } = useMD();
  return (
    <div className="seg" role="radiogroup" aria-label={U.team}>
      {([0, 1] as const).map((s) => {
        const tm = s ? meta.away : meta.home;
        return (
          <button key={s} className={value === s ? "on" : ""} role="radio" aria-checked={value === s} onClick={() => onChange(s)}>
            <span className="an-dot" style={{ background: teamVar(s), marginRight: 6, boxShadow: "0 0 0 1px rgba(255,255,255,.4)" }} />
            {short ? teamShort(tm, lang) : teamName(tm, lang)}
          </button>
        );
      })}
    </div>
  );
}

export function Kv({ k, v }: { k: string; v: React.ReactNode }) {
  return <><span className="k">{k}</span><span className="v">{v}</span></>;
}

/** Status note for one panel; "missing" (503) reads as unavailable. */
export function PanelState({ status, empty, na }: { status: Status; empty?: string; na?: string }) {
  const { U } = useMD();
  const A = useA();
  const text = status === "loading" ? U.loading : status === "missing" ? na ?? U.unavailable : status === "error" ? A.loadFailed : empty ?? U.unavailable;
  return (
    <div className={`note ${status === "error" ? "err" : ""}`} role="status">
      {status === "loading" && <span className="spin" aria-hidden="true" />}
      <span>{text}</span>
    </div>
  );
}

export function Card({ title, tag, children, className, id, headExtra }: { title: React.ReactNode; tag?: React.ReactNode; children: React.ReactNode; className?: string; id?: string; headExtra?: React.ReactNode }) {
  return (
    <section className={`card ${className ?? ""}`} id={id} aria-label={typeof title === "string" ? title : undefined}>
      <div className="card-h"><h3>{title}</h3>{tag != null && <span className="tag">{tag}</span>}{headExtra}</div>
      <div className="card-b">{children}</div>
    </section>
  );
}

export function TeamTag({ side, short }: { side: SideIdx | null; short?: boolean }) {
  const { meta, lang } = useMD();
  if (side == null) return null;
  const tm = side ? meta.away : meta.home;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontWeight: 700, color: teamVar(side) }}>
      <span className="an-dot" style={{ background: teamVar(side) }} />{short ? teamShort(tm, lang) : teamName(tm, lang)}
    </span>
  );
}
