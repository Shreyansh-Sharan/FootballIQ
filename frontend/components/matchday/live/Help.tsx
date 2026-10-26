"use client";

// Keyboard shortcuts overlay ("?"); modal, closes on Esc or an outside click.

import { useEffect, useRef } from "react";
import { useMD } from "../context";
import { useLive } from "./LiveCtx";

export default function Help() {
  const { U } = useMD();
  const lv = useLive();
  const btn = useRef<HTMLButtonElement>(null);
  const { setHelp } = lv;
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    btn.current?.focus();
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); setHelp(false); } };
    window.addEventListener("keydown", k);
    return () => { window.removeEventListener("keydown", k); prev?.focus?.(); };
  }, [setHelp]);
  return (
    <div className="pal-bg" onMouseDown={(e) => { if (e.target === e.currentTarget) lv.setHelp(false); }}>
      <div className="help" role="dialog" aria-modal="true" aria-labelledby="help-h">
        <h3 id="help-h">{U.help.title}</h3>
        <dl>
          {U.help.rows.map(([k, v]) => (
            <div key={k}><dt><kbd>{k}</kbd></dt><dd>{v}</dd></div>
          ))}
        </dl>
        <button ref={btn} className="btn" onClick={() => lv.setHelp(false)}>{U.close}</button>
      </div>
    </div>
  );
}
