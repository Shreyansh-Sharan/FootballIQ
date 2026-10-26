"use client";

import { createContext, useContext } from "react";
import type { Resource, Status, TrackingFeed } from "@/lib/matchday/api";
import type { ClockSnap } from "@/lib/matchday/clock";
import type { Commentary } from "@/lib/matchday/commentary";
import type { UIStrings } from "@/lib/matchday/i18n";
import type { IdxInfo } from "@/lib/matchday/match";
import type { RenderCtx, View } from "@/lib/matchday/perspective";
import type { Lang, MatchEvent, MatchMeta, MatchState, MetaPlayer, MomentsResp, PlayerFocus, SeriesPoint, SeriesResp, SideIdx } from "@/lib/matchday/types";

export interface Matchday {
  matchId: string;
  meta: MatchMeta;
  metaStatus: Status | "fallback";
  lang: Lang;
  U: UIStrings;
  view: View;
  setView: (v: View) => void;
  clock: ClockSnap;
  players: Map<string, MetaPlayer>;
  ctx: RenderCtx;
  series: Resource<SeriesResp>;
  /** Series points up to the clock. */
  points: SeriesPoint[];
  /** Latest series point at or before the clock. */
  point: SeriesPoint | null;
  moments: Resource<MomentsResp>;
  events: Resource<MatchEvent[]>;
  state: { data: MatchState | null; status: Status };
  score: [number, number];
  tracking: TrackingFeed;
  idxInfo: Map<number, IdxInfo>;
  hasTracking: boolean;
  /** [home, away] UI colours from the kits. */
  colors: [string, string];
  /** Changes with theme or team colours; canvases re-read the palette. */
  palKey: string;
  commentary: Commentary;
  /** Favourite player, else a default from the favourite side. */
  focusId: string | null;
  focus: { data: PlayerFocus | null; status: Status };
  notify: (msg: string) => void;
}

export const MatchdayCtx = createContext<Matchday | null>(null);

export function useMD(): Matchday {
  const v = useContext(MatchdayCtx);
  if (!v) throw new Error("useMD outside the Matchday shell");
  return v;
}

export const teamVar = (side: SideIdx | null | undefined) => (side === 0 ? "var(--home)" : side === 1 ? "var(--away)" : "var(--accent)");
