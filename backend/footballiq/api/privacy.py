"""Privacy middleware: clients see only public ids and fictional names; a JSON body that fails to scrub becomes a 500.

Pure ASGI rather than ``BaseHTTPMiddleware``, so streaming responses and WebSockets keep working.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode

from starlette.concurrency import run_in_threadpool

from footballiq.aliases import ALIAS_RE, AliasBook, get_book

log = logging.getLogger(__name__)

ID_PARAMS = frozenset({"team_id", "player_id", "match_id", "team", "player", "match", "player2_id", "recipient_id"})


class UnknownAlias(Exception):
    def __init__(self, alias: str):
        super().__init__(alias)
        self.alias = alias


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> bytes | None:
    for k, v in headers:
        if k.lower() == name:
            return v
    return None


def _is_json(content_type: bytes | None) -> bool:
    if not content_type:
        return False
    base = content_type.split(b";", 1)[0].strip().lower()
    return base == b"application/json" or base.endswith(b"+json")


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, allow_nan=True, separators=(",", ":"))


class PrivacyMiddleware:
    def __init__(self, app: Any, book: AliasBook | None = None):
        self.app = app
        self._book = book

    @property
    def book(self) -> AliasBook:
        return self._book or get_book()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        book = self.book
        if scope["type"] not in ("http", "websocket") or not book.enabled:
            await self.app(scope, receive, send)
            return
        try:
            scope, match_id = await self._translate(scope, book)
        except UnknownAlias as exc:
            await self._reject(scope, send, exc.alias)
            return
        if scope["type"] == "http":
            await self.app(scope, receive, self._http_sender(send, book, match_id))
        else:
            await self.app(scope, receive, self._ws_sender(send, book, match_id))

    # ------------------------------------------------------------------ in
    async def _lookup(self, book: AliasBook, alias: str, match_id: str | None) -> str | None:
        canon = book.to_canonical(alias)
        if canon is None:   # fresh process, or an id only a loaded match knows
            await run_in_threadpool(book.ensure_loaded, match_id)
            canon = book.to_canonical(alias)
        return canon

    async def _translate(self, scope: dict, book: AliasBook) -> tuple[dict, str | None]:
        path: str = scope.get("path", "")
        segs = path.split("/")
        changed: dict[str, str] = {}
        match_id = None
        for i, seg in enumerate(segs):
            if ALIAS_RE.match(seg):
                canon = await self._lookup(book, seg, match_id)
                if canon is None:
                    raise UnknownAlias(seg)
                segs[i] = changed[seg] = canon
            if i > 0 and segs[i - 1] == "matches" and segs[i]:
                match_id = segs[i]
        qs: bytes = scope.get("query_string", b"")
        new_qs = qs
        if qs and b"-" in qs:
            pairs = parse_qsl(qs.decode("latin-1"), keep_blank_values=True)
            out, dirty = [], False
            for k, v in pairs:
                if ALIAS_RE.match(v):
                    canon = await self._lookup(book, v, match_id)
                    if canon is None and k in ID_PARAMS:
                        raise UnknownAlias(v)
                    if canon is not None:
                        v, dirty = canon, True
                out.append((k, v))
            if dirty:
                new_qs = urlencode(out).encode("latin-1")
        if not changed and new_qs is qs:
            return scope, match_id
        scope = dict(scope)
        if changed:
            scope["path"] = "/".join(segs)
            raw = scope.get("raw_path")
            if raw:
                for alias, canon in changed.items():
                    raw = raw.replace(alias.encode(), canon.encode())
                scope["raw_path"] = raw
        scope["query_string"] = new_qs
        return scope, match_id

    async def _reject(self, scope: dict, send: Any, alias: str) -> None:
        body = _dumps({"detail": f"unknown id {alias!r}"}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 404, "headers": headers})
            await send({"type": "http.response.body", "body": body})
        elif "websocket.http.response" in (scope.get("extensions") or {}):
            await send({"type": "websocket.http.response.start", "status": 404, "headers": headers})
            await send({"type": "websocket.http.response.body", "body": body})
        else:
            await send({"type": "websocket.close", "code": 4404})

    # ------------------------------------------------------------------ out
    def _http_sender(self, send: Any, book: AliasBook, match_id: str | None):
        state: dict[str, Any] = {"start": None, "chunks": []}

        async def wrapped(message: dict) -> None:
            kind = message["type"]
            if kind == "http.response.start":
                headers = list(message.get("headers") or [])
                loc = _header(headers, b"location")
                if loc is not None:
                    new_loc = book.to_public(loc.decode("latin-1")).encode("latin-1", "replace")
                    headers = [(k, new_loc if k.lower() == b"location" else v) for k, v in headers]
                message = {**message, "headers": headers}
                if _is_json(_header(headers, b"content-type")) and _header(headers, b"content-encoding") is None:
                    state["start"] = message
                    return
                await send(message)
                return
            if kind == "http.response.body" and state["start"] is not None:
                state["chunks"].append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                start, body = state["start"], b"".join(state["chunks"])
                state["start"], state["chunks"] = None, []
                status = start["status"]
                if not body:            # HEAD or empty body: keep the original headers
                    await send(start)
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                    return
                try:
                    body = _dumps(book.to_public(json.loads(body), match_id)).encode("utf-8")
                except Exception:  # noqa: BLE001 - never let an un-anonymised body out
                    log.exception("could not anonymise a JSON response")
                    body, status = _dumps({"detail": "internal error"}).encode(), 500
                headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode()))
                await send({**start, "status": status, "headers": headers})
                await send({"type": "http.response.body", "body": body, "more_body": False})
                return
            await send(message)

        return wrapped

    def _ws_sender(self, send: Any, book: AliasBook, match_id: str | None):
        async def wrapped(message: dict) -> None:
            if message["type"] == "websocket.send" and message.get("text") is not None:
                text = message["text"]
                try:
                    obj = json.loads(text) if text[:1] in ("{", "[") else None
                except ValueError:
                    obj = None
                text = _dumps(book.to_public(obj, match_id)) if obj is not None else book.to_public(text, match_id)
                message = {**message, "text": text}
            elif message["type"] == "websocket.close" and message.get("reason"):
                message = {**message, "reason": book.to_public(message["reason"], match_id)}
            await send(message)

        return wrapped


def install_privacy(app: Any, book: AliasBook | None = None) -> None:
    """Add the middleware outermost; call after any other ``add_middleware``."""
    if any(getattr(m, "cls", None) is PrivacyMiddleware for m in getattr(app, "user_middleware", [])):
        return
    app.add_middleware(PrivacyMiddleware, book=book)
