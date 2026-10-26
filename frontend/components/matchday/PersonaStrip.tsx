"use client";

import { teamName } from "@/lib/matchday/match";
import type { Persona, View } from "@/lib/matchday/perspective";
import type { SideIdx } from "@/lib/matchday/types";
import { useMD } from "./context";
import { I } from "./Icons";
import { Kit } from "./Kit";

export function PersonaIcon({ view }: { view: Pick<View, "persona" | "fav"> }) {
  const { meta } = useMD();
  if (view.persona === "fan") return <Kit meta={meta} side={view.fav} />;
  const ic = view.persona === "player" ? I.player : I[view.persona];
  return <span className="av">{ic}</span>;
}

const ITEMS: { persona: Persona; fav?: SideIdx }[] = [
  { persona: "fan", fav: 0 }, { persona: "fan", fav: 1 }, { persona: "casual" }, { persona: "coach" }, { persona: "analyst" }, { persona: "player" },
];

export default function PersonaStrip() {
  const { U, view, setView, meta, lang } = useMD();
  const on = (it: (typeof ITEMS)[number]) => it.persona === view.persona && (it.persona !== "fan" || it.fav === view.fav);
  return (
    <div className="pstrip" role="radiogroup" aria-label={U.pick}>
      {ITEMS.map((it) => (
        <button key={`${it.persona}${it.fav ?? ""}`} className={`pchip ${on(it) ? "on" : ""}`} role="radio" aria-checked={on(it)}
          onClick={() => setView({ ...view, persona: it.persona, fav: it.fav ?? view.fav })}>
          <PersonaIcon view={{ persona: it.persona, fav: it.fav ?? view.fav }} />
          <span>
            {it.persona === "fan" ? U.fanOf(teamName(it.fav ? meta.away : meta.home, lang)) : U.personas[it.persona]}
            <small>{U.personaSub[it.persona]}</small>
          </span>
        </button>
      ))}
    </div>
  );
}
