import type { Metadata } from "next";
import Landing from "@/components/matchday/analysis/Landing";
import "../matchday.css";
import "../matchday-analysis.css";

export const metadata: Metadata = {
  title: "FootballIQ · Every match, understood live",
  description: "Live football intelligence: tracking, calibrated models and an AI analyst that cites its evidence, on one match clock.",
};

export default function WelcomePage() {
  return <Landing />;
}
