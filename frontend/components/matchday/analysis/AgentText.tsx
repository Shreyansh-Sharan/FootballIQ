"use client";

// Minimal markdown for agent answers (bullets, **bold**, headings, Recommendation / Confidence lines).

import { neutral } from "@/lib/matchday/neutral";

const bold = (s: string) => s.split(/\*\*(.+?)\*\*/g).map((p, i) => (i % 2 ? <b key={i}>{p}</b> : p));

export default function AgentText({ text }: { text: string }) {
  const lines = neutral(text).split("\n").map((l) => l.trim()).filter(Boolean);
  return (
    <div className="an-at">
      {lines.map((l, i) => {
        if (/^#{1,6}\s/.test(l)) return <div key={i} className="lead">{bold(l.replace(/^#{1,6}\s+/, ""))}</div>;
        if (/^([-*•]|\d+[.)])\s/.test(l)) return <div key={i} className="bul"><span>{bold(l.replace(/^([-*•]|\d+[.)])\s+/, ""))}</span></div>;
        if (/^\**recommendation:?\**/i.test(l)) return <div key={i} className="an-rec">{bold(l)}</div>;
        if (/^\**confidence:?\**/i.test(l)) return <div key={i} className="an-conf">{l.replace(/\*\*/g, "")}</div>;
        return <div key={i} className={i === 0 ? "lead" : undefined}>{bold(l)}</div>;
      })}
    </div>
  );
}
