// Inline SVG icons; colour follows currentColor.

const S = { fill: "none", stroke: "currentColor", strokeWidth: 2 } as const;

export const I = {
  live: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><circle cx="12" cy="12" r="3" /><path d="M6.3 6.3a8 8 0 0 0 0 11.4M17.7 6.3a8 8 0 0 1 0 11.4" /></svg>,
  stories: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><rect x="3" y="4" width="8" height="16" rx="2" /><rect x="13" y="4" width="8" height="16" rx="2" /></svg>,
  shape: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><path d="M4 7l6-3 10 4-2 10-9 2-5-6z" /><path d="M9 4v16M15 6v13" /></svg>,
  flow: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><path d="M3 12h3l2-6 4 12 3-9 2 3h4" /></svg>,
  player: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><circle cx="12" cy="7" r="3.5" /><path d="M5 21c1-4.5 4-6.5 7-6.5s6 2 7 6.5" /></svg>,
  recaps: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><path d="M5 4h14v16H5z" /><path d="M8 8h8M8 12h8M8 16h5" /></svg>,
  prematch: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><rect x="4" y="4" width="16" height="17" rx="2" /><path d="M8 2v4M16 2v4M4 10h16M9 15l2 2 4-4" /></svg>,
  tactical: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8" cy="9" r="1.6" /><circle cx="16" cy="9" r="1.6" /><circle cx="12" cy="15" r="1.6" /><path d="M9.5 9h5M9 10.5l2 3M15 10.5l-2 3" /></svg>,
  shots: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><path d="M3 20h18M6 20V9h12v11" /><circle cx="12" cy="4" r="2" /><path d="M12 6v7" /></svg>,
  models: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><path d="M3 20h18M5 16l4-5 4 3 6-8" /><circle cx="19" cy="6" r="1.5" /></svg>,
  ai: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><path d="M12 3l1.8 4.6L18 9.4l-4.2 1.8L12 16l-1.8-4.8L6 9.4l4.2-1.8z" /><path d="M18 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" /></svg>,
  broadcast: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><rect x="3" y="5" width="18" height="12" rx="2" /><path d="M8 21h8M6 13h7" /></svg>,
  play: <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M8 5v14l11-7z" fill="currentColor" /></svg>,
  pause: <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z" fill="currentColor" /></svg>,
  sun: <svg viewBox="0 0 24 24" width="18" height="18" {...S} aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>,
  moon: <svg viewBox="0 0 24 24" width="18" height="18" {...S} aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>,
  auto: <svg viewBox="0 0 24 24" width="18" height="18" {...S} aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" /></svg>,
  casual: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01" /></svg>,
  coach: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l2 2-2 2M12 15h5M15 8l2 2" /></svg>,
  analyst: <svg viewBox="0 0 24 24" {...S} aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>,
  volOn: <svg viewBox="0 0 24 24" width="18" height="18" {...S} aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4z" /><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12" /></svg>,
  volOff: <svg viewBox="0 0 24 24" width="18" height="18" {...S} aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4z" /><path d="M17 9l5 6M22 9l-5 6" /></svg>,
  mic: <svg viewBox="0 0 24 24" width="18" height="18" {...S} aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>,
  // player controls
  back10: <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M12 5V2L7 6l5 4V7a6 6 0 1 1-6 6H4a8 8 0 1 0 8-8z" fill="currentColor" /><text x="12" y="16.5" fontSize="6.5" textAnchor="middle" fill="currentColor" fontWeight="700">10</text></svg>,
  fwd10: <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M12 5V2l5 4-5 4V7a6 6 0 1 0 6 6h2a8 8 0 1 1-8-8z" fill="currentColor" /><text x="12" y="16.5" fontSize="6.5" textAnchor="middle" fill="currentColor" fontWeight="700">10</text></svg>,
  cc: <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="2" /><text x="12" y="15" fontSize="7" textAnchor="middle" fill="currentColor" fontWeight="700">CC</text></svg>,
  pip: <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><rect x="2" y="4" width="20" height="16" rx="2" fill="none" stroke="currentColor" strokeWidth="2" /><rect x="12" y="11" width="8" height="7" rx="1" fill="currentColor" /></svg>,
  theatre: <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><rect x="2" y="6" width="20" height="12" rx="2" fill="none" stroke="currentColor" strokeWidth="2" /></svg>,
  full: <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" fill="none" stroke="currentColor" strokeWidth="2" /></svg>,
  exitFull: <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" fill="none" stroke="currentColor" strokeWidth="2" /></svg>,
  expand: <svg viewBox="0 0 24 24" width="18" height="18" {...S} aria-hidden="true"><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" /></svg>,
  close: <svg viewBox="0 0 24 24" width="18" height="18" {...S} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>,
  search: <svg viewBox="0 0 24 24" width="16" height="16" {...S} aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>,
  spark: <svg viewBox="0 0 24 24" width="18" height="18" {...S} aria-hidden="true"><path d="M12 3l1.8 4.6L18 9.4l-4.2 1.8L12 16l-1.8-4.8L6 9.4l4.2-1.8z" /></svg>,
  bigplay: <svg viewBox="0 0 24 24" width="34" height="34" aria-hidden="true"><path d="M8 5v14l11-7z" fill="currentColor" /></svg>,
};

export type IconName = keyof typeof I;
