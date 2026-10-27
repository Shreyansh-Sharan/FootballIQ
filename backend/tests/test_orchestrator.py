"""Multi-agent orchestrator, offline: a scripted model plays planner, specialists and synthesizer."""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from footballiq.agents.orchestrator import Limits, Orchestrator, RunContext, RunRequest, RunStatus
from footballiq.agents.orchestrator.llm import ChatResponse, ToolCall, parse_json
from footballiq.agents.orchestrator.roles import fallback_plan
from footballiq.agents.orchestrator.verifier import verify
from footballiq.agents.tools import MatchTools
from footballiq.api.app import create_app
from footballiq.api.orchestrator import minute_float
from test_matchday import MIN, _Store, _timeline


class Scripted:
    """Plays every role from the role name; records calls. ``synth`` answers are consumed in order."""

    name = "scripted"

    def __init__(self, plan=None, synth=None, slow: dict[str, float] | None = None, bad_tool: str | None = None):
        self.plan = plan if plan is not None else {"intent": "who is on top", "tasks": [
            {"specialist": "tactician", "question": "Who controls the game?"},
            {"specialist": "threat", "question": "Who creates the better chances?"}], "reason": "control and chances"}
        self.synth = list(synth or ["Home FC are on top.\n- 1 goal from match events.\nConfidence: medium - small sample"])
        self.slow, self.bad_tool = slow or {}, bad_tool
        self.calls: list[str] = []

    def complete(self, messages, *, tools=None, json_mode=False, max_tokens=1500, role=""):
        self.calls.append(role)
        time.sleep(self.slow.get(role, 0))
        if role == "planner":
            return ChatResponse(json.dumps(self.plan), usage={"prompt_tokens": 10, "completion_tokens": 5})
        if role == "synthesizer":
            return ChatResponse(self.synth.pop(0) if len(self.synth) > 1 else self.synth[0])
        # specialist: one tool round (both ask for the key events: a tool both roles may use), then a JSON report
        if not any(m["role"] == "tool" for m in messages):
            calls = [ToolCall("c1", "get_key_events", "{}")]
            if self.bad_tool:
                calls.append(ToolCall("c2", self.bad_tool, "{}"))
            return ChatResponse("", tool_calls=calls)
        return ChatResponse(json.dumps({"summary": f"{role} view", "findings": [
            {"claim": "Home FC scored 1 goal", "evidence": "get_match_stats goals 1", "confidence": "high"}],
            "recommendation": None, "data_gaps": []}))


def _ctx_factory(tl):
    def make(match_id, at_ms):
        if match_id != "m-test":
            raise KeyError(match_id)
        tools = MatchTools(tl, at_ms)
        return RunContext(tools=tools, context="Replay context: Home FC v Away FC, 25'", clock="25'", minute=25.0,
                          team_names={"home-fc": "Home FC", "away-fc": "Away FC"})
    return make


def _orch(model, **lim):
    return Orchestrator(model, _ctx_factory(_timeline()), Limits(**({"run_timeout_s": 30, "synth_reserve_s": 5} | lim)))


def _req(**kw):
    return RunRequest(**({"match_id": "m-test", "at_ms": 25 * MIN, "question": "Who is on top right now?"} | kw))


# ---------------------------------------------------------------------- routing
def test_fallback_routing_by_keywords():
    assert [t.specialist for t in fallback_plan("Who should we substitute? He looks tired").tasks] == ["performance"]
    assert {t.specialist for t in fallback_plan("Is their formation a back three, and who controls possession?").tasks} == {"tactician"}
    assert [t.specialist for t in fallback_plan("What's going on?").tasks] == ["tactician", "threat", "forecaster"]


def test_unusable_plan_falls_back_to_keywords():
    run = _orch(Scripted(plan={"tasks": [{"specialist": "astrologer", "question": "?"}]})).run_sync(_req(question="Will they win?"))
    assert run.status == RunStatus.DONE and run.plan.source == "fallback"
    assert [t.specialist for t in run.plan.tasks] == ["forecaster"]


# ---------------------------------------------------------------------- pipeline
def test_full_run_parallel_shared_tools_and_verified_answer():
    model = Scripted()
    orch = _orch(model)
    run = orch.run_sync(_req())
    d = run.to_dict()
    assert run.status == RunStatus.DONE, run.error
    assert [t["status"] for t in d["plan"]["tasks"]] == ["done", "done"]
    # both specialists asked for the same key events: executed once, shared with the other
    ev_calls = [c for t in run.plan.tasks for c in t.tool_calls if c["name"] == "get_key_events"]
    assert len(ev_calls) == 2 and sum(c["cached"] for c in ev_calls) == 1
    assert run.answer.startswith("Home FC are on top") and run.verification.status == "pass"
    kinds = [e["kind"] for e in d["trace"]]
    assert kinds[0] == "plan" and "task_start" in kinds and "synth" in kinds and "verify" in kinds and kinds[-1] == "done"
    assert d["usage"]["model_calls"] == len(model.calls)


def test_specialist_cannot_use_tools_outside_its_role():
    run = _orch(Scripted(bad_tool="get_substitution_options")).run_sync(_req())
    assert run.status == RunStatus.DONE
    denied = [c for t in run.plan.tasks for c in t.tool_calls if c["name"] == "get_substitution_options"]
    assert denied and not any(c["ok"] for c in denied)
    executed = [c["name"] for t in run.plan.tasks for c in t.tool_calls if c["ok"]]
    assert "get_substitution_options" not in executed


def test_tools_are_cut_at_the_clock():
    """The specialists' tools see nothing after at_ms: the 20' goal exists at 25', not at 15'."""
    early = _orch(Scripted()).run_sync(_req(at_ms=15 * MIN, question="Who is on top at 15?"))
    assert early.status == RunStatus.DONE
    tl = _timeline()
    assert json.loads(MatchTools(tl, 15 * MIN).run("get_match_stats", {}))["teams"]
    stats15 = MatchTools(tl, 15 * MIN).run("get_match_stats", {})
    stats25 = MatchTools(tl, 25 * MIN).run("get_match_stats", {})
    assert stats15 != stats25


def test_ungrounded_numbers_trigger_one_revision():
    model = Scripted(synth=["Home FC lead with 87% possession.\nConfidence: high", "Home FC lead.\nConfidence: medium"])
    run = _orch(model).run_sync(_req())
    assert run.status == RunStatus.DONE and run.verification.revised
    assert "87" not in run.answer and run.verification.status == "pass"
    assert model.calls.count("synthesizer") == 2


def test_slow_specialist_is_skipped_at_the_deadline():
    model = Scripted(slow={"threat": 6.0})
    run = _orch(model, run_timeout_s=8, synth_reserve_s=5).run_sync(_req())
    assert run.status == RunStatus.DONE
    st = {t.specialist: t.status.value for t in run.plan.tasks}
    assert st == {"tactician": "done", "threat": "skipped"}


def test_identical_requests_share_one_run_and_unknown_match_fails_cleanly():
    orch = _orch(Scripted())
    a = orch.start(_req())
    b = orch.start(_req(question="  who is ON top right now? "))
    assert a.id == b.id
    bad = orch.run_sync(_req(match_id="nope"))
    assert bad.status == RunStatus.FAILED and "not found" in bad.error


# ---------------------------------------------------------------------- verifier
def test_verifier_grounding_percentages_formations_and_future():
    ev = ['{"possession_pct": 56.4, "win_phase": {"probability": 0.231}, "formation": "4-3-3", "shots": 13}']
    ok = verify("Home FC have 56% of the ball, a 23.1% chance to win, 13 shots, in a 4-3-3 at 68'.", ev, 70.0)
    assert ok.status == "pass", ok
    bad = verify("They had 19 shots and scored at 75'. StatsBomb says so.", ev, 70.0)
    assert "19" in bad.unverified_numbers and "75'" in bad.future_minutes and bad.status == "fail" and bad.issues
    assert verify("Goal at 90+3' and 45+2'.", [], minute_float("90+4'")).future_minutes == []
    assert verify("Goal at 90+5'.", [], minute_float("90+4'")).future_minutes == ["90+5'"]


def test_parse_json_tolerates_fences():
    assert parse_json('Sure:\n```json\n{"a": {"b": 1}}\n```') == {"a": {"b": 1}}
    assert parse_json("no json") is None


# ---------------------------------------------------------------------- API
def test_api_team_endpoints(monkeypatch):
    monkeypatch.setenv("FOOTBALLIQ_PSEUDONYMS", "off")
    app = create_app(store=_Store(_timeline()))
    app.state.orchestrator = _orch(Scripted())
    c = TestClient(app)
    roster = c.get("/v1/agents/team").json()
    assert {s["key"] for s in roster["specialists"]} == {"tactician", "threat", "forecaster", "performance"}
    d = c.post("/v1/matches/m-test/agents/team", json={"question": "Who is on top?", "at_ms": 25 * MIN, "wait": True}).json()
    assert d["status"] == "done" and d["answer"] and d["verification"]["status"] == "pass"
    assert c.get(f"/v1/agents/runs/{d['id']}").json()["id"] == d["id"]
    assert c.get("/v1/agents/runs/run-nope").status_code == 404
    assert c.post("/v1/matches/m-test/agents/team", json={"question": "x", "at_ms": 1, "lang": "fr"}).status_code == 422
    started = c.post("/v1/matches/m-test/agents/team", json={"question": "Will they win?", "at_ms": 25 * MIN}).json()
    assert started["status"] in ("queued", "planning", "running", "synthesising", "verifying", "done")
