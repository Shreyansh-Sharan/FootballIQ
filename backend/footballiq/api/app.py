"""FastAPI replay service. Every match-scoped endpoint is bounded by the replay cutoff (``to_ms`` / ``at_ms``).

Fabric data is read once per match into memory; the replay loop never queries Fabric.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from footballiq import __version__, config
from footballiq.agents import foundry
from footballiq.agents.definitions import AGENTS
from footballiq.agents.service import AgentService
from footballiq.aliases import AliasedStore, get_book
from footballiq.api.commentary import commentary_router
from footballiq.api.privacy import install_privacy
from footballiq.api.matchday import matchday_router
from footballiq.ball_flight import flight as ball_flight
from footballiq.coach import CoachService
from footballiq.history import pre_match
from footballiq.commentary.colour import FoundryColour
from footballiq.commentary.engine import LANGS as COMMENTARY_LANGS
from footballiq.commentary.service import CommentaryService
from footballiq.matchday.service import MatchdayService
from footballiq.ml.retro import MODE_RETRO, MODE_STRICT
from footballiq.predictions import PredictionStore
from footballiq.realtime import EventstreamPublisher, resolve_target
from footballiq.replay.session import ReplaySession
from footballiq.replay.timeline import MatchTimeline, event_payload
from footballiq.shots import shot_rows
from footballiq.shots import summary as shot_summary
from footballiq.store import default_store
from footballiq.tactical import TacticalStore, WindowNotComplete

log = logging.getLogger(__name__)
MAX_FRAME_WINDOW_MS = 60_000


class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    at_ms: int = Field(..., ge=0, description="Replay clock; the agent sees nothing after it")
    thread_id: str | None = Field(None, max_length=100)


class ExplainBody(BaseModel):
    at_ms: int = Field(..., ge=0)


def create_app(store=None, publisher: EventstreamPublisher | None = None) -> FastAPI:
    config.load_dotenv()   # real environment variables take precedence
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # warm in the background so startup is instant
        def warm() -> None:
            try:
                app.state.store.match_ids()
                for mid in filter(None, os.environ.get("FOOTBALLIQ_PRELOAD", "").split(",")):
                    if hasattr(app.state.store, "pin"):
                        app.state.store.pin(mid.strip())   # preloaded matches never leave memory
                    app.state.store.get(mid.strip())
                    if getattr(app.state.store, "lh", None) is not None:   # strict forecasts too, so the first view has numbers
                        try:
                            prediction_store().latest(mid.strip(), 0)
                        except Exception:  # noqa: BLE001 - model tables may not exist yet; endpoints report that
                            log.info("no model outputs to warm for %s", mid)
                coach = coach_service()
                coach.warm_history(block=True)         # tournament form for coach reasoning
                for mid in filter(None, os.environ.get("FOOTBALLIQ_PRELOAD", "").split(",")):
                    coach.insights(mid.strip(), 0)     # precomputes the insight timeline
                    app.state.matchday.data(app.state.store.get(mid.strip()))
                    for lang in COMMENTARY_LANGS:                                  # includes the analyst rewrite
                        app.state.commentary.script(app.state.store.get(mid.strip()), lang)
            except Exception:  # surfaced via /health
                log.exception("warm-up failed")
                app.state.warm_error = "catalogue load failed; see server log"

        threading.Thread(target=warm, daemon=True).start()
        if app.state.publisher is None:
            try:
                target = await run_in_threadpool(resolve_target)
            except Exception:
                log.exception("eventstream connection lookup failed - publishing disabled")
                target = None
            app.state.publisher = EventstreamPublisher(target)
        await app.state.publisher.start()
        yield
        await app.state.publisher.stop()

    app = FastAPI(title="Football IQ Replay API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    book = get_book()   # FOOTBALLIQ_PSEUDONYMS=off disables aliasing
    app.state.store = AliasedStore(store or default_store(), book) if book.enabled else (store or default_store())
    app.state.warm_error = None
    app.state.publisher = publisher
    app.state.tactical = None
    app.state.predictions = None
    app.state.agents = None
    app.state.coach = None
    app.state.ai_takes = {}

    def allowed(match_id: str | None) -> bool:
        """FOOTBALLIQ_MATCHES (comma-separated ids) limits the app to those matches; unset allows all."""
        only = {m.strip() for m in os.environ.get("FOOTBALLIQ_MATCHES", "").split(",") if m.strip()}
        return not only or match_id in only

    def get_timeline(match_id: str) -> MatchTimeline:
        tl = app.state.store.get(match_id) if allowed(match_id) else None
        if tl is None:
            raise HTTPException(status_code=404, detail=f"match {match_id!r} not found")
        return tl

    @app.get("/health")
    def health() -> dict[str, Any]:
        status = app.state.store.status()
        pub = app.state.publisher.status() if app.state.publisher else {"enabled": False}
        return {"status": "error" if app.state.warm_error else "ok", "version": __version__,
                "error": app.state.warm_error, **status, "eventstream": pub}

    @app.get("/v1/matches")
    def list_matches() -> list[dict[str, Any]]:
        featured = next(iter(filter(None, os.environ.get("FOOTBALLIQ_PRELOAD", "").split(","))), "").strip()
        return [{**s, "featured": s.get("match_id") == featured} for s in app.state.store.summaries() if allowed(s.get("match_id"))]

    @app.get("/v1/matches/{match_id}/overview")
    def overview(match_id: str) -> dict[str, Any]:
        tl = get_timeline(match_id)
        out = tl.match.model_dump(exclude={"result"})
        out["tracking"] = tl.tracking.coverage() if tl.tracking is not None else None
        return out

    @app.get("/v1/matches/{match_id}/events")
    def events(
        match_id: str,
        to_ms: int = Query(..., ge=0, description="Replay cutoff; nothing later is returned"),
        from_ms: int = Query(-1, ge=-1),
        limit: int = Query(5000, ge=1, le=10000),
    ) -> dict[str, Any]:
        tl = get_timeline(match_id)
        evs = tl.events_between(from_ms, to_ms)
        return {"match_id": match_id, "from_ms": from_ms, "to_ms": to_ms, "events": [event_payload(e) for e in evs[-limit:]]}

    @app.get("/v1/matches/{match_id}/state")
    def state(match_id: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        return get_timeline(match_id).state_at(at_ms)

    @app.get("/v1/matches/{match_id}/freeze-frame")
    def freeze_frame(match_id: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        ff = get_timeline(match_id).freeze_frame_at(at_ms)
        return {"at_ms": at_ms, "freeze_frame": ff.model_dump() if ff else None}

    @app.get("/v1/matches/{match_id}/history")
    def history(match_id: str, last_n: int = Query(6, ge=1, le=20)) -> dict[str, Any]:
        tl = get_timeline(match_id)
        return pre_match(tl.match, app.state.store.all_matches(), last_n)

    def tactical_store():
        if app.state.tactical is None:
            lh = getattr(app.state.store, "lh", None)
            if lh is None:
                raise HTTPException(status_code=404, detail="tactical/physical views need the Fabric source (FOOTBALLIQ_SOURCE=fabric)")
            app.state.tactical = TacticalStore(lh)
        return app.state.tactical

    @app.get("/v1/matches/{match_id}/tactical/windows")
    def tactical_windows(match_id: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        get_timeline(match_id)
        return {"match_id": match_id, "at_ms": at_ms, "windows": tactical_store().windows(match_id, at_ms)}

    @app.get("/v1/matches/{match_id}/tactical")
    def tactical_window(match_id: str, team: str, window: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        get_timeline(match_id)
        try:
            return tactical_store().window(match_id, team, window, at_ms)
        except WindowNotComplete as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/matches/{match_id}/tactical/timeline")
    def tactical_timeline(match_id: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        get_timeline(match_id)
        return {"match_id": match_id, "at_ms": at_ms, "windows": tactical_store().timeline(match_id, at_ms)}

    @app.get("/v1/matches/{match_id}/tactical/formations")
    def tactical_formations(match_id: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        get_timeline(match_id)
        return {"match_id": match_id, "at_ms": at_ms, **tactical_store().formations(match_id, at_ms)}

    @app.get("/v1/matches/{match_id}/physical")
    def physical(match_id: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        get_timeline(match_id)
        return {"match_id": match_id, "at_ms": at_ms, "hsr_threshold_mps": 5.5, "sprint_threshold_mps": 7.0,
                "source": "per-second tracking metrics, summed over seconds <= at_ms",
                "players": tactical_store().physical(match_id, at_ms)}

    def prediction_store(mode: str = MODE_STRICT) -> PredictionStore:
        """``strict`` (default, live stream included) is chronological; ``retrospective`` only on explicit request."""
        if app.state.predictions is None:
            app.state.predictions = {}
        if mode not in app.state.predictions:
            lh = getattr(app.state.store, "lh", None)
            if lh is None:
                raise HTTPException(status_code=404, detail="model outputs need the Fabric source (FOOTBALLIQ_SOURCE=fabric)")
            app.state.predictions[mode] = PredictionStore(lh, mode=mode)
        return app.state.predictions[mode]

    def _models_ready(fn):
        try:
            return fn()
        except HTTPException:
            raise
        except Exception as exc:  # tables missing until nb_ml_train + nb_ml_score have run
            log.warning("model outputs unavailable: %s", exc)
            raise HTTPException(status_code=503, detail="model outputs not available yet - run nb_ml_train and nb_ml_score in Fabric "
                                "(MODE=retrospective for the cross-fit)") from exc

    @app.get("/v1/matches/{match_id}/predictions")
    def predictions(match_id: str, at_ms: int = Query(..., ge=0), mode: str = Query(MODE_STRICT, pattern=f"^({MODE_STRICT}|{MODE_RETRO})$")) -> dict[str, Any]:
        get_timeline(match_id)
        return _models_ready(lambda: prediction_store(mode).latest(match_id, at_ms))

    @app.get("/v1/matches/{match_id}/predictions/series")
    def prediction_series(match_id: str, at_ms: int = Query(..., ge=0), mode: str = Query(MODE_STRICT, pattern=f"^({MODE_STRICT}|{MODE_RETRO})$")) -> dict[str, Any]:
        get_timeline(match_id)
        return _models_ready(lambda: prediction_store(mode).series(match_id, at_ms))

    @app.get("/v1/matches/{match_id}/model-values")
    def model_values(match_id: str, at_ms: int = Query(..., ge=0), mode: str = Query(MODE_STRICT, pattern=f"^({MODE_STRICT}|{MODE_RETRO})$")) -> dict[str, Any]:
        get_timeline(match_id)
        return _models_ready(lambda: prediction_store(mode).event_values(match_id, at_ms))

    @app.get("/v1/matches/{match_id}/shots")
    def shots(match_id: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        """Shots up to the replay clock, with our xG and the benchmark xG."""
        tl = get_timeline(match_id)
        try:
            model_xg, version = prediction_store().xg_by_event(match_id, at_ms)
        except Exception:  # noqa: BLE001 - shots still work with provider xG only
            model_xg, version = {}, None
        frames = {f.event_id: f for f in tl.frames}
        rows = shot_rows(tl.events_between(-1, at_ms), frames, tl.match.home.team_id, model_xg)
        by_id = {e.event_id: e for e in tl.events}
        for r in rows:   # ball flight for goals, from tracking when available
            if r["is_goal"]:
                f = ball_flight(tl.tracking, by_id[r["event_id"]], r["team_id"] == tl.match.home.team_id, at_ms)
                r["flight"] = {k: v for k, v in f.items() if k != "path"}
        return {"match_id": match_id, "at_ms": at_ms, "model_version": version, "shots": rows,
                "teams": shot_summary(rows, [tl.match.home.team_id, tl.match.away.team_id])}

    @app.get("/v1/matches/{match_id}/shots/{event_id}/flight")
    def shot_flight(match_id: str, event_id: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        """Ball path of one shot from tracking, cut at the replay clock."""
        tl = get_timeline(match_id)
        ev = next((e for e in tl.events if e.event_id == event_id and e.type == "Shot"), None)
        if ev is None or ev.match_elapsed_ms > at_ms:
            raise HTTPException(status_code=404, detail="shot not found before the replay clock")
        return {"event_id": event_id, **ball_flight(tl.tracking, ev, ev.team_id == tl.match.home.team_id, at_ms)}

    # ---- coach
    def coach_service() -> CoachService:
        if app.state.coach is None:
            fabric = getattr(app.state.store, "lh", None) is not None
            app.state.coach = CoachService(app.state.store, predictions=(lambda: prediction_store()) if fabric else None,
                                           tactical=(lambda: tactical_store()) if fabric else None)
        return app.state.coach

    def _coach_call(fn):
        try:
            return fn()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"match {exc} not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/matches/{match_id}/insights")
    def insights(match_id: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        """Automatic insights up to the replay clock."""
        return _coach_call(lambda: coach_service().insights(match_id, at_ms))

    @app.get("/v1/matches/{match_id}/prematch/profile")
    def prematch_profile(match_id: str) -> dict[str, Any]:
        """Pre-match tournament profile, key players and players on a yellow card."""
        return _coach_call(lambda: coach_service().prematch(match_id))

    @app.get("/v1/matches/{match_id}/players")
    def players(match_id: str, at_ms: int = Query(..., ge=0), team: str | None = None) -> dict[str, Any]:
        return _coach_call(lambda: coach_service().players(match_id, at_ms, team))

    @app.get("/v1/matches/{match_id}/players/substitutions")
    def substitutions(match_id: str, team: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        return _coach_call(lambda: coach_service().substitutions(match_id, at_ms, team))

    @app.get("/v1/matches/{match_id}/players/best")
    def best_player(match_id: str, team: str, situation: str, at_ms: int = Query(..., ge=0)) -> dict[str, Any]:
        return _coach_call(lambda: coach_service().best(match_id, at_ms, team, situation))

    @app.post("/v1/matches/{match_id}/insights/{insight_id}/ai")
    def insight_ai(match_id: str, insight_id: str) -> dict[str, Any]:
        """Moment Explainer take on one insight, cached."""
        key = (match_id, insight_id)
        if key in app.state.ai_takes:
            return app.state.ai_takes[key]
        ins = _coach_call(lambda: coach_service().find_insight(match_id, insight_id))
        if ins is None:
            raise HTTPException(status_code=404, detail="unknown insight (request /insights first)")
        focus = f"{ins['minute']} {ins['title']}. {ins['detail']}"
        out = _agent_call(lambda: agent_service().explain(match_id, ins["t_ms"], focus=focus))
        app.state.ai_takes[key] = {**out, "insight_id": insight_id}
        return app.state.ai_takes[key]

    # ---- Foundry agents
    def agent_service() -> AgentService:
        if not foundry.configured():
            raise HTTPException(status_code=503, detail="Foundry agents are not configured: set FOUNDRY_PROJECT_ENDPOINT, "
                                "FOUNDRY_TENANT_ID, FOUNDRY_CLIENT_ID and FOUNDRY_CLIENT_SECRET (see .env.example)")
        if app.state.agents is None:
            fabric = getattr(app.state.store, "lh", None) is not None
            app.state.agents = AgentService(app.state.store, foundry.FoundryClient(),
                                            predictions=(lambda: prediction_store()) if fabric else None,
                                            tactical=(lambda: tactical_store()) if fabric else None, coach=coach_service())
        return app.state.agents

    def _agent_call(fn):
        try:
            return fn()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"match {exc} not found") from exc
        except foundry.FoundryError as exc:
            log.warning("Foundry agent call failed: %s", exc)
            raise HTTPException(status_code=502, detail=f"Foundry agent error: {exc}") from exc

    @app.get("/v1/agents")
    def agents_status() -> dict[str, Any]:
        """Agent ids and model in use; never credentials."""
        if not foundry.configured():
            return {"configured": False, "agents": {}}
        svc = agent_service()
        return {"configured": True, "endpoint": svc.client.endpoint, "model": foundry.default_model(),
                "agents": {k: {"name": spec.name, "id": svc.client.agent_id(k)} for k, spec in AGENTS.items()}}

    @app.post("/v1/matches/{match_id}/agents/ask")
    def agent_ask(match_id: str, body: AskBody) -> dict[str, Any]:
        """Match Strategist: one question at the replay clock (follow-ups reuse thread_id)."""
        return _agent_call(lambda: agent_service().ask(match_id, body.at_ms, body.question, body.thread_id))

    @app.post("/v1/matches/{match_id}/agents/explain")
    def agent_explain(match_id: str, body: ExplainBody) -> dict[str, Any]:
        """Moment Explainer card for the replay clock."""
        return _agent_call(lambda: agent_service().explain(match_id, body.at_ms))

    @app.get("/v1/models")
    def models(version: str | None = None, mode: str = Query(MODE_STRICT, pattern=f"^({MODE_STRICT}|{MODE_RETRO})$")) -> dict[str, Any]:
        return _models_ready(lambda: prediction_store(mode).models(version))

    @app.get("/v1/matches/{match_id}/tracking")
    def tracking(match_id: str) -> dict[str, Any]:
        tr = get_timeline(match_id).tracking
        if tr is None:
            return {"match_id": match_id, "available": False}
        return {"match_id": match_id, "available": True, "source": tr.source, "coverage": tr.coverage(),
                "roster": tr.roster()}

    @app.get("/v1/matches/{match_id}/frames")
    def frames(
        match_id: str,
        to_ms: int = Query(..., ge=0, description="Replay cutoff; no frame after it is returned"),
        from_ms: int = Query(None, ge=-1, description=f"Defaults to to_ms - 1000; window at most {MAX_FRAME_WINDOW_MS} ms"),
        max_frames: int = Query(300, ge=1, le=2000),
    ) -> dict[str, Any]:
        tr = get_timeline(match_id).tracking
        if tr is None:
            raise HTTPException(status_code=404, detail="no tracking data for this match")
        start = to_ms - 1000 if from_ms is None else from_ms
        if to_ms - start > MAX_FRAME_WINDOW_MS:
            raise HTTPException(status_code=422, detail=f"window larger than {MAX_FRAME_WINDOW_MS} ms")
        return {"match_id": match_id, "from_ms": start, "to_ms": to_ms,
                "frames": tr.frames_between(start, to_ms, max_frames)}

    @app.websocket("/v1/matches/{match_id}/replay")
    async def replay(ws: WebSocket, match_id: str) -> None:
        await ws.accept()
        await ws.send_json({"type": "loading", "match_id": match_id})
        try:
            tl = await run_in_threadpool(app.state.store.get, match_id)
        except Exception:
            log.exception("loading %s failed", match_id)
            tl = None
            await ws.send_json({"type": "error", "message": f"could not load match {match_id!r}"})
        if tl is None:
            await ws.send_json({"type": "error", "message": f"match {match_id!r} not found"})
            await ws.close(code=4404)
            return
        predictions = None
        if app.state.publisher is not None and app.state.publisher.enabled and getattr(app.state.store, "lh", None) is not None:
            store = prediction_store()
            store.warm(match_id)
            predictions = lambda t: store.stream_payload(match_id, t)
        session = ReplaySession(tl, ws.send_json, publisher=app.state.publisher, predictions=predictions)
        try:
            await session.run(ws.receive_json)
        except WebSocketDisconnect:
            pass

    app.state.matchday = MatchdayService(tactical=tactical_store, predictions=prediction_store)
    app.include_router(matchday_router(get_timeline, app.state.matchday))
    app.state.commentary = CommentaryService(
        app.state.matchday, colour_writer=FoundryColour().polish if FoundryColour.available() else None)
    app.include_router(commentary_router(get_timeline, app.state.commentary))

    if book.enabled:
        install_privacy(app)   # outermost, so every response is aliased
    return app


app = create_app()
