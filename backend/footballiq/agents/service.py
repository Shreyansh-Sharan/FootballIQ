"""Runs the Foundry agents for one match at one replay clock."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from footballiq.agents.definitions import run_context
from footballiq.agents.foundry import FoundryClient, RunResult
from footballiq.agents.tools import MatchTools, _minute
from footballiq.aliases import get_book

CARD_KEYS = ("headline", "what_is_happening", "main_risk", "one_action", "confidence", "evidence")


def parse_card(text: str) -> dict[str, Any] | None:
    """Extract the explainer's JSON card, tolerating code fences or surrounding prose."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        card = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(card, dict) or not card.get("headline"):
        return None
    card["evidence"] = [e for e in card.get("evidence") or [] if isinstance(e, dict)][:6]
    card["confidence"] = card.get("confidence") if card.get("confidence") in ("high", "medium", "low") else "low"
    return {k: card.get(k) for k in CARD_KEYS}


class AgentService:
    def __init__(self, store: Any, client: FoundryClient, predictions: Callable[[], Any] | None = None,
                 tactical: Callable[[], Any] | None = None, coach: Any = None):
        self.store, self.client, self.coach = store, client, coach
        lh = getattr(store, "lh", None)
        if predictions is None and lh is not None:
            from footballiq.predictions import PredictionStore
            ps = PredictionStore(lh)
            predictions = lambda: ps
        if tactical is None and lh is not None:
            from footballiq.tactical import TacticalStore
            ts = TacticalStore(lh)
            tactical = lambda: ts
        self._predictions, self._tactical = predictions, tactical

    def _tools(self, match_id: str, at_ms: int) -> tuple[MatchTools, str]:
        tl = self.store.get(match_id)
        if tl is None:
            raise KeyError(match_id)
        at_ms = max(0, min(int(at_ms), tl.match.duration_ms))
        ps = self._predictions() if self._predictions else None
        tools = MatchTools(tl, at_ms, predictions=ps.latest if ps else None, model_xg=ps.xg_by_event if ps else None,
                           tactical=self._tactical() if self._tactical else None, coach=self.coach)
        st = tl.state_at(at_ms)
        m = tl.match
        ctx = run_context({"match_id": match_id, "home": m.home.name, "away": m.away.name, "competition": m.competition,
                           "date": m.kickoff_source[:10], "minute": _minute(st["clock_label"]), "clock": st["clock_label"],
                           "period": st["period_label"],
                           "score": f"{m.home.name} {st['score'][m.home.team_id]}-{st['score'][m.away.team_id]} {m.away.name}"})
        return tools, ctx

    @staticmethod
    def _payload(r: RunResult, at_ms: int, clock: str) -> dict[str, Any]:
        return {"thread_id": r.thread_id, "run_id": r.run_id, "agent_id": r.agent_id, "model": r.model, "at_ms": at_ms,
                "replay_clock": clock, "tool_calls": r.tool_calls, "usage": r.usage, "seconds": r.seconds}

    def ask(self, match_id: str, at_ms: int, question: str, thread_id: str | None = None) -> dict[str, Any]:
        tools, ctx = self._tools(match_id, at_ms)
        question = get_book().scrub_text(question.strip()[:2000], match_id)   # the model only sees fictional names
        r = self.client.run("strategist", question, tools, ctx, thread_id=thread_id)
        return {"answer": r.text, **self._payload(r, tools.at_ms, tools.timeline.clock_label_at(tools.at_ms))}

    def explain(self, match_id: str, at_ms: int, focus: str | None = None) -> dict[str, Any]:
        """Moment card; ``focus`` is an auto insight for the agent to assess."""
        tools, ctx = self._tools(match_id, at_ms)
        msg = "Explain this moment for the bench."
        if focus:
            focus = get_book().scrub_text(focus, match_id)   # insight text can carry real names
            msg += (f" The analysis system just flagged this signal - explain whether it matters and what to do about it, using the "
                    f"tools to check it: {focus[:800]}")
        r = self.client.run("explainer", msg, tools, ctx)
        return {"card": parse_card(r.text), "raw": r.text, **self._payload(r, tools.at_ms, tools.timeline.clock_label_at(tools.at_ms))}
