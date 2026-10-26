// Broadcast cues: each moment becomes a timed graphic (template, layer, priority, in/out) for one perspective and language.

import { playerName, teamShort } from "./match";
import { relevance, renderInsight, type RenderCtx, type View } from "./perspective";
import type { Lang, Moment } from "./types";

const TEMPLATE: Record<string, string> = {
  goal: "lower_third.goal", chance: "lower_third.chance", card: "lower_third.card", sub: "lower_third.sub", flow: "stat_bug.rhythm",
  shape: "graphic.shape", speed: "tag.speed", pass: "graphic.pass", milestone: "tag.milestone",
};

export type CueLayer = "lower_third" | "tag" | "bug";

export interface Cue {
  cue_id: string;
  t_in: number;
  t_out: number;
  clock: string;
  template: string;
  priority: 1 | 2 | 3;
  layer: CueLayer;
  persona: string;
  lang: Lang;
  team: string | null;
  side: 0 | 1 | null;
  player: { id: string; name: string; number: number | null } | null;
  text: { headline: string; body: string };
  relevance: number;
}

export const personaKey = (view: View, ctx: RenderCtx) => (view.persona === "fan" ? `fan:${(view.fav === 0 ? ctx.meta.home : ctx.meta.away).team_id}` : view.persona);

export function cuesFor(moments: Moment[], view: View, lang: Lang, ctx: RenderCtx): Cue[] {
  return moments.map((m) => {
    const r = renderInsight(m, view, lang, ctx);
    const dur = m.kind === "goal" ? 12 : m.kind === "speed" || m.kind === "milestone" ? 5 : 8;
    const t = m.t_ms / 1000;
    const p = m.player_id ? ctx.players.get(m.player_id) : undefined;
    return {
      cue_id: `cue-${m.id}`, t_in: +t.toFixed(1), t_out: +(t + dur).toFixed(1), clock: m.clock,
      template: (TEMPLATE[m.kind] ?? `graphic.${m.kind}`) + (m.variant ? `.${m.variant}` : ""),
      priority: m.kind === "goal" ? 1 : m.imp >= 0.35 ? 2 : 3,
      layer: m.kind === "speed" || m.kind === "milestone" ? "tag" : m.kind === "flow" ? "bug" : "lower_third",
      persona: personaKey(view, ctx), lang, team: m.team_id ?? null, side: m.side,
      player: p ? { id: p.player_id, name: playerName(p, lang), number: p.number } : null,
      text: { headline: r.h, body: r.b }, relevance: +relevance(m, view).toFixed(2),
    };
  });
}

export function livePayload(o: { ctx: RenderCtx; view: View; lang: Lang; t: number; clock: string; score: [number, number]; active: Cue[] }) {
  const { meta } = o.ctx;
  return {
    match: `${meta.home.short}-${meta.away.short}`, clock: o.clock, t: +(o.t / 1000).toFixed(1), persona: personaKey(o.view, o.ctx), lang: o.lang,
    scorebug: { home: teamShort(meta.home, o.lang), away: teamShort(meta.away, o.lang), score: o.score }, active: o.active.slice(-3),
  };
}

/** JSON with syntax-highlight spans (keys, strings, numbers); input is escaped first. */
export function highlightJson(json: string): string {
  return json.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+\.?\d*)/g, (_m, s: string | undefined, colon: string | undefined, n: string | undefined) =>
      s ? (colon ? `<span class="k">${s}</span>${colon}` : `<span class="s">${s}</span>`) : `<span class="n">${n}</span>`);
}
