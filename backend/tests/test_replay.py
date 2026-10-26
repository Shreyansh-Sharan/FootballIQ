import pytest

from footballiq.replay.clock import VirtualClock


class FakeTime:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_clock_play_pause_speed_seek():
    now = FakeTime()
    c = VirtualClock(10_000, now=now)
    assert c.paused and c.current_ms == 0
    c.play()
    now.t += 1
    assert c.current_ms == 1000
    c.set_speed(5.0)
    now.t += 1
    assert c.current_ms == 6000
    c.pause()
    now.t += 10
    assert c.current_ms == 6000
    gen = c.generation
    c.seek(2000)
    assert c.current_ms == 2000 and c.generation == gen + 1
    c.play()
    now.t += 100
    assert c.current_ms == 10_000 and c.finished
    with pytest.raises(ValueError):
        c.set_speed(3.0)


def test_score_never_leaks_future(timeline):
    # goal at 10:00 (home), goal at 65:00 (away)
    assert timeline.state_at(9 * 60_000)["score"] == {"home-fc": 0, "away-fc": 0}
    assert timeline.state_at(10 * 60_000)["score"] == {"home-fc": 1, "away-fc": 0}
    assert timeline.state_at(64 * 60_000)["score"] == {"home-fc": 1, "away-fc": 0}
    assert timeline.state_at(66 * 60_000)["score"] == {"home-fc": 1, "away-fc": 1}


def test_counters(timeline):
    s = timeline.state_at(timeline.match.duration_ms)["stats"]
    assert s["home-fc"]["passes_attempted"] == 2 and s["home-fc"]["passes_completed"] == 2
    assert s["away-fc"]["pass_accuracy_pct"] == 0.0
    assert s["home-fc"]["corners"] == 1
    assert s["away-fc"]["provider_xg"] == 0.7
    assert s["home-fc"]["possession_pct"] + s["away-fc"]["possession_pct"] == pytest.approx(100, abs=0.2)


def test_events_between_is_cutoff_bounded(timeline):
    evs = timeline.events_between(-1, 10 * 60_000)
    assert evs[-1].event_id == "e4"
    assert all(e.match_elapsed_ms <= 10 * 60_000 for e in evs)


def test_freeze_frame_ttl(timeline):
    assert timeline.freeze_frame_at(10 * 60_000 + 1000).event_id == "e4"
    assert timeline.freeze_frame_at(10 * 60_000 + 60_000) is None
    assert timeline.freeze_frame_at(1000) is None
