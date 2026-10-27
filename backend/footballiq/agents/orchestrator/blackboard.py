"""Shared tool layer for one run: every specialist calls the same clock-bounded MatchTools through this blackboard.

* Permissions: a specialist can only call the tools in its registry entry.
* Cache: identical calls (same tool, same arguments) are executed once per run and shared, so four specialists asking for
  the match context cost one call. MatchTools is cut at the run's at_ms, so a shared result can never leak the future.
* Evidence: every tool output text is kept; the verifier checks the final answer's numbers against them.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from footballiq.agents.tools import MatchTools


class ToolDenied(Exception):
    pass


class Blackboard:
    def __init__(self, tools: MatchTools):
        self.tools = tools
        self._cache: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()
        self._inflight: dict[tuple[str, str], threading.Event] = {}
        self.outputs: list[str] = []          # every distinct tool output (evidence for the verifier)

    @staticmethod
    def _key(name: str, arguments: str | dict | None) -> tuple[str, str]:
        try:
            args = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else dict(arguments or {})
        except (json.JSONDecodeError, TypeError, ValueError):
            args = {"_raw": str(arguments)}
        return name, json.dumps(args, sort_keys=True)

    def call(self, name: str, arguments: str | dict | None, allowed: tuple[str, ...]) -> tuple[str, bool]:
        """Returns (json text, cached). Raises ToolDenied for a tool outside the specialist's permissions."""
        if name not in allowed:
            raise ToolDenied(name)
        key = self._key(name, arguments)
        while True:
            with self._lock:
                if key in self._cache:
                    return self._cache[key], True
                ev = self._inflight.get(key)
                if ev is None:
                    ev = self._inflight[key] = threading.Event()
                    owner = True
                else:
                    owner = False
            if owner:
                break
            ev.wait(timeout=60)                # another specialist is running the same call: share its result
        try:
            text = self.tools.run(name, json.loads(key[1]))
        finally:
            with self._lock:
                self._inflight.pop(key, None)
        with self._lock:
            self._cache[key] = text
            self.outputs.append(text)
        ev.set()
        return text, False

    def last_call(self) -> dict[str, Any] | None:
        return self.tools.calls[-1] if self.tools.calls else None
