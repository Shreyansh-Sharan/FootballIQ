import asyncio

from footballiq.realtime import EventHubTarget, EventstreamPublisher, tracking_summary
from footballiq.replay.session import ReplaySession
from footballiq.replay.timeline import MatchTimeline
from tests.test_tracking import make_tracking

CS = "Endpoint=sb://ns1.servicebus.windows.net/;SharedAccessKeyName=key_1;SharedAccessKey=c2VjcmV0;EntityPath=hub1"


def test_connection_string_and_sas():
    t = EventHubTarget.from_connection_string(CS)
    assert (t.namespace, t.hub, t.key_name) == ("ns1.servicebus.windows.net", "hub1", "key_1")
    sas = t.sas_token()
    assert sas.startswith("SharedAccessSignature sr=https%3A%2F%2Fns1.servicebus.windows.net%2Fhub1&sig=")
    assert "&skn=key_1" in sas


def test_publisher_never_blocks_and_drops_oldest():
    p = EventstreamPublisher(EventHubTarget.from_connection_string(CS), max_queue=3)
    for i in range(5):
        p.publish("match.events", "m", "s", 0, i, {"i": i})
    assert len(p.queue) == 3 and p.dropped == 2
    assert [m["payload"]["i"] for m in p.queue] == [2, 3, 4]
    assert EventstreamPublisher(None).enabled is False


def test_tracking_summary_shape():
    tr = make_tracking()
    s = tracking_summary(tr.latest_frame(1000), tr.players)
    assert s["frame_num"] and s["players"] and "home" in s and "away" in s


def test_session_publishes_only_up_to_clock(timeline):
    tl = MatchTimeline(timeline.match, timeline.events, timeline.frames, tracking=make_tracking())
    pub = EventstreamPublisher(EventHubTarget.from_connection_string(CS))

    class Clock:
        generation, speed, paused, finished, duration_ms, current_ms = 0, 1.0, False, False, 10_000_000, 0

    async def noop(_m):
        return None

    clock = Clock()
    s = ReplaySession(tl, noop, clock=clock, publisher=pub)
    asyncio.run(s.send_reset())
    clock.current_ms = 11 * 60_000
    asyncio.run(s.tick())
    msgs = list(pub.queue)
    streams = {m["stream"] for m in msgs}
    assert {"match.state", "match.events", "replay.telemetry"} <= streams
    assert all(m["replay_t_ms"] <= clock.current_ms for m in msgs)
    goal = [m for m in msgs if m["stream"] == "match.events" and m["payload"]["is_goal"]]
    assert [m["payload"]["event_id"] for m in goal] == ["e4"]  # the 65' goal has not been reached


def test_session_publishes_predictions_on_grid_change(timeline):
    pub = EventstreamPublisher(EventHubTarget.from_connection_string(CS))
    asked = []

    def predictions(t):
        asked.append(t)
        cutoff = t // 15_000 * 15_000
        return {"model_version": "v1", "feature_cutoff_ms": cutoff, "phase": "regulation", "rows": [{"target": "goal_next_10m", "p": 0.1}]}

    class Clock:
        generation, speed, paused, finished, duration_ms, current_ms = 0, 1.0, False, False, 10_000_000, 0

    async def noop(_m):
        return None

    clock = Clock()
    s = ReplaySession(timeline, noop, clock=clock, publisher=pub, predictions=predictions)
    for t in (0, 5_000, 14_000, 16_000, 29_000, 31_000):
        clock.current_ms = t
        s._publish_second(t)
    preds = [m for m in pub.queue if m["stream"] == "match.predictions"]
    assert [m["payload"]["feature_cutoff_ms"] for m in preds] == [0, 15_000, 30_000]  # once per grid step
    assert all(m["payload"]["feature_cutoff_ms"] <= m["replay_t_ms"] for m in preds)
