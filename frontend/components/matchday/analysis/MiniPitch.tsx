"use client";

// 105 x 68 m SVG pitch for the tactical boards (1 user unit = 1 m).

export const PW = 105;
export const PH = 68;

export default function MiniPitch({ children, label, defs }: { children?: React.ReactNode; label: string; defs?: React.ReactNode }) {
  const stripes = 12;
  return (
    <svg viewBox="-4 -4 113 76" role="img" aria-label={label}>
      {defs && <defs>{defs}</defs>}
      <rect x={-4} y={-4} width={113} height={76} fill="var(--pitch-edge)" />
      {Array.from({ length: stripes }, (_, i) => (
        <rect key={i} x={(i * PW) / stripes} y={0} width={PW / stripes + 0.05} height={PH} fill={i % 2 ? "var(--pitch-b)" : "var(--pitch-a)"} />
      ))}
      <g fill="none" stroke="var(--chalk)" strokeWidth={0.35}>
        <rect x={0} y={0} width={PW} height={PH} />
        <line x1={PW / 2} y1={0} x2={PW / 2} y2={PH} />
        <circle cx={PW / 2} cy={PH / 2} r={9.15} />
        <rect x={0} y={13.84} width={16.5} height={40.32} /><rect x={PW - 16.5} y={13.84} width={16.5} height={40.32} />
        <rect x={0} y={24.84} width={5.5} height={18.32} /><rect x={PW - 5.5} y={24.84} width={5.5} height={18.32} />
      </g>
      {children}
    </svg>
  );
}
