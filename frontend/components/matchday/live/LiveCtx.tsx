"use client";

// State of the one persistent live pitch and the insight pop-ups; provided by the Shell.

import { createContext, useContext, type MutableRefObject } from "react";
import type { AiTake, Insight } from "@/lib/matchday/analysis";
import type { CamMode, InsightSettings, MiniSize, Overlays } from "@/lib/matchday/live";
import type { SideIdx } from "@/lib/matchday/types";
import type { HitList } from "../Pitch";

/** Moment lower third shown on the live pitch. */
export interface Lower { id: string; t_ms: number; clock: string; side: SideIdx | null; h: string; b: string; kind: string; player: string | null }

export interface LiveInsights {
  all: Insight[];
  status: string;
  toasts: Insight[];
  dismiss: (id: string) => void;
  settings: InsightSettings;
  setSettings: (s: InsightSettings) => void;
  takes: Record<string, AiTake>;
  requestAi: (id: string) => void;
}

export interface LiveCtl {
  ov: Overlays; setOv: (o: Overlays) => void;
  /** Functional update, safe for quick repeated clicks. */
  toggleOv: (k: keyof Overlays) => void;
  cam: CamMode; setCam: (c: CamMode) => void;
  /** Shape shown: 0 home, 1 away, 2 both. */
  team: 0 | 1 | 2; setTeam: (t: 0 | 1 | 2) => void;
  /** Selected player on the pitch (tracking idx). */
  sel: number | null; setSel: (i: number | null) => void;
  theatre: boolean; setTheatre: (v: boolean) => void;
  captions: boolean; setCaptions: (v: boolean) => void;
  help: boolean; setHelp: (v: boolean) => void;
  palette: boolean; setPalette: (v: boolean) => void;
  mini: MiniSize; setMini: (s: MiniSize) => void;
  miniClosed: boolean; setMiniClosed: (v: boolean) => void;
  fullscreen: boolean; toggleFullscreen: () => void;
  pipOn: boolean; pipOk: boolean; togglePip: () => void;
  /** The Live tab's slot for the stage. */
  setSlot: (el: HTMLDivElement | null) => void;
  canvasRef: MutableRefObject<HTMLCanvasElement | null>;
  hitsRef: MutableRefObject<HitList | null>;
  zoomRef: MutableRefObject<((d: number) => void) | null>;
  lower: Lower | null;
  insights: LiveInsights;
}

export const LiveCtx = createContext<LiveCtl | null>(null);

export function useLive(): LiveCtl {
  const v = useContext(LiveCtx);
  if (!v) throw new Error("useLive outside the Matchday shell");
  return v;
}
