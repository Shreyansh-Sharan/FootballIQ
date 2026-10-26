// Display text never names data providers: pass backend free text through neutral() before rendering.
// Provider fields (e.g. xg_statsbomb) are labelled via BENCHMARK; provider xG shows as "event xG".

const RULES: [RegExp, string][] = [
  [/StatsBomb\s*360(\s+snapshots?)?/gi, "event freeze-frames"],
  [/StatsBomb\s+possession\s+chains/gi, "event possession chains"],
  [/StatsBomb\s+(tactical\s+shift)/gi, "team-sheet $1"],
  [/\(?StatsBomb\)?\s*xG/gi, "event xG"],
  [/\b(?:provider\s+)?benchmark\s+xG\b/gi, "event xG"],
  [/\bprovider\s+benchmark\b/gi, "event data"],
  [/\bthe\s+benchmark\b/gi, "the event data"],
  [/StatsBomb\s+open\s+data(\s*\(https?:\/\/\S+\))?/gi, "open event data"],
  [/StatsBomb/gi, "event data"],
  [/PFF\s*FC\s*tracking/gi, "broadcast tracking"],
  [/PFF\s*FC/gi, "tracking"],
  [/\bPFF\b/g, "tracking"],
  [/SkillCorner/gi, "broadcast tracking"],
  [/DFL\s*\/?\s*IDSSE|\bIDSSE\b/gi, "optical tracking"],
  [/gold_[a-z0-9_]+/gi, "the analytics tables"],
];

export function neutral(text: string | null | undefined): string {
  if (!text) return "";
  let out = text;
  for (const [re, rep] of RULES) out = out.replace(re, rep);
  return out;
}

/** Labels for provider benchmark fields. */
export const BENCHMARK = { xg: "Event xG", possession: "Event-data possession", agreement: "Agreement with event data" } as const;

/** Tracking source id -> neutral label. */
export function trackingLabel(source: string | null | undefined): string {
  const s = (source || "").toLowerCase();
  if (!s) return "No tracking";
  if (s.includes("idsse") || s.includes("dfl")) return "Optical tracking";
  return "Broadcast tracking";
}
