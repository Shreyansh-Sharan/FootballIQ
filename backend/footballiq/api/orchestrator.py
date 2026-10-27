"""Agent team endpoints (docs/MULTI_AGENT_LLD.md §8): start a multi-agent run, poll it, list the roster."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from footballiq.agents.orchestrator import Orchestrator, RunContext, RunRequest, roster
from footballiq.agents.orchestrator.models import LANGS, PERSONAS
from footballiq.agents.tools import _minute
from footballiq.aliases import get_book


class TeamBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    at_ms: int = Field(..., ge=0, description="Replay clock; no agent sees anything after it")
    lang: str = Field("en", pattern=f"^({'|'.join(LANGS)})$")
    persona: str = Field("coach", pattern=f"^({'|'.join(PERSONAS)})$")
    fav_team_id: str | None = Field(None, max_length=64, description="Fan perspective: the supported team (public id)")
    wait: bool = Field(False, description="Block until the run finishes (otherwise poll GET /v1/agents/runs/{run_id})")


def minute_float(clock: str) -> float:
    """"68'" -> 68.0, "90+3'" -> 90.03 (orders stoppage time between 90 and 91)."""
    base, _, extra = clock.rstrip("'′").partition("+")
    try:
        return int(base) + (int(extra) / 100 if extra else 0)
    except ValueError:
        return 999.0


def context_factory(tools_for: Callable[[str, int], tuple[Any, str]]) -> Callable[[str, int], RunContext]:
    """Builds a RunContext from the AgentService (same clock-bounded tools as the single agents)."""
    def make(match_id: str, at_ms: int) -> RunContext:
        tools, context = tools_for(match_id, at_ms)
        tl = tools.timeline
        clock = _minute(tl.state_at(tools.at_ms)["clock_label"])
        book = get_book()
        return RunContext(tools=tools, context=context, clock=clock, minute=minute_float(clock),
                          team_names={t.team_id: t.name for t in (tl.match.home, tl.match.away)},
                          scrub=lambda s: book.scrub_text(s, match_id))
    return make


def orchestrator_router(get: Callable[[], Orchestrator], model_name: Callable[[], str | None]) -> APIRouter:
    r = APIRouter(tags=["agent team"])

    @r.get("/v1/agents/team")
    def team_roster() -> dict[str, Any]:
        """The specialists, their tool permissions and the pipeline (no credentials)."""
        return {"model": model_name(), "pipeline": ["planner", "specialists (parallel)", "synthesizer", "verifier"],
                "specialists": roster()}

    @r.post("/v1/matches/{match_id}/agents/team")
    def start_team(match_id: str, body: TeamBody) -> dict[str, Any]:
        book = get_book()
        fav = body.fav_team_id
        if fav and book.enabled:
            fav = book.to_canonical(fav) or fav
        req = RunRequest(match_id=match_id, at_ms=body.at_ms, question=body.question, lang=body.lang, persona=body.persona,
                         fav_team_id=fav)
        orch = get()
        try:
            run = orch.run_sync(req) if body.wait else orch.start(req)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return run.to_dict()

    @r.get("/v1/agents/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = get().get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="no such run (runs are kept in memory for a while)")
        return run.to_dict()

    return r
