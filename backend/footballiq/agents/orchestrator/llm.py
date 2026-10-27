"""Chat-model port used by every orchestrator role, and its Microsoft Foundry adapter.

The orchestrator talks to models through ``ChatModel.complete`` only, so roles can be tested offline with a scripted
model and the deployment can be swapped (``FOUNDRY_MODEL``, or a per-role override) without touching role code.
The Foundry adapter calls the Azure OpenAI chat-completions endpoint of the Foundry project's AI Services resource
with the same Entra service principal as the Foundry agents (scope https://cognitiveservices.azure.com/.default).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from footballiq.agents import foundry

log = logging.getLogger(__name__)
SCOPE = "https://cognitiveservices.azure.com/.default"
API_VERSION = "2024-10-21"
RETRY_STATUS = (408, 429, 500, 502, 503, 504)


class ModelError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ChatResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None


class ChatModel(Protocol):
    name: str

    def complete(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
                 json_mode: bool = False, max_tokens: int = 1500, role: str = "") -> ChatResponse: ...


class FoundryChat:
    """Thread-safe chat-completions client (one per process). Retries 429/5xx with backoff."""

    def __init__(self, deployment: str | None = None, timeout: float = 90.0, max_retries: int = 3):
        if not foundry.configured():
            raise ModelError("Foundry is not configured (FOUNDRY_PROJECT_ENDPOINT / FOUNDRY_TENANT_ID / FOUNDRY_CLIENT_ID / "
                             "FOUNDRY_CLIENT_SECRET)")
        self.name = deployment or os.environ.get("FOOTBALLIQ_TEAM_MODEL") or foundry.default_model()
        base = os.environ["FOUNDRY_PROJECT_ENDPOINT"].split("/api/projects/")[0].rstrip("/")
        self.url = f"{base}/openai/deployments/{self.name}/chat/completions?api-version={API_VERSION}"
        self.http = httpx.Client(timeout=timeout)
        self.max_retries = max_retries
        # reasoning effort per role (gpt-5 family): routing and write-up are fast at "low"; specialists reason over tool
        # data at the model default. Override with FOOTBALLIQ_TEAM_REASONING_<ROLE> (none|low|medium|high|default).
        self.reasoning: dict[str, str | None] = {"planner": "low", "synthesizer": "low"}
        for role in ("planner", "synthesizer", "specialist"):
            v = os.environ.get(f"FOOTBALLIQ_TEAM_REASONING_{role.upper()}")
            if v:
                self.reasoning[role] = None if v == "default" else v
        self.reasoning_supported = True
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    def _bearer(self) -> str:
        with self._lock:
            if self._token and self._token[1] - time.time() > 300:
                return self._token[0]
            r = self.http.post(f"https://login.microsoftonline.com/{os.environ['FOUNDRY_TENANT_ID']}/oauth2/v2.0/token",
                               data={"grant_type": "client_credentials", "client_id": os.environ["FOUNDRY_CLIENT_ID"],
                                     "client_secret": os.environ["FOUNDRY_CLIENT_SECRET"], "scope": SCOPE})
            if r.status_code != 200:
                raise ModelError(f"token request failed ({r.status_code})")
            d = r.json()
            self._token = (d["access_token"], time.time() + int(d.get("expires_in", 3600)))
            return self._token[0]

    def complete(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
                 json_mode: bool = False, max_tokens: int = 1500, role: str = "") -> ChatResponse:
        body: dict[str, Any] = {"messages": messages, "max_completion_tokens": max_tokens}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode and not tools:
            body["response_format"] = {"type": "json_object"}
        effort = self.reasoning.get(role if role in ("planner", "synthesizer") else "specialist")
        if effort and self.reasoning_supported:
            body["reasoning_effort"] = effort
        last = ""
        for attempt in range(self.max_retries + 1):
            try:
                r = self.http.post(self.url, headers={"Authorization": f"Bearer {self._bearer()}"}, json=body)
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                if r.status_code == 400 and "reasoning_effort" in body and "reasoning" in r.text:
                    body.pop("reasoning_effort")          # deployment without reasoning controls
                    self.reasoning_supported = False
                    continue
                if r.status_code == 200:
                    d = r.json()
                    msg = d["choices"][0]["message"]
                    calls = [ToolCall(c["id"], c["function"]["name"], c["function"].get("arguments") or "{}")
                             for c in msg.get("tool_calls") or []]
                    return ChatResponse(content=msg.get("content") or "", tool_calls=calls, usage=d.get("usage") or {},
                                        model=d.get("model"))
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code not in RETRY_STATUS:
                    break
            if attempt < self.max_retries:
                time.sleep(min(20.0, 2.0 * 2 ** attempt))
        raise ModelError(f"{role or 'model'} call failed: {last}")


def tool_message(call: ToolCall, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call.id, "content": content}


def assistant_tool_calls(resp: ChatResponse) -> dict[str, Any]:
    return {"role": "assistant", "content": resp.content or None,
            "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                           for c in resp.tool_calls]}


def parse_json(text: str) -> dict[str, Any] | None:
    """First JSON object in ``text`` (tolerates code fences and prose around it)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        return obj if isinstance(obj, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None
