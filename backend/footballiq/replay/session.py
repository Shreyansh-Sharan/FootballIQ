"""One WebSocket replay session: virtual clock plus event and tracking dispatch up to replay_t.

Server messages carry ``generation_id`` and ``replay_t_ms``; clients send play, pause, speed or seek.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from footballiq.replay.clock import VirtualClock
from footballiq.replay.timeline import MatchTimeline, event_payload, is_key_event

TICK_S = 0.1
RECENT_ON_RESET = 40
# protects slow clients at high speed
MAX_EVENTS_PER_TICK = 200
# 30 Hz gives 3 frames per tick at 1x; thinned beyond this
MAX_FRAMES_PER_TICK = 6

TELEMETRY_EVERY_S = 5.0

if TYPE_CHECKING:
    from footballiq.realtime import EventstreamPublisher

Send = Callable[[dict[str, Any]], Awaitable[None]]


class ReplaySession:
    def __init__(self, timeline: MatchTimeline, send: Send, clock: VirtualClock | None = None,
                 publisher: "EventstreamPublisher | None" = None,
                 predictions: "Callable[[int], dict[str, Any] | None] | None" = None):
        self.timeline = timeline
        self.send = send
        self.clock = clock or VirtualClock(timeline.match.duration_ms)
        self.last_sent_ms = -1
        self._last_frame_id: str | None = None
        # Eventstream analytics; never awaited by the replay loop
        self.publisher = publisher if publisher is not None and publisher.enabled else None
        self.session_id = uuid.uuid4().hex[:12]
        self._last_pub_s = -1
        self._predictions = predictions
        self._last_pred_cutoff: int | None = None
        self._last_telemetry = 0.0
        self._frames_sent = 0
        self._events_sent = 0
        self._tick_ms = 0.0

    def _pub(self, stream: str, t: int, payload: dict[str, Any]) -> None:
        if self.publisher:
            self.publisher.publish(stream, self.timeline.match.canonical_match_id, self.session_id,
                                   self.clock.generation, t, payload)

    def _publish_second(self, t: int) -> None:
        """match.state + match.tracking.1s once per replay second (data at or before t only)."""
        if not self.publisher or t // 1000 == self._last_pub_s:
            return
        self._last_pub_s = t // 1000
        st = self.timeline.state_at(t)
        m = self.timeline.match
        self._pub("match.state", t, {
            "clock_label": st["clock_label"], "period": st["period"], "home_team_id": m.home.team_id,
            "away_team_id": m.away.team_id, "home_score": st["score"][m.home.team_id], "away_score": st["score"][m.away.team_id],
            "shootout": st["shootout"], "stats": st["stats"]})
        tr = self.timeline.tracking
        if tr is not None:
            from footballiq.realtime import tracking_summary

            summary = tracking_summary(tr.latest_frame(t, max_age_ms=1500), tr.players)
            if summary:
                self._pub("match.tracking.1s", t, summary)
        if self._predictions is not None:
            pred = self._predictions(t)  # in-memory lookup; None until the match's predictions are cached
            if pred and pred["feature_cutoff_ms"] != self._last_pred_cutoff:
                self._last_pred_cutoff = pred["feature_cutoff_ms"]
                self._pub("match.predictions", t, pred)

    def _publish_telemetry(self, kind: str, force: bool = False) -> None:
        now = time.monotonic()
        if not self.publisher or (not force and now - self._last_telemetry < TELEMETRY_EVERY_S):
            return
        self._last_telemetry = now
        self._pub("replay.telemetry", self.clock.current_ms, {
            "kind": kind, "speed": self.clock.speed, "paused": self.clock.paused, "frames_sent": self._frames_sent,
            "events_sent": self._events_sent, "server_tick_ms": round(self._tick_ms, 2)})

    def _envelope(self, kind: str, **payload: Any) -> dict[str, Any]:
        return {
            "type": kind,
            "generation_id": self.clock.generation,
            "replay_t_ms": self.clock.current_ms,
            "speed": self.clock.speed,
            "paused": self.clock.paused,
            **payload,
        }

    async def send_reset(self) -> None:
        t = self.clock.current_ms
        k = self.timeline.index_at(t)
        recent = [event_payload(e) for e in self.timeline.events[max(0, k - RECENT_ON_RESET):k]]
        key = [event_payload(e) for e in self.timeline.events[:k] if is_key_event(e)]
        self.last_sent_ms = t
        self._last_frame_id = None
        await self.send(self._envelope("reset", state=self.timeline.state_at(t), recent_events=recent, key_events=key))
        self._last_pub_s = -1
        self._last_pred_cutoff = None
        self._publish_telemetry("reset", force=True)
        self._publish_second(t)
        await self._maybe_send_snapshot(t)
        tracking = self.timeline.tracking
        if tracking is not None:
            latest = tracking.latest_frame(t)
            await self.send(self._envelope("frames", frames=[latest] if latest else []))

    async def send_tracking_meta(self) -> None:
        tracking = self.timeline.tracking
        await self.send(self._envelope(
            "tracking_meta", available=tracking is not None,
            roster=tracking.roster() if tracking else [],
            coverage=tracking.coverage() if tracking else None,
            source=tracking.source if tracking else None,
            wire_format="frames: [t_ms, frame_num, [ball_x, ball_y, ball_z, ball_observed] | null, "
                        "[[player_idx, x_m, y_m, observed], ...]]"))

    async def _maybe_send_snapshot(self, t: int) -> None:
        ff = self.timeline.freeze_frame_at(t)
        ff_id = ff.event_id if ff else None
        if ff_id != self._last_frame_id:
            self._last_frame_id = ff_id
            await self.send(self._envelope("snapshot", freeze_frame=ff.model_dump() if ff else None))

    async def tick(self) -> None:
        t0 = time.perf_counter()
        t = self.clock.current_ms
        if t != self.last_sent_ms:
            for ev in self.timeline.events_between(self.last_sent_ms, t)[-MAX_EVENTS_PER_TICK:]:
                payload = event_payload(ev)
                await self.send(self._envelope("event", event=payload))
                self._events_sent += 1
                self._pub("match.events", ev.match_elapsed_ms, payload)
            if self.timeline.tracking is not None and t > self.last_sent_ms:
                frames = self.timeline.tracking.frames_between(self.last_sent_ms, t, MAX_FRAMES_PER_TICK)
                if frames:
                    await self.send(self._envelope("frames", frames=frames))
                    self._frames_sent += len(frames)
            self.last_sent_ms = t
            self._publish_second(t)
            await self._maybe_send_snapshot(t)
        await self.send(self._envelope("state", state=self.timeline.state_at(t)))
        if self.clock.finished and not self.clock.paused:
            self.clock.pause()
        self._tick_ms = (time.perf_counter() - t0) * 1000
        self._publish_telemetry("heartbeat")

    async def handle(self, msg: dict[str, Any]) -> None:
        action = msg.get("action")
        if action == "play":
            if self.clock.finished:
                self.clock.seek(0)
                await self.send_reset()
            self.clock.play()
        elif action == "pause":
            self.clock.pause()
        elif action == "speed":
            self.clock.set_speed(float(msg["speed"]))
        elif action == "seek":
            self.clock.seek(int(msg["to_ms"]))
            await self.send_reset()
        else:
            await self.send({"type": "error", "message": f"unknown action {action!r}"})

    async def run(self, receive: Callable[[], Awaitable[dict[str, Any]]]) -> None:
        await self.send_tracking_meta()
        await self.send_reset()

        async def reader() -> None:
            while True:
                msg = await receive()
                try:
                    await self.handle(msg)
                except (KeyError, ValueError, TypeError) as exc:
                    await self.send({"type": "error", "message": str(exc)})

        reader_task = asyncio.create_task(reader())
        try:
            while not reader_task.done():
                await self.tick()
                await asyncio.sleep(TICK_S)
            reader_task.result()  # surface disconnects
        finally:
            reader_task.cancel()
