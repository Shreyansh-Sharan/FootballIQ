"""Orchestrator: plan -> specialists in parallel (shared blackboard) -> synthesize -> verify (one revision) -> answer.

Runs execute in a bounded worker pool and are kept in an in-memory store so clients can poll their progress
(``Run.to_dict()`` is safe to serialise at any moment). Identical requests at the same 15-second clock bucket share one
run (de-duplication + short-term cache).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable

from footballiq.agents.orchestrator import roles
from footballiq.agents.orchestrator.blackboard import Blackboard
from footballiq.agents.orchestrator.llm import ChatModel, ModelError
from footballiq.agents.orchestrator.models import LANGS, PERSONAS, Run, RunRequest, RunStatus, Task, TaskStatus
from footballiq.agents.orchestrator.verifier import neutralise, verify
from footballiq.agents.tools import MatchTools

log = logging.getLogger(__name__)


@dataclass
class RunContext:
    """What one run needs about the match at its clock (built by the API from the AgentService)."""
    tools: MatchTools                 # clock-bounded, alias-translating tool executor
    context: str                      # replay context line for every prompt
    clock: str                        # scoreboard minute, e.g. "68'" or "90+3'"
    minute: float                     # 68 / 90.03, for the no-future check
    team_names: dict[str, str] = field(default_factory=dict)
    scrub: Callable[[str], str] = lambda s: s     # fictional-name scrubber for user text and the final answer


@dataclass
class Limits:
    run_timeout_s: float = 150.0      # whole run
    synth_reserve_s: float = 35.0     # time kept back for synthesis + verification
    max_concurrent_runs: int = 3
    max_specialist_workers: int = 8
    cache_ttl_s: float = 600.0
    bucket_ms: int = 15_000
    max_runs_kept: int = 200


class Orchestrator:
    def __init__(self, model: ChatModel, context_factory: Callable[[str, int], RunContext], limits: Limits | None = None):
        self.model = model
        self.context_factory = context_factory
        self.limits = limits or Limits()
        self._runs: OrderedDict[str, Run] = OrderedDict()
        self._by_key: dict[tuple, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self._run_pool = ThreadPoolExecutor(self.limits.max_concurrent_runs, thread_name_prefix="team-run")
        self._task_pool = ThreadPoolExecutor(self.limits.max_specialist_workers, thread_name_prefix="team-agent")

    # ------------------------------------------------------------------ public API
    def start(self, req: RunRequest) -> Run:
        """Queue a run (or return the identical one already running / recently finished)."""
        req = self._validate(req)
        key = req.cache_key(self.limits.bucket_ms)
        with self._lock:
            hit = self._by_key.get(key)
            if hit and hit[0] in self._runs:
                run = self._runs[hit[0]]
                fresh = time.time() - hit[1] < self.limits.cache_ttl_s
                if not run.status.terminal or (run.status == RunStatus.DONE and fresh):
                    return run
            run = Run(request=req, model=getattr(self.model, "name", None))
            self._runs[run.id] = run
            self._by_key[key] = (run.id, time.time())
            while len(self._runs) > self.limits.max_runs_kept:
                old, _ = self._runs.popitem(last=False)
                self._by_key = {k: v for k, v in self._by_key.items() if v[0] != old}
        self._run_pool.submit(self._execute, run)
        return run

    def run_sync(self, req: RunRequest, timeout_s: float | None = None) -> Run:
        run = self.start(req)
        end = time.time() + (timeout_s or self.limits.run_timeout_s + 30)
        while not run.status.terminal and time.time() < end:
            time.sleep(0.2)
        return run

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    # ------------------------------------------------------------------ pipeline
    @staticmethod
    def _validate(req: RunRequest) -> RunRequest:
        q = " ".join((req.question or "").split())
        if not q:
            raise ValueError("question is empty")
        req.question = q[:2000]
        req.lang = req.lang if req.lang in LANGS else "en"
        req.persona = req.persona if req.persona in PERSONAS else "coach"
        req.at_ms = max(0, int(req.at_ms))
        return req

    def _execute(self, run: Run) -> None:
        run.started = time.time()
        deadline = run.started + self.limits.run_timeout_s
        try:
            ctx = self.context_factory(run.request.match_id, run.request.at_ms)
            run.clock = ctx.clock
            question = ctx.scrub(run.request.question)

            run.status = RunStatus.PLANNING
            run.plan = roles.plan(self.model, question, ctx.context, run.add_usage)
            run.event("plan", "planner", f"{run.plan.source}: " + ", ".join(t.specialist for t in run.plan.tasks)
                      + (f" - {run.plan.reason}" if run.plan.reason else ""))

            run.status = RunStatus.RUNNING
            board = Blackboard(ctx.tools)
            self._run_specialists(run, board, ctx, deadline - self.limits.synth_reserve_s)
            if not roles.tasks_status_ok(run.plan.tasks):
                raise ModelError("no specialist could report")

            run.status = RunStatus.SYNTHESISING
            persona = roles.persona_text(run.request.persona, ctx.team_names.get(run.request.fav_team_id or ""))
            answer = roles.synthesize(self.model, question, run.plan.tasks, ctx.context, run.request.lang, persona, run.add_usage)
            run.event("synth", "synthesizer", f"{len(answer.split())} words")

            run.status = RunStatus.VERIFYING
            evidence = board.outputs + [json.dumps(t.report, ensure_ascii=False) for t in run.plan.tasks if t.report] + [ctx.context]
            ver = verify(answer, evidence, ctx.minute)
            run.event("verify", "verifier", f"{ver.status}: {ver.numbers_checked} numbers checked"
                      + (f", unverified {ver.unverified_numbers}" if ver.unverified_numbers else "")
                      + (f", future minutes {ver.future_minutes}" if ver.future_minutes else ""))
            if (ver.unverified_numbers or ver.future_minutes) and time.time() < deadline - 10:
                problems = ver.unverified_numbers + ver.future_minutes
                revised = roles.synthesize(self.model, question, run.plan.tasks, ctx.context, run.request.lang, persona,
                                           run.add_usage, revise=(answer, problems, ctx.clock))
                ver2 = verify(revised, evidence, ctx.minute)
                run.event("revise", "synthesizer", f"{ver2.status}: unverified {ver2.unverified_numbers or 'none'}")
                if len(ver2.unverified_numbers) + 3 * len(ver2.future_minutes) <= len(ver.unverified_numbers) + 3 * len(ver.future_minutes):
                    answer, ver = revised, ver2
                ver.revised = True
            answer, providers = neutralise(answer)
            run.answer = ctx.scrub(answer)
            run.verification = ver
            run.status = RunStatus.DONE
            run.event("done", "orchestrator", f"{run.usage['model_calls']} model calls, {len(ctx.tools.calls)} tool calls")
        except Exception as exc:  # noqa: BLE001 - every failure ends the run with a reason the client can show
            log.warning("team run %s failed: %s", run.id, exc, exc_info=not isinstance(exc, (ModelError, KeyError, ValueError)))
            run.error = f"{type(exc).__name__}: {exc}"[:300] if not isinstance(exc, KeyError) else f"match {exc} not found"
            run.status = RunStatus.FAILED
            run.event("error", "orchestrator", run.error)
        finally:
            run.finished = time.time()

    def _run_specialists(self, run: Run, board: Blackboard, ctx: RunContext, deadline: float) -> None:
        futures: dict[Future, Task] = {}

        def work(task: Task) -> dict[str, Any]:
            task.status, task.started = TaskStatus.RUNNING, time.time()
            run.event("task_start", task.specialist, task.question)
            return roles.run_specialist(self.model, task, board, ctx.context, deadline, run.add_usage,
                                        lambda t, info: run.event("tool", t.specialist, info["name"] + (" (shared)" if info["cached"] else "")))

        for task in run.plan.tasks:
            futures[self._task_pool.submit(work, task)] = task
        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=max(0.0, deadline - time.time()), return_when=FIRST_COMPLETED)
            if not done:
                break
            for fut in done:
                task = futures[fut]
                task.seconds = round(time.time() - (task.started or time.time()), 1)
                try:
                    task.report = fut.result()
                    task.status = TaskStatus.DONE
                    run.event("task_done", task.specialist, task.report.get("summary", ""))
                except Exception as exc:  # noqa: BLE001
                    task.status, task.error = TaskStatus.FAILED, f"{type(exc).__name__}: {exc}"[:200]
                    run.event("task_failed", task.specialist, task.error)
        for fut in pending:                    # past the deadline: synthesise with what we have
            task = futures[fut]
            task.status, task.error = TaskStatus.SKIPPED, "ran out of time"
            run.event("task_failed", task.specialist, "skipped: run deadline")
