"""Multi-agent orchestrator: a planner routes a question to specialist analysts that work in parallel on a shared,
clock-bounded tool blackboard; a synthesizer writes one answer and a deterministic verifier checks it.
Design: docs/MULTI_AGENT_LLD.md."""

from footballiq.agents.orchestrator.engine import Limits, Orchestrator, RunContext
from footballiq.agents.orchestrator.models import Run, RunRequest, RunStatus
from footballiq.agents.orchestrator.registry import SPECIALISTS, roster

__all__ = ["Limits", "Orchestrator", "Run", "RunContext", "RunRequest", "RunStatus", "SPECIALISTS", "roster"]
