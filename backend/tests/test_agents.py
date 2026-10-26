"""Foundry agent plumbing, offline: run loop, tool dispatch, idempotent setup, card parsing, API guard."""
import json

import pytest
from fastapi.testclient import TestClient

from footballiq.agents import foundry
from footballiq.agents.definitions import AGENTS
from footballiq.agents.foundry import FoundryClient
from footballiq.agents.service import parse_card
from footballiq.agents.tools import MatchTools


class FakeFoundry(FoundryClient):
    """Answers the REST calls the run loop makes; the 'model' asks for two tools, then answers."""

    def __init__(self):
        super().__init__(endpoint="https://example.test/api/projects/p")
        self.agents, self.posted_outputs, self.updates = [], [], 0
        self._polls = 0

    def _req(self, method, path, json=None, params=None):
        if path == "/assistants" and method == "GET":
            return {"data": self.agents, "has_more": False}
        if path == "/assistants" and method == "POST":
            self.agents.append({"id": f"asst_{len(self.agents)}", **json, "tools": json["tools"]})
            return self.agents[-1]
        if path.startswith("/assistants/") and method == "POST":
            self.updates += 1
            a = next(a for a in self.agents if a["id"] == path.split("/")[-1])
            a.update(json)
            return a
        if path == "/threads":
            return {"id": "thread_1"}
        if path.endswith("/messages") and method == "POST":
            return {}
        if path.endswith("/runs") and method == "POST":
            return {"id": "run_1", "status": "requires_action", "required_action": {"submit_tool_outputs": {"tool_calls": [
                {"id": "c1", "function": {"name": "get_match_context", "arguments": "{}"}},
                {"id": "c2", "function": {"name": "get_key_events", "arguments": json_dumps({"limit": 2, "types": ["goal"]})}}]}}}
        if path.endswith("/submit_tool_outputs"):
            self.posted_outputs = json["tool_outputs"]
            return {"id": "run_1", "status": "completed", "model": "gpt-5.1", "usage": {"total_tokens": 10}}
        if path.endswith("/messages") and method == "GET":
            return {"data": [{"content": [{"type": "text", "text": {"value": "Argentina lead 2-0."}}]}]}
        raise AssertionError(f"unexpected {method} {path}")


def json_dumps(o):
    return json.dumps(o)


def test_run_executes_tools_at_the_replay_clock_and_returns_the_answer(timeline):
    fc = FakeFoundry()
    t_ms = timeline.events[3].match_elapsed_ms  # the home goal at 10'
    r = fc.run("strategist", "Who leads?", MatchTools(timeline, t_ms), "ctx")
    assert r.text == "Argentina lead 2-0." and r.thread_id == "thread_1" and r.model == "gpt-5.1"
    assert [c["name"] for c in r.tool_calls] == ["get_match_context", "get_key_events"]
    ctx = json.loads(fc.posted_outputs[0]["output"])
    assert ctx["score"] == timeline.state_at(t_ms)["score"]
    goals = json.loads(fc.posted_outputs[1]["output"])["events"]
    assert all(e["type"] == "Goal" for e in goals) and len(goals) == 1


def test_setup_is_idempotent_and_updates_when_the_definition_changes():
    fc = FakeFoundry()
    spec = AGENTS["strategist"]
    a = fc.ensure_agent(spec, "gpt-5.1")
    b = fc.ensure_agent(spec, "gpt-5.1")
    assert a["id"] == b["id"] and len(fc.agents) == 1 and fc.updates == 0
    fc.ensure_agent(spec, "grok-4.6")                      # model change -> update in place, same id
    assert fc.updates == 1 and len(fc.agents) == 1 and fc.agents[0]["model"] == "grok-4.6"


def test_agent_under_an_old_name_is_renamed_in_place():
    fc = FakeFoundry()
    spec = AGENTS["strategist"]
    fc.agents.append({"id": "asst_old", "name": spec.aliases[0], "instructions": "old", "model": "gpt-5.1", "tools": []})
    a = fc.ensure_agent(spec, "gpt-5.1")
    assert a["id"] == "asst_old" and a["name"] == spec.name and len(fc.agents) == 1 and fc.updates == 1


def test_tools_never_see_past_the_clock(timeline):
    early = MatchTools(timeline, 1_000)
    assert json.loads(early.run("get_key_events", '{"types": ["goal"]}'))["events"] == []
    bad = json.loads(early.run("get_forecasts", "{}"))
    assert "unavailable" in bad


@pytest.mark.parametrize("text", [
    '{"headline": "A lead", "what_is_happening": "x", "main_risk": "y", "one_action": "z", "confidence": "high", "evidence": []}',
    'Here you go:\n```json\n{"headline": "A lead", "confidence": "sure", "evidence": [{"source": "s", "detail": "d"}, "junk"]}\n```',
])
def test_parse_card_tolerates_fences_and_bad_fields(text):
    card = parse_card(text)
    assert card["headline"] == "A lead" and card["confidence"] in ("high", "low")
    assert all(isinstance(e, dict) for e in card["evidence"])


def test_parse_card_rejects_non_json():
    assert parse_card("Argentina are on top.") is None


def test_api_reports_agents_not_configured(silver_store, monkeypatch):
    for k in ("FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_TENANT_ID", "FOUNDRY_CLIENT_ID", "FOUNDRY_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    from footballiq.api.app import create_app
    client = TestClient(create_app(store=silver_store))
    assert client.get("/v1/agents").json() == {"configured": False, "agents": {}}
    mid = silver_store.match_ids()[0]
    r = client.post(f"/v1/matches/{mid}/agents/ask", json={"question": "Who leads?", "at_ms": 1000})
    assert r.status_code == 503 and "FOUNDRY_PROJECT_ENDPOINT" in r.json()["detail"]
    assert not foundry.configured()
