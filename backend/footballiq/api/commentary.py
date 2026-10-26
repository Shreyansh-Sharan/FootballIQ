"""Commentary endpoints (docs/MATCHDAY_API.md): lines cut at the replay clock, and their audio."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from footballiq.commentary.service import CommentaryService, NotReady
from footballiq.replay.timeline import MatchTimeline

LANG = "^(en|es|hi)$"


def commentary_router(get_timeline: Callable[[str], MatchTimeline], service: CommentaryService) -> APIRouter:
    r = APIRouter(tags=["commentary"])

    @r.get("/v1/matches/{match_id}/commentary")
    def commentary(match_id: str, lang: str = Query("en", pattern=LANG), to_ms: int = Query(..., ge=0, description="Replay cutoff"),
                   from_ms: int = Query(-1, ge=-1)) -> dict[str, Any]:
        return service.lines(get_timeline(match_id), lang, from_ms, to_ms)

    @r.get("/v1/matches/{match_id}/commentary/audio/{line_id}")
    def commentary_audio(match_id: str, line_id: str, lang: str = Query("en", pattern=LANG)) -> Response:
        try:
            data = service.audio(get_timeline(match_id), lang, line_id)
        except NotReady as exc:
            return Response(content=f'{{"detail": "{exc}"}}', status_code=503, media_type="application/json", headers={"Retry-After": "5"})
        if data is None:
            raise HTTPException(status_code=404, detail="no such commentary line")
        return Response(content=data, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})

    @r.get("/v1/commentary/status")
    def commentary_status() -> dict[str, Any]:
        return service.speech.status()

    return r
