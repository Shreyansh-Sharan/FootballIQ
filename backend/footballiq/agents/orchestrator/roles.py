"""The three model-backed roles: planner (route), specialist (tool loop) and synthesizer (one answer)."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

from footballiq.agents.orchestrator.blackboard import Blackboard, ToolDenied
from footballiq.agents.orchestrator.llm import ChatModel, ModelError, assistant_tool_calls, parse_json, tool_message
from footballiq.agents.orchestrator.models import Plan, Task, TaskStatus
from footballiq.agents.orchestrator.registry import (
    LANG_NAME, PERSONA, PLANNER, REVISE, SPECIALIST_OUTPUT, SPECIALISTS, SYNTHESIZER, roster_text, tool_specs,
)
from footballiq.agents.definitions import COMMON_RULES

log = logging.getLogger(__name__)
MAX_TASKS = 4

# keyword routing used when the planner's output is unusable (and for an obvious single-domain question)
ROUTES: list[tuple[str, tuple[str, ...]]] = [
    ("performance", ("sub", "substitut", "tired", "fatigue", "fitness", "player", "penalty taker", "who should", "card risk",
                     "booked", "yellow", "in form", "out of form", "player form", "dip", "sprint", "distance", "best player",
                     "free kick", "corner taker")),
    ("tactician", ("shape", "formation", "tactic", "press", "control", "possession", "width", "depth", "block", "line",
                   "system", "4-", "3-", "switch")),
    ("threat", ("shot", "chance", "xg", "finish", "goal come", "next goal", "set piece", "threat", "danger", "corner")),
    ("forecaster", ("win", "probab", "likely", "odds", "forecast", "draw", "favourite", "favorite", "predict", "model")),
]


def fallback_plan(question: str) -> Plan:
    q = question.lower()
    keys = [k for k, words in ROUTES if any(w in q for w in words)]
    if not keys:
        keys = ["tactician", "threat", "forecaster"]       # broad question: the three team-level views
    return Plan(intent="answer the question", source="fallback", reason="keyword routing",
                tasks=[Task(k, question) for k in dict.fromkeys(keys)][:MAX_TASKS])


def plan(model: ChatModel, question: str, context: str, add_usage: Callable[[dict], None]) -> Plan:
    msgs = [{"role": "system", "content": PLANNER.format(roster=roster_text()) + "\n" + context},
            {"role": "user", "content": question}]
    try:
        resp = model.complete(msgs, json_mode=True, max_tokens=900, role="planner")
        add_usage(resp.usage)
        d = parse_json(resp.content) or {}
    except ModelError as exc:
        log.warning("planner failed, keyword routing: %s", exc)
        return fallback_plan(question)
    tasks, seen = [], set()
    for t in d.get("tasks") or []:
        key = (t or {}).get("specialist")
        sub = str((t or {}).get("question") or "").strip()
        if key in SPECIALISTS and key not in seen and sub:
            seen.add(key)
            tasks.append(Task(key, sub[:500]))
    if not tasks:
        return fallback_plan(question)
    return Plan(intent=str(d.get("intent") or "")[:120], tasks=tasks[:MAX_TASKS], reason=str(d.get("reason") or "")[:300])


def run_specialist(model: ChatModel, task: Task, board: Blackboard, context: str, deadline: float,
                   add_usage: Callable[[dict], None], on_tool: Callable[[Task, dict], None]) -> dict[str, Any]:
    """Tool-calling loop for one specialist, bounded by its tool budget and the run deadline."""
    spec = SPECIALISTS[task.specialist]
    tools = tool_specs(spec.tools)
    ctx_text, _ = board.call("get_match_context", None, spec.tools)            # shared, cached for the whole team
    system = (COMMON_RULES + f"\nRole: {spec.title} in the FootballIQ analyst team. {spec.focus}\n" + SPECIALIST_OUTPUT +
              "\n" + context + "\nMatch context (from get_match_context): " + ctx_text)
    msgs: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": task.question}]
    calls = 0
    for _ in range(spec.max_tool_calls + 2):
        if time.time() > deadline:
            raise TimeoutError("run deadline reached")
        budget_left = calls < spec.max_tool_calls
        resp = model.complete(msgs, tools=tools if budget_left else None, json_mode=not budget_left, max_tokens=1400,
                              role=spec.key)
        add_usage(resp.usage)
        task.model_calls += 1
        if not resp.tool_calls:
            report = parse_json(resp.content)
            if report is None:
                report = {"summary": resp.content.strip()[:600], "findings": [], "recommendation": None, "data_gaps": []}
            return normalise_report(report)
        msgs.append(assistant_tool_calls(resp))
        for call in resp.tool_calls:
            calls += 1
            if calls > spec.max_tool_calls:
                out, cached = json.dumps({"unavailable": "tool budget used up: answer with what you have"}), False
            else:
                try:
                    out, cached = board.call(call.name, call.arguments, spec.tools)
                except ToolDenied:
                    out, cached = json.dumps({"error": f"{call.name} is not one of your tools"}), False
            info = {"name": call.name, "arguments": _args(call.arguments), "cached": cached, "chars": len(out),
                    "ok": '"unavailable"' not in out[:40] and '"error"' not in out[:20]}
            task.tool_calls.append(info)
            on_tool(task, info)
            msgs.append(tool_message(call, out))
        if calls >= spec.max_tool_calls:
            msgs.append({"role": "user", "content": "Tool budget used. Reply now with the JSON report."})
    raise ModelError(f"{spec.key} did not finish within its tool budget")


def _args(arguments: str) -> dict[str, Any]:
    try:
        v = json.loads(arguments or "{}")
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}


def normalise_report(r: dict[str, Any]) -> dict[str, Any]:
    findings = []
    for f in r.get("findings") or []:
        if isinstance(f, dict) and f.get("claim"):
            conf = f.get("confidence") if f.get("confidence") in ("high", "medium", "low") else "medium"
            findings.append({"claim": str(f["claim"])[:400], "evidence": str(f.get("evidence") or "")[:400], "confidence": conf})
    rec = r.get("recommendation")
    return {"summary": str(r.get("summary") or "")[:600], "findings": findings[:5],
            "recommendation": str(rec)[:400] if rec and str(rec).lower() != "null" else None,
            "data_gaps": [str(g)[:200] for g in (r.get("data_gaps") or []) if g][:5]}


def persona_text(persona: str, fav_team_name: str | None) -> str:
    text = PERSONA.get(persona, PERSONA["coach"])
    return text.format(team=fav_team_name or "the home side")


def synthesize(model: ChatModel, question: str, tasks: list[Task], context: str, lang: str, persona: str,
               add_usage: Callable[[dict], None], revise: tuple[str, list[str], str] | None = None) -> str:
    reports = {SPECIALISTS[t.specialist].title: t.report for t in tasks if t.report}
    gaps = [f"{SPECIALISTS[t.specialist].title}: {t.error or t.status.value}" for t in tasks if not t.report]
    system = SYNTHESIZER.format(persona=persona, lang=LANG_NAME.get(lang, "English")) + "\n" + context
    user = (f"User question: {question}\n\nSpecialist reports:\n{json.dumps(reports, ensure_ascii=False)}"
            + (f"\n\nSpecialists that could not report: {gaps}" if gaps else ""))
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if revise is not None:
        draft, problems, clock = revise
        msgs += [{"role": "assistant", "content": draft},
                 {"role": "user", "content": REVISE.format(problems=", ".join(problems), clock=clock)}]
    resp = model.complete(msgs, max_tokens=1200, role="synthesizer")
    add_usage(resp.usage)
    text = resp.content.strip()
    if not text:
        raise ModelError("synthesizer returned no text")
    return re.sub(r"\n{3,}", "\n\n", text)


def tasks_status_ok(tasks: list[Task]) -> bool:
    return any(t.status == TaskStatus.DONE and t.report for t in tasks)
