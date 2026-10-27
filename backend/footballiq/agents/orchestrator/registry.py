"""The analyst team: specialists (role, tool permissions, output contract) and the planner / synthesizer prompts.

Adding a specialist = one ``Specialist`` entry here (and, if it needs data no tool returns, a new ``tool_*`` method in
footballiq/agents/tools.py plus its spec in TOOL_SPECS). The planner sees each specialist's ``brief``.
"""

from __future__ import annotations

from dataclasses import dataclass

from footballiq.agents.definitions import COMMON_RULES
from footballiq.agents.tools import TOOL_SPECS

LANG_NAME = {"en": "English", "es": "Spanish (Latin American football vocabulary)", "hi": "Hindi in Devanagari, keeping English "
             "football terms the way Indian broadcasts do (pass, cross, corner, goalkeeper written in Devanagari)"}
PERSONA = {
    "coach": "the head coach on the bench: decisive, tactical, one coachable action",
    "analyst": "a performance analyst: numbers first, with the model or source for each",
    "fan": "a supporter of {team}: warm and partisan ('we', 'us' for {team}) but honest about the numbers",
    "casual": "a casual viewer: plain words, no jargon, explain any metric in a few words",
    "player": "a player: concrete, about what to do on the pitch next",
}


@dataclass(frozen=True)
class Specialist:
    key: str
    title: str
    brief: str                    # one line for the planner
    focus: str                    # role instructions
    tools: tuple[str, ...]        # tool permissions (names from TOOL_SPECS)
    max_tool_calls: int = 5


SPECIALISTS: dict[str, Specialist] = {s.key: s for s in (
    Specialist(
        "tactician", "Tactical analyst",
        "team shape and formations (detected from tracking vs the team sheet), formation switches, possession, width and depth, "
        "who controls territory, pressing and tactical shifts",
        "You read shape and control. Compare the detected formation with the declared one, note confirmed switches and when "
        "they happened, possession (ours vs the benchmark), width/depth in possession, and what the shape means for the next "
        "phase.",
        ("get_match_context", "get_tactical_shape", "get_match_stats", "get_key_events")),
    Specialist(
        "threat", "Chance & threat analyst",
        "shots, chance quality (xG), finishing, big chances, set pieces and where the next goal is likely to come from",
        "You read chances. Use shot quality (xG per shot, big chances, distance, angle, defenders in the cone), finishing "
        "(goals vs xG), recent shots and set pieces, and the goal-in-10' forecast with its drivers.",
        ("get_match_context", "get_shot_quality", "get_forecasts", "get_key_events")),
    Specialist(
        "forecaster", "Game-state forecaster",
        "win/draw/loss probabilities, goal / corner / penalty forecasts and their drivers, expected goals left, pre-match "
        "strength (Elo, form)",
        "You read the models. Give the outcome probabilities at the end of the phase with uncertainty, the event forecasts "
        "and their top drivers, and how game state (score, time left, cards) moves them. Say these are model estimates.",
        ("get_match_context", "get_forecasts", "get_match_stats")),
    Specialist(
        "performance", "Performance & fitness coach",
        "individual players: form and dips, fatigue and physical load, card risk, substitutions (who off, who on) and the "
        "best player for a situation (penalty, corner, free kick, counter, defending a lead)",
        "You read players. Use player form flags and their reasons, physical output (distance, high-speed running, sprints), "
        "card risk, ranked substitution options and the best player for a situation. These are rule-based coach analytics, "
        "not a trained model: never cite a model version for them.",
        ("get_match_context", "get_player_form", "get_physical", "get_substitution_options", "get_best_player",
         "get_key_events"), max_tool_calls=6),
)}

SPECIALIST_OUTPUT = """
Your answer goes to the lead analyst, not to the user. Reply with ONLY one JSON object:
{"summary": "one sentence that answers your sub-question",
 "findings": [{"claim": "one fact or inference", "evidence": "which tool and the exact numbers", "confidence": "high|medium|low"}],
 "recommendation": "one concrete, coachable action, or null",
 "data_gaps": ["data you needed but a tool said was unavailable"]}
2 to 4 findings. Every number must be copied exactly from a tool output in this conversation. English only.
"""

PLANNER = COMMON_RULES + """
Role: lead analyst. You do not answer; you decide which specialists work on the question and what each must find out.

Specialists:
{roster}

Pick the 1 to 3 specialists the question really needs (4 only for broad "what's going on / what should we do" questions).
Give each a precise sub-question in English that it can answer with its own data. Reply with ONLY one JSON object:
{{"intent": "a few words: what the user wants", "tasks": [{{"specialist": "<key>", "question": "<sub-question>"}}],
  "reason": "one short sentence on why these specialists"}}
"""

SYNTHESIZER = COMMON_RULES + """
Role: lead analyst. Your specialists have reported (JSON below). Write the single answer the user sees, for {persona}.
Language: {lang}.

Rules:
- Use only facts and numbers that appear in the reports; copy numbers exactly. If a specialist reported a data gap, say
  briefly what is not available instead of guessing.
- If two specialists disagree, say so and say which evidence is stronger.
- Format (under 170 words unless the user asks for more):
  first line: the answer in one sentence.
  then 2-4 short bullets, each one supporting reason with its number and source (match events, tracking, our model, benchmark xG).
  then "Recommendation:" one concrete action (who, what, where), if the question calls for one.
  then "Confidence: high|medium|low - why".
- Keep the labels "Recommendation:" and "Confidence:" in English even when you write in another language.
"""

REVISE = """The following numbers or minutes in your answer are not in the specialists' reports or are later than the
current minute ({clock}): {problems}. Rewrite the answer without them (use only numbers from the reports). Same format."""


def tool_specs(names: tuple[str, ...]) -> list[dict]:
    allowed = set(names)
    return [t for t in TOOL_SPECS if t["function"]["name"] in allowed]


def roster_text() -> str:
    return "\n".join(f"- {s.key}: {s.title} - {s.brief}" for s in SPECIALISTS.values())


def roster() -> list[dict]:
    return [{"key": s.key, "title": s.title, "brief": s.brief, "tools": list(s.tools)} for s in SPECIALISTS.values()]
