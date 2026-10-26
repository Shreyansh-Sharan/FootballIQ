// Self-hosted fonts as CSS variables on <html>; matchday.css maps them to --display / --body / --mono.
import { JetBrains_Mono, Noto_Sans_Devanagari, Rubik, Saira_Extra_Condensed } from "next/font/google";

export const saira = Saira_Extra_Condensed({ subsets: ["latin", "latin-ext"], weight: ["600", "700", "800", "900"], variable: "--font-saira", display: "swap" });
export const rubik = Rubik({ subsets: ["latin", "latin-ext"], weight: ["400", "500", "600", "700"], variable: "--font-rubik", display: "swap" });
export const jbmono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "600"], variable: "--font-jbmono", display: "swap" });
export const deva = Noto_Sans_Devanagari({ subsets: ["devanagari"], weight: ["400", "600", "700", "800"], variable: "--font-deva", display: "swap", preload: false });

export const fontVars = [saira.variable, rubik.variable, jbmono.variable, deva.variable].join(" ");
