import type { Metadata } from "next";
import Shell from "@/components/matchday/Shell";
import "./matchday.css";

export const metadata: Metadata = {
  title: "FootballIQ Matchday",
  description: "One match, told for you: live pitch, shape, control and rhythm, perspectives, recaps, broadcast cues and live commentary.",
};

export default function Page() {
  return <Shell />;
}
