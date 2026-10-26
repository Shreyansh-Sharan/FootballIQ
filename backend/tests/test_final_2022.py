"""Acceptance checks on the Argentina v France 2022 final; skipped unless it has been ingested."""


def ms(minute: int, second: int = 0, period_start: int = 0) -> int:
    return period_start + (minute * 60 + second) * 1000


def test_final_score_chronology(final_timeline):
    tl = final_timeline
    goals = [(e.clock_label, e.team_id) for e in tl.events if e.is_goal and not e.is_shootout]
    assert [t for _, t in goals] == ["argentina", "argentina", "france", "france", "argentina", "france"]
    end = tl.state_at(tl.match.duration_ms)
    assert end["score"] == {"argentina": 3, "france": 3}
    assert end["shootout"] == {"argentina": 4, "france": 2}
    assert tl.match.result["shootout"] == {"argentina": 4, "france": 2}
    assert [p.period for p in tl.match.periods] == [1, 2, 3, 4, 5]


def test_no_spoilers_mid_match(final_timeline):
    p2 = next(p for p in final_timeline.match.periods if p.period == 2).start_match_ms
    t = ms(22, 30, p2)  # 67:30 on the scoreboard clock
    st = final_timeline.state_at(t)
    assert st["clock_label"] == "67:30"
    assert st["score"] == {"argentina": 2, "france": 0}
    assert st["shootout"] is None
    assert all(e.match_elapsed_ms <= t for e in final_timeline.events[: st["events_visible"]])


def test_seek_play_rewind_is_deterministic(final_timeline):
    """Seek 67:30, play 60 s, rewind 10 s: same state."""
    p2 = next(p for p in final_timeline.match.periods if p.period == 2).start_match_ms
    t0 = ms(22, 30, p2)
    forward = [final_timeline.state_at(t0 + d) for d in range(0, 60_001, 100)]
    rewind_t = t0 + 50_000
    assert final_timeline.state_at(rewind_t) == forward[500]
    assert final_timeline.events_between(-1, rewind_t) == final_timeline.events[: forward[500]["events_visible"]]
