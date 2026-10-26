import type { Metadata } from "next";
import { fontVars } from "./fonts";

// No global CSS: / imports matchday.css and /lab imports globals.css, so the two styles never mix.

export const metadata: Metadata = {
  title: "FootballIQ",
  description: "Live football intelligence: tracking, models and AI coaching in real time",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" className={fontVars}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Condensed:wght@500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
