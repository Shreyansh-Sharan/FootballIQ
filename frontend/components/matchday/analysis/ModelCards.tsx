"use client";

// Held-out metrics per model vs base-rate baselines, plus a calibration sparkline.
// "@no_priors" rows are the same model without Elo.

import type { ModelCards as Cards } from "@/lib/matchday/analysis";
import { modelLabel, pc, useA } from "./common";

const ORDER = ["xg", "xpass", "goal_10m", "goal_10m@no_priors", "corner_2m", "corner_2m@no_priors",
  "penalty_5m", "penalty_5m@no_priors", "win_probability", "win_probability@no_priors"];

function Reliability({ bins, label }: { bins?: { mean_pred: number; obs_rate: number }[]; label: string }) {
  if (!bins?.length) return <span className="mute">—</span>;
  const max = Math.max(0.05, ...bins.map((b) => Math.max(b.mean_pred, b.obs_rate)));
  const s = 34 / max;
  return (
    <svg viewBox="0 0 36 36" width={40} height={40} role="img" aria-label={label} style={{ display: "block", marginLeft: "auto" }}>
      <rect x={0.5} y={0.5} width={35} height={35} rx={4} fill="var(--panel2)" stroke="var(--line)" />
      <line x1={1} y1={35} x2={35} y2={1} stroke="var(--line2)" strokeDasharray="2 2" />
      <polyline fill="none" stroke="var(--accent)" strokeWidth={1.6} points={bins.map((b) => `${1 + b.mean_pred * s},${35 - b.obs_rate * s}`).join(" ")} />
    </svg>
  );
}

export default function ModelCards({ cards }: { cards: Cards }) {
  const A = useA();
  const f = (v: number | undefined, d = 3) => (v == null || Number.isNaN(v) ? "—" : v.toFixed(d));
  const trained = cards.models[0];
  const retro = cards.mode === "retrospective";
  const priors = A.priorsNames[cards.priors] ?? cards.priors.replace(/_/g, " ");
  const n = trained?.train_matches?.toLocaleString() ?? "?";
  const nameOf = (k: string) => (k.includes("@") ? A.withoutElo : A.modelNames[k] ?? k);
  return (
    <>
      <p className="an-mono-note">
        {retro
          ? A.cardsHeadRetro(cards.model_version ?? "—", n, priors, cards.test_competitions.length)
          : A.cardsHead(modelLabel(cards.model_version), n, trained?.train_window?.[0] ?? "—", trained?.train_window?.[1] ?? "—", priors, cards.test_competitions.length)}
      </p>
      <div className="scroll-x">
        <table className="ptable an-num" style={{ minWidth: 760 }}>
          <thead><tr>
            <th scope="col">{A.mc.model}</th><th scope="col" className="n">{A.mc.n}</th><th scope="col" className="n">{A.mc.base}</th>
            <th scope="col" className="n">{A.mc.ll}</th><th scope="col" className="n">{A.mc.llb}</th><th scope="col" className="n">{A.mc.brier}</th>
            <th scope="col" className="n">{A.mc.brierb}</th><th scope="col" className="n">{A.mc.auc}</th><th scope="col" className="n">{A.mc.ece}</th>
            <th scope="col" className="n">{A.mc.cal}</th>
          </tr></thead>
          <tbody>
            {ORDER.filter((k) => cards.metrics[k]).map((k) => {
              const m = cards.metrics[k];
              const winp = k.startsWith("win_probability");
              const sub = k.includes("@");
              return (
                <tr key={k} className={sub ? "an-faded" : ""}>
                  <th scope="row" style={{ fontWeight: sub ? 400 : 600, paddingLeft: sub ? 20 : 8 }}>{nameOf(k)}</th>
                  <td className="n">{m.n != null ? Math.round(m.n).toLocaleString() : "—"}</td>
                  <td className="n">{winp ? "—" : pc(m.base_rate, 1)}</td>
                  <td className="n">{f(m.log_loss)}</td>
                  <td className="n mute">{f(winp ? m.log_loss_uniform : m.log_loss_base_rate)}</td>
                  <td className="n">{f(winp ? m.brier_multiclass : m.brier)}</td>
                  <td className="n mute">{winp ? "—" : f(m.brier_base_rate)}</td>
                  <td className="n">{f(m.auc)}</td>
                  <td className="n">{f(m.ece)}</td>
                  <td className="n"><Reliability bins={cards.calibration[k]} label={A.calAria(nameOf(k))} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="an-small">{retro ? A.cardsNoteRetro : A.cardsNoteStrict}{A.cardsNote}</p>
    </>
  );
}
