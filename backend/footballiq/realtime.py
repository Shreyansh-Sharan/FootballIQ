"""Replay telemetry to a Fabric Eventstream custom endpoint (Event Hubs REST), never on the render path.

A bounded queue drops the oldest messages when full; streams fan out in fabric/kql/football_rt.kql.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)
API = "https://api.fabric.microsoft.com/v1"


@dataclass
class EventHubTarget:
    namespace: str
    hub: str
    key_name: str
    key: str

    @classmethod
    def from_connection_string(cls, cs: str) -> EventHubTarget:
        parts = dict(p.split("=", 1) for p in cs.strip().strip(";").split(";") if "=" in p)
        ns = parts["Endpoint"].replace("sb://", "").strip("/")
        return cls(namespace=ns, hub=parts["EntityPath"], key_name=parts["SharedAccessKeyName"], key=parts["SharedAccessKey"])

    def sas_token(self, ttl_s: int = 3600) -> str:
        uri = urllib.parse.quote_plus(f"https://{self.namespace}/{self.hub}")
        expiry = str(int(time.time()) + ttl_s)
        sig = base64.b64encode(hmac.new(self.key.encode(), f"{uri}\n{expiry}".encode(), hashlib.sha256).digest())
        return f"SharedAccessSignature sr={uri}&sig={urllib.parse.quote_plus(sig)}&se={expiry}&skn={self.key_name}"


def resolve_target() -> EventHubTarget | None:
    """Explicit connection string, else looked up via the Fabric REST API (SAS key never stored)."""
    if os.environ.get("FOOTBALLIQ_EVENTSTREAM", "").lower() in ("off", "0", "false"):
        return None
    cs = os.environ.get("FOOTBALLIQ_EVENTSTREAM_CONNECTION")
    if cs:
        return EventHubTarget.from_connection_string(cs)
    if not all(os.environ.get(k) for k in ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET")):
        return None
    tok = httpx.post(
        f"https://login.microsoftonline.com/{os.environ['FABRIC_TENANT_ID']}/oauth2/v2.0/token",
        data={"grant_type": "client_credentials", "client_id": os.environ["FABRIC_CLIENT_ID"],
              "client_secret": os.environ["FABRIC_CLIENT_SECRET"], "scope": "https://api.fabric.microsoft.com/.default"},
        timeout=30).json()["access_token"]
    es_name = os.environ.get("FABRIC_EVENTSTREAM_NAME", "es_football_replay")
    src_name = os.environ.get("FABRIC_EVENTSTREAM_SOURCE", "replay-api")
    with httpx.Client(base_url=API, headers={"Authorization": f"Bearer {tok}"}, timeout=60) as c:
        ws = os.environ.get("FABRIC_WORKSPACE_ID")
        if not ws:
            name = os.environ.get("FABRIC_WORKSPACE_NAME", "Football Analytics Shreyansh")
            ws = next(w["id"] for w in c.get("/workspaces").json()["value"] if w["displayName"] == name)
        es = next((i for i in c.get(f"/workspaces/{ws}/eventstreams").json()["value"] if i["displayName"] == es_name), None)
        if es is None:
            log.warning("eventstream %s not found - publishing disabled", es_name)
            return None
        topo = c.get(f"/workspaces/{ws}/eventstreams/{es['id']}/topology").json()
        src = next(s for s in topo["sources"] if s["name"] == src_name)
        conn = c.get(f"/workspaces/{ws}/eventstreams/{es['id']}/sources/{src['id']}/connection").json()
    return EventHubTarget.from_connection_string(conn["accessKeys"]["primaryConnectionString"])


class EventstreamPublisher:
    def __init__(self, target: EventHubTarget | None, max_queue: int = 20_000, batch: int = 200, flush_s: float = 1.0):
        self.target = target
        self.queue: deque[dict[str, Any]] = deque(maxlen=max_queue)
        self.batch = batch
        self.flush_s = flush_s
        self.sent = 0
        self.dropped = 0
        self.failed_batches = 0
        self.last_error: str | None = None
        self.last_sent_at: str | None = None
        self._task: asyncio.Task | None = None
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return self.target is not None

    def publish(self, stream: str, match_id: str, session_id: str, generation_id: int, replay_t_ms: int,
                payload: dict[str, Any]) -> None:
        """Non-blocking enqueue. Never raises, never waits."""
        if not self.enabled:
            return
        if len(self.queue) == self.queue.maxlen:
            self.dropped += 1  # deque drops the oldest on append
        self.queue.append({
            "stream": stream, "match_id": match_id, "session_id": session_id, "generation_id": generation_id,
            "replay_t_ms": int(replay_t_ms), "sent_at_utc": datetime.now(timezone.utc).isoformat(), "payload": payload,
        })

    async def start(self) -> None:
        if self.enabled and self._task is None:
            self._client = httpx.AsyncClient(timeout=20)
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await self._flush()  # best effort
        if self._client:
            await self._client.aclose()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.flush_s)
            try:
                await self._flush()
            except Exception as exc:  # keep the loop alive
                self.last_error = repr(exc)[:300]
                log.warning("eventstream flush failed: %s", self.last_error)

    async def _flush(self) -> None:
        assert self._client is not None
        while self.queue:
            msgs = [self.queue.popleft() for _ in range(min(self.batch, len(self.queue)))]
            body = [{"Body": json.dumps(m, separators=(",", ":"))} for m in msgs]
            url = f"https://{self.target.namespace}/{self.target.hub}/messages?timeout=60"
            r = await self._client.post(url, content=json.dumps(body), headers={
                "Authorization": self.target.sas_token(),
                "Content-Type": "application/vnd.microsoft.servicebus.json"})
            if r.status_code >= 300:
                self.failed_batches += 1
                self.last_error = f"{r.status_code} {r.text[:200]}"
                log.warning("eventstream send failed: %s", self.last_error)
                return
            self.sent += len(msgs)
            self.last_sent_at = datetime.now(timezone.utc).isoformat()

    def status(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "target": f"{self.target.namespace}/{self.target.hub}" if self.target else None,
                "queued": len(self.queue), "sent": self.sent, "dropped": self.dropped,
                "failed_batches": self.failed_batches, "last_error": self.last_error, "last_sent_at": self.last_sent_at}


def tracking_summary(frame: list[Any] | None, roster: list[Any]) -> dict[str, Any] | None:
    """1 Hz tracking downsample: ball, centroid, width/depth per team (outfield), compact positions."""
    if not frame:
        return None
    _t, fnum, ball, players = frame
    side = {p.idx: p.side for p in roster}
    gk = {p.idx for p in roster if (p.position_group or "").upper() == "GK"}
    out: dict[str, Any] = {"frame_num": fnum, "ball": ball,
                           "players_observed_pct": round(100 * sum(p[3] for p in players) / len(players), 1) if players else None,
                           "players": [[p[0], p[1], p[2], p[3]] for p in players]}
    for s in ("home", "away"):
        pts = [(p[1], p[2]) for p in players if side.get(p[0]) == s and p[0] not in gk]
        if len(pts) >= 5:
            xs, ys = [x for x, _ in pts], [y for _, y in pts]
            out[s] = {"cx": round(sum(xs) / len(xs), 2), "cy": round(sum(ys) / len(ys), 2),
                      "width": round(max(ys) - min(ys), 2), "depth": round(max(xs) - min(xs), 2)}
        else:
            out[s] = {}
    return out
