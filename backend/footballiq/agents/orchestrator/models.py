"""Data model of an orchestrated run: request, plan, specialist tasks, verification and the trace.

Everything here is plain data (dataclasses) so a run can be serialised to the API at any moment while it executes.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

LANGS = ("en", "es", "hi")
PERSONAS = ("coach", "analyst", "fan", "casual", "player")


class RunStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"            # specialists working
    SYNTHESISING = "synthesising"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in (RunStatus.DONE, RunStatus.FAILED)


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"            # run deadline reached before it finished


@dataclass
class RunRequest:
    match_id: str                  # canonical id (the API translates public ids before it gets here)
    at_ms: int                     # replay clock: nothing after it may be used
    question: str
    lang: str = "en"
    persona: str = "coach"
    fav_team_id: str | None = None # fan perspective: whose side we're on

    def cache_key(self, bucket_ms: int) -> tuple:
        q = " ".join(self.question.lower().split())
        return (self.match_id, self.at_ms // bucket_ms, q, self.lang, self.persona, self.fav_team_id)


@dataclass
class Task:
    specialist: str
    question: str
    status: TaskStatus = TaskStatus.QUEUED
    started: float | None = None
    seconds: float | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)   # {name, arguments, ok, cached, chars}
    report: dict[str, Any] | None = None                            # {summary, findings[], recommendation, data_gaps[]}
    error: str | None = None
    model_calls: int = 0


@dataclass
class Plan:
    intent: str
    tasks: list[Task]
    reason: str = ""
    source: str = "model"          # model | fallback


@dataclass
class Verification:
    status: str                    # pass | warn | fail
    numbers_checked: int = 0
    unverified_numbers: list[str] = field(default_factory=list)
    future_minutes: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    revised: bool = False


@dataclass
class TraceEvent:
    t: float                       # seconds since the run started
    kind: str                      # plan | task_start | tool | task_done | task_failed | synth | verify | revise | done | error
    agent: str
    detail: str = ""


@dataclass
class Run:
    request: RunRequest
    id: str = field(default_factory=lambda: "run-" + uuid.uuid4().hex[:12])
    status: RunStatus = RunStatus.QUEUED
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    clock: str = ""                # scoreboard minute at at_ms, e.g. "68'"
    plan: Plan | None = None
    answer: str | None = None
    verification: Verification | None = None
    trace: list[TraceEvent] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "model_calls": 0})
    model: str | None = None
    error: str | None = None
    cached_from: str | None = None

    def event(self, kind: str, agent: str, detail: str = "") -> None:
        base = self.started or self.created
        self.trace.append(TraceEvent(round(time.time() - base, 2), kind, agent, detail[:300]))

    def add_usage(self, usage: dict[str, Any] | None) -> None:
        self.usage["model_calls"] += 1
        for k in ("prompt_tokens", "completion_tokens"):
            self.usage[k] += int((usage or {}).get(k) or 0)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["seconds"] = round((self.finished or time.time()) - (self.started or self.created), 1)
        d["request"] = {k: v for k, v in d["request"].items() if k != "match_id"} | {"match_id": self.request.match_id}
        if self.plan:
            for t in d["plan"]["tasks"]:
                t["status"] = t["status"].value if isinstance(t["status"], TaskStatus) else t["status"]
                t.pop("started", None)
        return d
