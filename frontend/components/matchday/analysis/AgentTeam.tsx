"use client";

// Agent team: one question -> a planner routes it -> specialists work in parallel -> a synthesizer writes one answer
// -> a verifier checks every number. The run is polled every second and drawn live as a pipeline.
// A "team" handoff (askTeam) runs its question on arrival.

import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  teamDone, useAgentStatus, useTeamRoster, useTeamRun,
  type TeamAsk, type TeamPersona, type TeamRun, type TeamTask, type TeamToolCall, type TeamTrace, type TeamVerification,
} from "@/lib/matchday/analysis";
import { CLOCK } from "@/lib/matchday/clock";
import { onHandoff, takePendingTeam, watchAt } from "@/lib/matchday/handoff";
import { clockLabel, playerName, teamName } from "@/lib/matchday/match";
import { neutral } from "@/lib/matchday/neutral";
import { teamVar, useMD } from "../context";
import { I } from "../Icons";
import AgentText from "./AgentText";
import { useA, useSuggestions } from "./common";

const KEYS = ["tactician", "threat", "forecaster", "performance"];
const SHIELD = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z" /><path d="M9 12l2 2 4-4" />
  </svg>
);
const CHECK = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>;
const LANE: Record<string, { color: string; icon: ReactNode }> = {
  tactician: { color: "var(--p-balanced)", icon: I.tactical },
  threat: { color: "var(--chaos)", icon: I.shots },
  forecaster: { color: "var(--p-stop_start)", icon: I.models },
  performance: { color: "var(--control)", icon: I.flow },
};
const ROLE: Record<string, { color: string; icon: ReactNode }> = {
  planner: { color: "var(--accent-text)", icon: I.coach },
  specialists: { color: "var(--accent-text)", icon: I.ai },
  synthesizer: { color: "var(--accent-text)", icon: I.spark },
  verifier: { color: "var(--accent-text)", icon: SHIELD },
  orchestrator: { color: "var(--dim)", icon: I.ai },
};
/** "Watch this moment" seeks to this lead before the asked moment; the stale rule tolerates it (plus 1 s) so the answer stays visible. */
const WATCH_LEAD = 6000;
const CONF: Record<string, string> = { high: "var(--good)", medium: "var(--warn)", low: "#e5576c" };

type LaneState = "ready" | "waiting" | "queued" | "thinking" | "tools" | "done" | "failed" | "skipped" | "idle";
type NodeState = "pending" | "active" | "done" | "warn" | "failed";

/** "Recommendation:" / "Confidence:" alone on a line: join the next line so AgentText styles them as one block. */
const joinLabels = (s: string) => s.replace(/^[ \t]*(\**(?:recommendation|confidence)\**:\**|\**(?:recommendation|confidence)\**)[ \t]*\n+[ \t]*(?:[-*•][ \t]+)?/gim, "$1 ");
const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const toolName = (A: ReturnType<typeof useA>, name: string) => A.tools[name] ?? cap(name.replace(/^get_/, "").replace(/_/g, " "));

/** Backend free text for display: ids -> names, tool and field names -> plain words, then neutral(). */
function useClean() {
  const { meta, lang, players } = useMD();
  const A = useA();
  return useCallback((s: string | null | undefined) => {
    if (!s) return "";
    let out = s.split(meta.home.team_id).join(teamName(meta.home, lang)).split(meta.away.team_id).join(teamName(meta.away, lang));
    out = out.replace(/\bp-[a-z0-9]{6}\b/g, (id) => { const p = players.get(id); return p ? playerName(p, lang) : id; });
    out = out.replace(/\b(?:provider_xg|xg_statsbomb)\b/gi, "event xG");
    out = out.replace(/\bget_[a-z_]+\b/g, (n) => A.tools[n] ?? n);
    out = out.replace(/\b[a-z]+(?:_[a-z0-9]+)+\b/g, (w) => w.replace(/_/g, " "));
    return neutral(out);
  }, [meta, lang, players, A]);
}

/** Last trace time per agent for the given kind. */
function lastT(trace: TeamTrace[], kind: string): Map<string, number> {
  const m = new Map<string, number>();
  for (const e of trace) if (e.kind === kind) m.set(e.agent, e.t);
  return m;
}

function laneState(run: TeamRun | null, busy: boolean, task: TeamTask | undefined, secs: number, lastTool: number | undefined): LaneState {
  if (!run) return busy ? "waiting" : "ready";
  if (!run.plan) return run.status === "failed" ? "idle" : "waiting";
  if (!task) return "idle";
  if (task.status === "running") return lastTool != null && secs - lastTool < 4 ? "tools" : "thinking";
  if (task.status === "queued" && run.status === "failed") return "skipped";
  return task.status === "queued" ? "queued" : task.status;
}

export default function AgentTeam() {
  const md = useMD();
  const { meta, lang, matchId, clock, view, U } = md;
  const A = useA();
  const T = A.crew;
  const status = useAgentStatus();
  const configured = !!status.data?.configured;
  const off = status.status === "ready" && !configured;
  const roster = useTeamRoster();
  const { run, ask, error, busy, reconnecting, syncedAt, start, retry, clear } = useTeamRun(matchId);
  const clean = useClean();
  const base = useSuggestions();
  const [q, setQ] = useState("");
  const [queued, setQueued] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const t = clock.t;
  const clk = clockLabel(meta.periods, t);
  const suggestions = [T.combo(clk), ...base.slice(0, 4)];

  // ---- asking
  const favTeam = view.fav === 0 ? meta.home : meta.away;
  const opts = useRef({ lang, persona: view.persona as TeamPersona, fav: favTeam.team_id });
  opts.current = { lang, persona: view.persona as TeamPersona, fav: favTeam.team_id };
  const go = useCallback((question: string) => {
    const o = opts.current;
    void start({ question, at_ms: CLOCK.t, lang: o.lang, persona: o.persona, fav_team_id: o.persona === "fan" ? o.fav : null });
  }, [start]);
  const send = () => { if (q.trim() && !busy && !off) { go(q); setQ(""); } };

  // ---- handoffs: a pending team question runs on arrival (replacing a run in progress)
  useEffect(() => {
    const p = takePendingTeam();
    if (p) setQueued(p);
    return onHandoff((h) => {
      if (h.type !== "team") return;
      const p2 = takePendingTeam();
      if (p2) setQueued(p2);
    });
  }, []);
  useEffect(() => {
    if (!queued || status.status === "loading") return;
    if (off) setQ(queued);
    else go(queued);
    setQueued(null);
  }, [queued, off, status.status, go]);

  // ---- live seconds between polls
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [busy]);
  const live = !!run && !teamDone(run.status);
  const secs = run ? run.seconds + (live && syncedAt ? Math.max(0, Math.min(8, (now - syncedAt) / 1000)) : 0) : 0;

  // ---- derived
  const tasks = run?.plan?.tasks ?? [];
  const byKey = new Map(tasks.map((x) => [x.specialist, x]));
  const keys = [...KEYS, ...tasks.map((x) => x.specialist).filter((k) => !KEYS.includes(k))];
  const order = run?.plan ? [...keys.filter((k) => byKey.has(k)), ...keys.filter((k) => !byKey.has(k))] : keys;
  const starts = lastT(run?.trace ?? [], "task_start");
  const tools = lastT(run?.trace ?? [], "tool");
  const doneN = tasks.filter((x) => x.status === "done" || x.status === "failed" || x.status === "skipped").length;
  const at = run?.request.at_ms ?? ask?.at_ms ?? null;
  const askedClk = at != null ? clockLabel(meta.periods, at) : clk;
  const future = at != null && at > t + WATCH_LEAD + 1000;
  const moved = at != null && !future && Math.abs(t - at) > 60000;
  const toolbelt = new Map((roster?.specialists ?? []).map((s) => [s.key, s.tools]));
  const specName = (k: string) => T.spec[k]?.title ?? cap(k);

  // hover title on tool chips: arguments with ids replaced by names
  const argsTitle = (c: TeamToolCall) => {
    const a = JSON.stringify(c.arguments ?? {});
    return a === "{}" ? toolName(A, c.name) : `${toolName(A, c.name)} ${clean(a)}`;
  };

  // ---- pipeline nodes
  const st = run?.status;
  const revising = !!run?.trace.some((e) => e.kind === "revise") && st !== "done";
  const ver = run?.verification;
  const nodes: { key: string; state: NodeState; sub: string }[] = [
    {
      key: "planner",
      state: !run ? (busy ? "active" : "pending") : run.plan ? "done" : st === "failed" ? "failed" : "active",
      sub: run?.plan ? T.stage.picked(tasks.length) : st === "failed" ? T.stage.failed : run || busy ? T.stage.planning : T.roleSub.planner,
    },
    {
      key: "specialists",
      state: !run?.plan ? "pending" : st === "running" ? "active" : st === "failed" && !run.answer && doneN < tasks.length ? "failed"
        : tasks.length && tasks.every((x) => x.status === "failed" || x.status === "skipped") ? "failed" : tasks.some((x) => x.status !== "done") ? "warn" : "done",
      sub: run?.plan ? T.stage.working(doneN, tasks.length) : T.roleSub.specialists,
    },
    {
      key: "synthesizer",
      state: st === "synthesising" ? "active" : st === "verifying" || st === "done" || !!run?.answer ? (revising ? "active" : "done")
        : st === "failed" && run?.plan && doneN === tasks.length ? "failed" : "pending",
      sub: revising ? T.stage.revising : st === "synthesising" ? T.stage.writing : run?.answer ? T.words((run.answer.match(/\S+/g) ?? []).length) : T.roleSub.synthesizer,
    },
    {
      key: "verifier",
      state: st === "verifying" ? "active" : st === "done" && ver ? (ver.status === "pass" && !ver.unverified_numbers.length ? "done" : ver.status === "fail" ? "failed" : "warn")
        : st === "done" ? "done" : st === "failed" && run?.answer ? "failed" : "pending",
      sub: st === "verifying" ? T.stage.checking : st === "done" && ver ? `${ver.numbers_checked} ✓${ver.unverified_numbers.length ? ` · ${ver.unverified_numbers.length} ?` : ""}` : T.roleSub.verifier,
    },
  ];

  // ---- screen-reader progress (one line per stage change)
  const say = !run ? (busy ? T.say.planning : "")
    : st === "queued" || st === "planning" ? T.say.planning
      : st === "running" ? (doneN ? T.say.done(doneN, tasks.length) : T.say.picked(tasks.map((x) => specName(x.specialist)).join(", ")))
        : st === "synthesising" ? T.say.writing : st === "verifying" ? T.say.checking : st === "done" ? T.say.ready : T.say.failed;

  const who = (a: TeamAsk | null) => {
    if (!a) return "";
    if (a.persona === "fan") {
      const tm = a.fav_team_id === meta.away.team_id ? meta.away : meta.home;
      return T.fanOf(teamName(tm, lang));
    }
    return U.personas[a.persona] ?? a.persona;
  };
  const whoColor = ask?.persona === "fan" ? teamVar(ask.fav_team_id === meta.away.team_id ? 1 : 0) : "var(--accent)";
  const followUp = () => {
    if (!run) return;
    setQ(T.followUpPrefix(run.request.question));
    input.current?.focus();
  };
  const fmt = (n: number) => n.toLocaleString(lang === "hi" ? "hi-IN" : lang === "es" ? "es-ES" : "en-GB");
  const errText = error === "network" ? T.errNetwork : error === "lost" ? T.errLost : error === "failed" ? T.errStart : null;
  const showSkeleton = (st === "synthesising" || st === "verifying") && !run?.answer;

  return (
    <section className="card at" aria-label={T.title}>
      <div className="card-h">
        <h3>{T.title}</h3>
        <div className="an-row">
          {(roster?.model || run?.model) && <span className="tag">{(run?.model ?? roster?.model ?? "").toUpperCase()} · {keys.length} × {T.roles.specialists}</span>}
          {(run || error) && <button className="chip" onClick={clear}>{T.newQ}</button>}
        </div>
      </div>
      <div className="card-b">
        <p className="sr" role="status" aria-live="polite">{say}</p>
        {!run && !busy && <p className="dim at-intro">{T.sub}</p>}
        {off && <div className="note notrack" role="status"><b>{T.setup}</b><span>{T.setupSub}</span></div>}
        {(status.status === "error" || status.status === "missing") && !run && <div className="note err" role="status">{A.agentDown}</div>}

        <form className="an-input" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} maxLength={2000} disabled={busy || off} aria-label={A.question}
            placeholder={off ? A.placeholderOff : T.placeholder(clk)} />
          <button className="btn" disabled={busy || !q.trim() || off}>{busy ? T.working : T.ask}</button>
        </form>
        {!run && !busy && !error && (
          <div className="col" style={{ gap: 8 }}>
            <span className="tag">{A.tryAsking}</span>
            <div className="an-sugs">
              {suggestions.map((s) => <button key={s} className="an-sug" disabled={off} onClick={() => go(s)}>{s}</button>)}
            </div>
          </div>
        )}

        {error === "unavailable" && <div className="note notrack" role="status"><b>{T.setup}</b><span>{T.setupSub}</span></div>}
        {errText && (
          <div className="note err at-errbox" role="alert">
            <span>{errText}</span>
            {ask && <button className="btn ghost sm" onClick={retry}>{T.retry}</button>}
          </div>
        )}
        {reconnecting && <div className="note small" role="status"><span className="spin" aria-hidden="true" /><span>{T.reconnecting}</span></div>}

        {ask && (
          <div className="at-q">
            <div className="an-row">
              <span className="an-mono-note">{T.askedAt(askedClk)}</span>
              <span className="at-for"><span className="an-dot" style={{ background: whoColor }} />{T.forWho(who(ask))}</span>
              {run && live && <span className="at-clock mono" aria-hidden="true">{secs.toFixed(0)} s</span>}
            </div>
            <p className="at-q-text">{ask.question}</p>
          </div>
        )}

        <ol className={`at-steps ${live || busy ? "live" : ""}`} aria-label={T.pipeline}>
          {nodes.map((n) => (
            <li key={n.key} className={`at-step ${n.state}`}>
              <span className="at-node" aria-hidden="true">{n.state === "done" ? CHECK : ROLE[n.key].icon}</span>
              <b>{T.roles[n.key]}</b>
              <small>{n.sub}</small>
            </li>
          ))}
        </ol>

        {run?.plan && (
          <div className="at-plan">
            <span className="at-plan-k">{ROLE.planner.icon}{T.plan}{run.plan.source === "fallback" && <span className="chip an-warn">{T.fallbackPlan}</span>}</span>
            <p><b>{cap(clean(run.plan.intent))}</b>{run.plan.reason && <span className="dim"> · {clean(run.plan.reason)}</span>}</p>
          </div>
        )}

        {run?.status === "failed" && (
          <div className="note err at-errbox" role="alert">
            <div className="col" style={{ gap: 4 }}>
              <b>{T.errFailed}</b>
              {run.error && <code className="at-errcode">{clean(run.error)}</code>}
            </div>
            <button className="btn ghost sm" onClick={retry}>{T.retry}</button>
          </div>
        )}

        {showSkeleton && (
          <div className="at-ans pending" aria-busy="true">
            <div className="at-ans-h"><span className="at-av">{st === "verifying" ? SHIELD : I.spark}</span><h4>{T.answer}</h4></div>
            <p className="an-thinking">{st === "verifying" ? T.checking : T.writing(tasks.filter((x) => x.report).length)}</p>
            <div className="at-skel" aria-hidden="true"><i /><i /><i /><i /></div>
          </div>
        )}
        {run?.answer && (
          <section className="at-ans" aria-label={T.answer}>
            <div className="at-ans-h">
              <span className="at-av">{I.spark}</span>
              <h4>{T.answer}</h4>
              <span className="tag">{askedClk}</span>
            </div>
            {future ? (
              <div className="note warn small" role="status">
                <span>{T.future(askedClk)} — <button className="an-link" onClick={() => watchAt(at!, 0)}>{A.goTo(askedClk)}</button></span>
              </div>
            ) : (
              <>
                <AgentText text={joinLabels(clean(run.answer))} />
                <Verdict v={ver ?? null} checking={st === "verifying"} />
                <div className="an-row at-ans-f">
                  <span className="an-mono-note">
                    {T.meta((run.model ?? "").toUpperCase(), run.seconds.toFixed(0), fmt(run.usage.prompt_tokens + run.usage.completion_tokens), run.usage.model_calls)}
                  </span>
                  <span className="an-grow" />
                  {moved && <span className="an-mono-note">{T.movedOn(askedClk, clk)}</span>}
                  {moved && <button className="btn ghost sm" onClick={() => watchAt(at!, WATCH_LEAD)}>{T.watch}</button>}
                  <button className="btn ghost sm" onClick={followUp} disabled={busy}>{T.followUp}</button>
                </div>
              </>
            )}
          </section>
        )}

        <div className="at-lanes" aria-label={T.roles.specialists}>
          {order.map((k) => {
            const task = byKey.get(k);
            const ls = laneState(run, busy, task, secs, tools.get(k));
            const s0 = starts.get(k);
            const elapsed = task?.seconds != null && task.status !== "running" ? task.seconds
              : task?.status === "running" && s0 != null ? Math.max(0, secs - s0) : null;
            return (
              <Lane key={k} k={k} state={ls} task={task} elapsed={elapsed} hide={future} clean={clean} argsTitle={argsTitle}
                belt={toolbelt.get(k) ?? []} />
            );
          })}
        </div>

        {run && run.trace.length > 0 && <Log run={run} hide={future} clean={clean} specName={specName} />}
        <p className="an-small">{A.disclaimer}</p>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ one specialist lane
function Lane({ k, state, task, elapsed, hide, clean, argsTitle, belt }: {
  k: string; state: LaneState; task: TeamTask | undefined; elapsed: number | null; hide: boolean;
  clean: (s: string | null | undefined) => string; argsTitle: (c: TeamToolCall) => string; belt: string[];
}) {
  const A = useA();
  const T = A.crew;
  const look = LANE[k] ?? { color: "var(--accent)", icon: I.ai };
  const spec = T.spec[k] ?? { title: cap(k), brief: "" };
  const rep = task?.report;
  const active = state === "thinking" || state === "tools";
  const compact = state === "ready" || state === "idle" || state === "waiting";
  return (
    <article className={`at-lane ${state}`} style={{ "--lane": look.color } as CSSProperties} aria-label={`${spec.title}: ${T.st[state]}`}>
      {active && <span className="at-bar" aria-hidden="true" />}
      <div className="at-lane-h">
        <span className="at-av" aria-hidden="true">{look.icon}</span>
        <div className="at-lane-t"><b>{spec.title}</b><small>{spec.brief}</small></div>
        <span className={`at-st ${state}`}>
          <i aria-hidden="true">{state === "done" ? CHECK : null}</i>
          <span>{T.st[state]}</span>
          {elapsed != null && <em className="mono">{T.secs(elapsed.toFixed(0))}</em>}
        </span>
      </div>
      {state === "idle" && <p className="at-idle">{T.notNeeded}</p>}
      {compact && belt.length > 0 && (
        <p className="at-belt"><span>{T.toolbelt}</span> {belt.filter((b) => b !== "get_match_context").map((b) => toolName(A, b)).join(" · ")}</p>
      )}
      {task && <p className="at-brief"><span className="tag">{T.brief}</span> {clean(task.question)}</p>}
      {task && task.tool_calls.length > 0 && (
        <div className="at-tools">
          {task.tool_calls.map((c, i) => (
            <span key={i} className={`at-tool ${c.ok ? "" : "bad"}`} title={argsTitle(c)}>
              <span aria-hidden="true">{c.ok ? "✓" : "∅"}</span> {toolName(A, c.name)}
              {!c.ok && <span className="sr"> ({T.failedTool})</span>}
              {c.cached && <span className="at-shared">{T.shared}</span>}
            </span>
          ))}
        </div>
      )}
      {active && <div className="at-dots" aria-hidden="true"><i /><i /><i /></div>}
      {task?.error && task.status !== "done" && <p className="at-err">{clean(task.error)}</p>}
      {rep && !hide && (
        <div className="at-rep">
          {rep.summary && <p className="at-sum">{clean(rep.summary)}</p>}
          {rep.findings.length > 0 && (
            <ul className="at-finds" aria-label={T.findings}>
              {rep.findings.map((f, i) => (
                <li key={i}>
                  <p>
                    <span className="at-conf" style={{ "--c": CONF[f.confidence] ?? "var(--mute)" } as CSSProperties}>{A.confs[f.confidence] ?? f.confidence}</span>
                    {clean(f.claim)}
                  </p>
                  {f.evidence && <details className="at-evd"><summary>{T.evidence}</summary><p>{clean(f.evidence)}</p></details>}
                </li>
              ))}
            </ul>
          )}
          {rep.recommendation && <div className="an-rec at-rec"><span className="tag">{T.recommendation}</span>{clean(rep.recommendation)}</div>}
          {rep.data_gaps.length > 0 && (
            <div className="at-gaps"><span className="tag">{T.gaps}</span><ul>{rep.data_gaps.map((g, i) => <li key={i}>{clean(g)}</li>)}</ul></div>
          )}
        </div>
      )}
    </article>
  );
}

// ------------------------------------------------------------------ verification badge
function Verdict({ v, checking }: { v: TeamVerification | null; checking: boolean }) {
  const A = useA();
  const T = A.crew;
  if (checking) return <div className="at-ver active" role="status"><span className="spin" aria-hidden="true" />{T.checking}</div>;
  if (!v) return <div className="at-ver none">{SHIELD}<span>{T.verNone}</span></div>;
  const un = v.unverified_numbers;
  const fut = v.future_minutes;
  const tone = v.status === "fail" ? "fail" : un.length || fut.length || v.status === "warn" ? "warn" : "pass";
  const lines: string[] = [];
  if (un.length) lines.push(T.verWarn(un.length, un.slice(0, 6).join(", ") + (un.length > 6 ? "…" : "")));
  if (fut.length) lines.push(T.verFuture(fut.slice(0, 6).join(", ")));
  if (tone === "fail" && !lines.length) lines.push(T.verFail);
  if (tone === "pass" || (!lines.length && v.numbers_checked)) lines.unshift(v.numbers_checked ? T.verPass(v.numbers_checked) : T.verNone);
  if (!lines.length) lines.push(T.verNone);
  return (
    <div className={`at-ver ${tone}`}>
      {SHIELD}
      <div className="col" style={{ gap: 2 }}>
        <span>{lines.join(" · ")}{v.revised && <span className="at-rev"> · {T.revised}</span>}</span>
        {v.issues.length > 0 && (
          <details className="at-evd"><summary>{T.issues}</summary><ul>{v.issues.map((x, i) => <li key={i}>{neutral(x)}</li>)}</ul></details>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ activity log (newest first)
function Log({ run, hide, clean, specName }: { run: TeamRun; hide: boolean; clean: (s: string | null | undefined) => string; specName: (k: string) => string }) {
  const A = useA();
  const T = A.crew;
  const [open, setOpen] = useState(true);
  const agentName = (a: string) => (KEYS.includes(a) || !T.roles[a] ? specName(a) : T.roles[a]);
  const color = (a: string) => LANE[a]?.color ?? ROLE[a]?.color ?? "var(--dim)";
  const detail = (e: TeamTrace): ReactNode => {
    const d = e.detail ?? "";
    switch (e.kind) {
      case "plan": {
        const m = /^\w+:\s*([\w ,]+?)(?:\s+-\s+.*)?$/.exec(d);
        return m ? m[1].split(",").map((s) => specName(s.trim())).join(", ") : clean(d);
      }
      case "tool": {
        const shared = /\(shared\)\s*$/.test(d);
        const name = d.replace(/\s*\(shared\)\s*$/, "").trim();
        return <>{toolName(A, name)}{shared && <span className="at-shared">{T.shared}</span>}</>;
      }
      case "synth": { const n = /(\d+)\s+words/.exec(d); return n ? T.words(+n[1]) : clean(d); }
      case "verify": { const n = /(\d+)\s+numbers/.exec(d); return n && d.startsWith("pass") ? T.verPass(+n[1]) : clean(d); }
      case "done": { const n = /(\d+) model calls, (\d+) tool calls/.exec(d); return n ? T.calls(+n[1], +n[2]) : clean(d); }
      default: return hide && (e.kind === "task_done" || e.kind === "revise") ? "" : clean(d);
    }
  };
  const rows = run.trace.map((e, i) => ({ e, i })).reverse();
  return (
    <details className="at-log" open={open} onToggle={(ev) => setOpen((ev.currentTarget as HTMLDetailsElement).open)}>
      <summary><span>{T.log}</span><span className="an-mono-note">{T.logN(rows.length)}</span></summary>
      <ol>
        {rows.map(({ e, i }) => (
          <li key={i} className={`k-${e.kind}`}>
            <span className="t mono">+{e.t.toFixed(1)}s</span>
            <span className="who" style={{ color: color(e.agent) }}>{agentName(e.agent)}</span>
            <span className="what"><b>{T.ev[e.kind] ?? e.kind}</b> <span className="det">{detail(e)}</span></span>
          </li>
        ))}
      </ol>
    </details>
  );
}
