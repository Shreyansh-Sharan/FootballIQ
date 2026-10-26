"""Matchday endpoints (docs/MATCHDAY_API.md): meta, series, moments and player focus, all cut at the replay clock."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query

from footballiq.matchday.service import MatchdayService, meta, player_focus
from footballiq.replay.timeline import MatchTimeline


def matchday_router(get_timeline: Callable[[str], MatchTimeline], service: MatchdayService) -> APIRouter:
    r = APIRouter(tags=["matchday"])

    @r.get("/v1/matches/{match_id}/matchday/meta")
    def matchday_meta(match_id: str) -> dict[str, Any]:
        tl = get_timeline(match_id)
        return meta(tl, service.data(tl).roles)

    @r.get("/v1/matches/{match_id}/matchday/series")
    def matchday_series(match_id: str, to_ms: int = Query(..., ge=0, description="Replay cutoff")) -> dict[str, Any]:
        return service.data(get_timeline(match_id)).series(to_ms)

    @r.get("/v1/matches/{match_id}/matchday/moments")
    def matchday_moments(match_id: str, to_ms: int = Query(..., ge=0, description="Replay cutoff")) -> dict[str, Any]:
        return {"moments": service.data(get_timeline(match_id)).moments_until(to_ms)}

    @r.get("/v1/matches/{match_id}/matchday/player/{player_id}")
    def matchday_player(match_id: str, player_id: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        out = player_focus(service.data(get_timeline(match_id)), player_id, at_ms)
        if out is None:
            raise HTTPException(status_code=404, detail="player not in this match")
        return out

    return r
