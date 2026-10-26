"""Foundry Agent Service REST client (Entra client credentials); agents are looked up by name.

Requested tool calls run locally through ``MatchTools``, bound to the replay clock.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from footballiq.agents.definitions import AGENTS, AgentSpec
from footballiq.agents.tools import MatchTools

log = logging.getLogger(__name__)
SCOPE = "https://ai.azure.com/.default"
TERMINAL = {"completed", "failed", "cancelled", "expired", "incomplete"}


class FoundryError(RuntimeError):
    pass


def configured() -> bool:
    return all(os.environ.get(k) for k in ("FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_TENANT_ID", "FOUNDRY_CLIENT_ID", "FOUNDRY_CLIENT_SECRET"))


def default_model() -> str:
    return os.environ.get("FOUNDRY_MODEL", "gpt-5.1")


class FoundryClient:
    def __init__(self, endpoint: str | None = None, api_version: str | None = None, timeout: float = 60.0):
        if not configured() and endpoint is None:
            raise FoundryError("Foundry is not configured: set FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_TENANT_ID, "
                               "FOUNDRY_CLIENT_ID and FOUNDRY_CLIENT_SECRET (see .env.example)")
        self.endpoint = (endpoint or os.environ["FOUNDRY_PROJECT_ENDPOINT"]).rstrip("/")
        self.api_version = api_version or os.environ.get("FOUNDRY_API_VERSION", "2025-05-01")
        self.http = httpx.Client(timeout=timeout)
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()
        self._agent_ids: dict[str, str] = {}

    def _bearer(self) -> str:
        with self._lock:
            if self._token and self._token[1] - time.time() > 300:   # refresh 5 min before expiry
                return self._token[0]
            r = self.http.post(f"https://login.microsoftonline.com/{os.environ['FOUNDRY_TENANT_ID']}/oauth2/v2.0/token",
                               data={"grant_type": "client_credentials", "client_id": os.environ["FOUNDRY_CLIENT_ID"],
                                     "client_secret": os.environ["FOUNDRY_CLIENT_SECRET"], "scope": SCOPE})
            if r.status_code != 200:
                raise FoundryError(f"Entra token request failed ({r.status_code}): {r.json().get('error_description', r.text)[:200]}")
            body = r.json()
            self._token = (body["access_token"], time.time() + int(body.get("expires_in", 3600)))
            return self._token[0]

    def _req(self, method: str, path: str, json: dict | None = None, params: dict | None = None) -> dict[str, Any]:
        for attempt in range(4):
            try:
                r = self.http.request(method, f"{self.endpoint}{path}", json=json,
                                      params={"api-version": self.api_version, **(params or {})},
                                      headers={"Authorization": f"Bearer {self._bearer()}"})
            except httpx.TransportError as exc:
                if attempt == 3:
                    raise FoundryError(f"{method} {path}: {exc}") from exc
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 401 and attempt < 3:
                self._token = None
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(float(r.headers.get("retry-after", 2 ** attempt)))
                continue
            if r.status_code >= 400:
                raise FoundryError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
            return r.json() if r.content else {}
        raise FoundryError(f"{method} {path}: retries exhausted")

    def list_agents(self) -> list[dict[str, Any]]:
        out, after = [], None
        while True:
            page = self._req("GET", "/assistants", params={"limit": 100, "order": "asc", **({"after": after} if after else {})})
            out += page.get("data", [])
            if not page.get("has_more"):
                return out
            after = page.get("last_id")

    def ensure_agent(self, spec: AgentSpec, model: str | None = None) -> dict[str, Any]:
        """Create the agent, or update it in place if its definition changed."""
        body = {"name": spec.name, "description": spec.description, "instructions": spec.instructions, "tools": spec.tools,
                "model": model or default_model(), "temperature": spec.temperature,
                "metadata": {"app": "footballiq", "role": spec.key, "definition_version": spec.version}}
        agents = self.list_agents()
        existing = next((a for a in agents if a.get("name") == spec.name), None) or \
            next((a for a in agents if a.get("name") in spec.aliases), None)
        if existing is None:
            agent = self._req("POST", "/assistants", json=body)
            log.info("created Foundry agent %s (%s)", spec.name, agent["id"])
        elif any(existing.get(k) != body[k] for k in ("name", "instructions", "model", "description")) or \
                (existing.get("metadata") or {}).get("definition_version") != spec.version or \
                [t.get("function", {}).get("name") for t in existing.get("tools", [])] != [t["function"]["name"] for t in spec.tools]:
            agent = self._req("POST", f"/assistants/{existing['id']}", json=body)
            log.info("updated Foundry agent %s (%s)", spec.name, agent["id"])
        else:
            agent = existing
        self._agent_ids[spec.key] = agent["id"]
        return agent

    def agent_id(self, key: str) -> str:
        if key not in self._agent_ids:
            override = os.environ.get(f"FOUNDRY_AGENT_{key.upper()}_ID")
            if override:
                self._agent_ids[key] = override
            else:
                spec = AGENTS[key]
                found = next((a for a in self.list_agents() if a.get("name") == spec.name), None)
                self._agent_ids[key] = found["id"] if found else self.ensure_agent(spec)["id"]
        return self._agent_ids[key]

    def run(self, key: str, message: str, tools: MatchTools, context: str, thread_id: str | None = None,
            timeout_s: float = 150.0, model: str | None = None) -> RunResult:
        agent = self.agent_id(key)
        if thread_id is None:
            thread_id = self._req("POST", "/threads", json={"metadata": {"app": "footballiq", "match_id": tools.match_id}})["id"]
        self._req("POST", f"/threads/{thread_id}/messages", json={"role": "user", "content": message})
        body = {"assistant_id": agent, "additional_instructions": context, **({"model": model} if model else {})}
        run = self._req("POST", f"/threads/{thread_id}/runs", json=body)
        t0 = time.time()
        while True:
            status = run.get("status")
            if status == "requires_action":
                calls = run["required_action"]["submit_tool_outputs"]["tool_calls"]
                outputs = [{"tool_call_id": c["id"], "output": tools.run(c["function"]["name"], c["function"].get("arguments"))}
                           for c in calls]
                run = self._req("POST", f"/threads/{thread_id}/runs/{run['id']}/submit_tool_outputs", json={"tool_outputs": outputs})
                continue
            if status in TERMINAL:
                break
            if time.time() - t0 > timeout_s:
                self._req("POST", f"/threads/{thread_id}/runs/{run['id']}/cancel")
                raise FoundryError(f"agent run timed out after {timeout_s:.0f}s")
            time.sleep(0.8)
            run = self._req("GET", f"/threads/{thread_id}/runs/{run['id']}")
        if status != "completed":
            err = run.get("last_error") or run.get("incomplete_details") or {}
            raise FoundryError(f"agent run {status}: {err}")
        msgs = self._req("GET", f"/threads/{thread_id}/messages", params={"order": "desc", "limit": 1, "run_id": run["id"]})
        text = "\n".join(c["text"]["value"] for m in msgs.get("data", [])[:1] for c in m.get("content", []) if c.get("type") == "text")
        return RunResult(text=text.strip(), thread_id=thread_id, run_id=run["id"], agent_id=agent, model=run.get("model"),
                         tool_calls=tools.calls, usage=run.get("usage") or {}, seconds=round(time.time() - t0, 1))


@dataclass
class RunResult:
    text: str
    thread_id: str
    run_id: str
    agent_id: str
    model: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0
