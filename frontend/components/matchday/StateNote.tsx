"use client";

import type { Status } from "@/lib/matchday/api";
import { useMD } from "./context";

/** Status note for a panel whose data is not ready. */
export function StateNote({ status, empty, small }: { status: Status | "none" | "fallback"; empty?: string; small?: boolean }) {
  const { U } = useMD();
  const text = status === "loading" ? U.loading : status === "missing" ? U.unavailable : status === "error" ? U.failed : empty ?? U.unavailable;
  return (
    <div className={`note ${status === "error" ? "err" : ""} ${small ? "small" : ""}`} role="status">
      {status === "loading" && <span className="spin" aria-hidden="true" />}
      <span>{text}</span>
    </div>
  );
}

/** Shape panels on a match without tracking. */
export function NoTracking() {
  const { U } = useMD();
  return (
    <div className="note notrack" role="status">
      <b>{U.noTracking}</b>
      <span>{U.noTrackingSub}</span>
    </div>
  );
}

export const notReady = (status: Status) => status !== "ready";
