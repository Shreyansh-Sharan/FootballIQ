// Cross-panel handoffs (open a tab, ask the analyst, focus a player, seek) without prop drilling.
// The Shell subscribes and acts; tabs consume the pending question or section.

import type { TabKey } from "@/components/matchday/Header";

export type CoachSection = "subs" | "form" | "best" | "physical";

export type Handoff =
  | { type: "tab"; tab: TabKey; section?: string }
  | { type: "ask"; question: string }                      // opens the AI tab and asks the Strategist
  | { type: "explain" }                                    // opens the AI tab and runs the Moment Explainer
  | { type: "team"; question: string }                     // opens the AI tab and asks the agent team
  | { type: "focus"; playerId: string; tab?: TabKey }      // highlight a player on the pitch / Player Focus
  | { type: "coach"; section: CoachSection; teamSide?: 0 | 1; playerId?: string }
  | { type: "seek"; t_ms: number; lead_ms?: number };      // seek to t_ms - lead_ms (never past the live edge)

type Listener = (h: Handoff) => void;
const listeners = new Set<Listener>();
let pendingQuestion: string | null = null;
let pendingTeam: string | null = null;
let pendingSection: string | null = null;

export function handoff(h: Handoff): void {
  if (h.type === "ask") pendingQuestion = h.question;
  if (h.type === "team") pendingTeam = h.question;
  if (h.type === "tab" && h.section) pendingSection = h.section;
  if (h.type === "coach") pendingSection = h.section;
  listeners.forEach((l) => l(h));
}

export function onHandoff(l: Listener): () => void {
  listeners.add(l);
  return () => { listeners.delete(l); };
}

/** Consumes the pending question (null afterwards). */
export function takePendingQuestion(): string | null {
  const q = pendingQuestion;
  pendingQuestion = null;
  return q;
}

/** Consumes the pending agent-team question (null afterwards). */
export function takePendingTeam(): string | null {
  const q = pendingTeam;
  pendingTeam = null;
  return q;
}

/** Which AI-tab handoff is waiting, without consuming it (the AI tab picks the matching mode). */
export function pendingAiMode(): "single" | "team" | null {
  return pendingTeam != null ? "team" : pendingQuestion != null ? "single" : null;
}

/** Consumes the pending section (e.g. Coach "subs"). */
export function takePendingSection(): string | null {
  const s = pendingSection;
  pendingSection = null;
  return s;
}

export const askAI = (question: string) => handoff({ type: "ask", question });
export const askTeam = (question: string) => handoff({ type: "team", question });
export const openTab = (tab: TabKey, section?: string) => handoff({ type: "tab", tab, section });
export const watchAt = (t_ms: number, lead_ms = 6000) => handoff({ type: "seek", t_ms, lead_ms });
export const focusPlayer = (playerId: string, tab?: TabKey) => handoff({ type: "focus", playerId, tab });
