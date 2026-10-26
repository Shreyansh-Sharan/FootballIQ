"use client";

// Events up to the replay clock, newest first; clicking one seeks to 6 s before it.

import { useMemo, useState } from "react";
import { CLOCK } from "@/lib/matchday/clock";
import { describeEvent, EV_COLOR, EV_FILTERS, EV_ICON, eventKind, minuteOf, sideOfTeam, type EvFilter } from "@/lib/matchday/live";
import { teamName, teamShort } from "@/lib/matchday/match";
import type { MatchEvent, SideIdx } from "@/lib/matchday/types";
import { teamVar, useMD } from "../context";

export default function EventTracker() {
  const { U, meta, lang, clock, events, state } = useMD();
  const [filter, setFilter] = useState<EvFilter>("primary");
  const [follow, setFollow] = useState(true);
  const t = clock.t;
  const kinds = EV_FILTERS.find(([k]) => k === filter)?.[1] ?? null;
  const rows = useMemo(() => {
    const out: { e: MatchEvent; k: ReturnType<typeof eventKind> }[] = [];
    const max = follow ? 60 : 200;
    for (let i = events.data.length - 1; i >= 0 && out.length < max; i--) {
      const e = events.data[i];
      if (e.match_elapsed_ms > t || e.is_shootout || e.type === "Starting XI") continue;
      const k = eventKind(e);
      if (kinds ? k != null && kinds.includes(k) : true) out.push({ e, k });
    }
    return out;
  }, [events.data, t, kinds, follow]);
  const tn = (id: string | null) => { const s = sideOfTeam(meta, id); return s == null ? "" : teamName(s ? meta.away : meta.home, lang); };
  const stats = state.data?.stats;
  return (
    <div className="evt">
      {stats && (
        <div className="ev-totals" title={U.evt.totalsTip}>
          {([0, 1] as SideIdx[]).map((k) => {
            const s = stats[k ? meta.away.team_id : meta.home.team_id];
            return (
              <div key={k} style={{ borderTopColor: teamVar(k) }}>
                <b style={{ color: teamVar(k) }}>{teamShort(k ? meta.away : meta.home, lang)}</b>
                <span className="mono">{s?.shots ?? 0} {U.evt.totals.sh} · {s?.shots_on_target ?? 0} {U.evt.totals.ot} · {s?.corners ?? 0} {U.evt.totals.ck} · {s?.fouls ?? 0} {U.evt.totals.fl} · {(s?.yellow_cards ?? 0) + (s?.red_cards ?? 0)} {U.evt.totals.crd}</span>
              </div>
            );
          })}
        </div>
      )}
      <div className="chips-row">
        <div className="chips" role="radiogroup" aria-label={U.evt.title}>
          {EV_FILTERS.map(([k]) => (
            <button key={k} role="radio" aria-checked={filter === k} className={`chipbtn ${filter === k ? "on" : ""}`} onClick={() => setFilter(k)}>{U.evt.filters[k]}</button>
          ))}
        </div>
        <label className="follow"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />{U.evt.follow}</label>
      </div>
      {rows.length === 0 ? <p className="dim" style={{ fontSize: 13 }}>{events.status === "ready" ? U.evt.nothing : U.loading}</p> : (
        <ol className="ev-list" aria-live={follow ? "polite" : "off"}>
          {rows.map(({ e, k }, i) => {
            const side = sideOfTeam(meta, e.team_id);
            return (
              <li key={e.event_id}>
                <button className={`ev-row ${i === 0 && follow ? "latest" : ""}`} style={{ borderLeftColor: side != null ? teamVar(side) : "var(--line)" }}
                  title={U.evt.jumpHint} onClick={() => CLOCK.seek(Math.max(0, e.match_elapsed_ms - 6000))}>
                  <span className="mono ev-min">{minuteOf(e.clock_label)}</span>
                  <span className="ev-kind" style={{ color: k ? EV_COLOR[k] : "var(--mute)" }}>{k ? EV_ICON[k] : "·"} {k ? U.evt.kinds[k] : e.type}</span>
                  <span className="ev-desc">{side != null && <b style={{ color: teamVar(side) }}>{teamShort(side ? meta.away : meta.home, lang)} </b>}{describeEvent(e, k, U, tn)}</span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
