// Recaps: the top N moments by relevance, told in match order with a lead, stats line and dominant rhythm.

import { UI } from "./i18n";
import { teamName } from "./match";
import { relevance, renderInsight, type RenderCtx, type View } from "./perspective";
import { RECAP, type RecapScope } from "./templates";
import type { Lang, Moment, Pattern, SeriesPoint } from "./types";

export type RecapFormat = "studio" | "social" | "push" | "report";
export const RECAP_FORMATS: RecapFormat[] = ["studio", "social", "push", "report"];
export const RECAP_SCOPES: RecapScope[] = ["now", "ht", "ft"];

export interface RecapStats { sh: [number, number]; xg: [number, number]; po: [number, number] }

export interface RecapInput {
  moments: Moment[];
  end: number;
  endLabel: string;
  scope: RecapScope;
  fmt: RecapFormat;
  view: View;
  lang: Lang;
  excluded: Set<string>;
  ctx: RenderCtx;
  stats: RecapStats | null;
  points: SeriesPoint[];
}

export interface Recap { text: string; used: string[]; ranked: { m: Moment; r: number }[] }

export function buildRecap(o: RecapInput): Recap {
  const R = RECAP[o.lang], U = UI[o.lang], meta = o.ctx.meta;
  const ranked = o.moments.filter((m) => m.t_ms <= o.end).map((m) => ({ m, r: relevance(m, o.view) })).sort((a, b) => b.r - a.r);
  const pool = ranked.filter((x) => !o.excluded.has(x.m.id));
  const n = { push: 1, social: 3, studio: 5, report: 8 }[o.fmt];
  const top = pool.slice(0, n).sort((a, b) => a.m.t_ms - b.m.t_ms);
  const sc = o.ctx.scoreAt(o.end);
  const pats: Partial<Record<Pattern, number>> = {};
  for (const p of o.points) if (p.t_ms <= o.end && p.flow) pats[p.flow.pattern] = (pats[p.flow.pattern] ?? 0) + 1;
  const entries = Object.entries(pats) as [Pattern, number][];
  const dom = entries.sort((a, b) => b[1] - a[1])[0];
  const share = dom ? Math.round((100 * dom[1]) / Math.max(1, entries.reduce((a, [, c]) => a + c, 0))) : 0;
  const spoiler = o.view.spoiler;
  const end_ = (s: string) => (/[.!?।]$/.test(s) ? s : `${s}.`);
  const lines = top.map(({ m }, k) => {
    const r = renderInsight(m, o.view, o.lang, o.ctx);
    const body = r.b.replace(/^\d+(\+\d+)?′\s*·\s*/, "").replace(/^PEN\s*·\s*/, "");
    return { m, text: `${R.then[Math.min(k, R.then.length - 1)]}, ${m.clock}: ${end_(r.h)} ${end_(body)}` };
  });
  const hide = (s: string) => (spoiler ? s.replace(/\d+–\d+/g, "–") : s);
  const fav = o.view.fav;
  const lead = o.view.persona === "fan"
    ? R.fanLead({ spoiler, us: teamName(fav === 0 ? meta.home : meta.away, o.lang), usS: sc[fav], themS: sc[1 - fav] })
    : R.lead({ spoiler, a: teamName(meta.home, o.lang), b: teamName(meta.away, o.lang), sa: sc[0], sb: sc[1], scope: o.scope, m: o.endLabel });
  const stats = o.stats ? R.stats({ sh: o.stats.sh, xg: [o.stats.xg[0].toFixed(2), o.stats.xg[1].toFixed(2)], po: o.stats.po }) : "";
  const rh = dom ? R.rhythm({ p: U.patterns[dom[0]], share }) : "";
  let text: string;
  if (o.fmt === "push") {
    const r = top[0] ? renderInsight(top[0].m, o.view, o.lang, o.ctx) : { h: lead, b: "" };
    text = r.b ? `${r.h} · ${r.b}` : r.h;
  } else if (o.fmt === "social") {
    text = `${lead}\n\n${lines.map((l) => `▸ ${l.text.split(": ").slice(1).join(": ")}`).join("\n")}\n\n${R.hashtag(meta.home.short, meta.away.short)}`;
  } else if (o.fmt === "studio") {
    text = [lead, ...lines.map((l) => l.text), rh, R.cta[o.view.persona] ?? ""].filter(Boolean).join(" ");
  } else {
    text = `${R.title[o.scope]}\n\n${[lead, stats].filter(Boolean).join(" ")}\n\n${lines.map((l) => l.text).join("\n\n")}${rh ? `\n\n${rh}` : ""}`;
  }
  return { text: hide(text), used: top.map((x) => x.m.id), ranked };
}
