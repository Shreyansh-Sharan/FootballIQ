import numpy as np
from fastapi.testclient import TestClient

from footballiq.api.app import create_app
from footballiq.replay.session import ReplaySession
from footballiq.replay.timeline import MatchTimeline
from footballiq.replay.tracking import TrackedPlayer, TrackingTimeline, gaps


def make_tracking(n=300, hz=30):
    # frames delivered out of order and with a 2 s gap to check sorting / gap detection
    t = (np.arange(n) * 1000 / hz).astype(np.int64)
    t[200:] += 2000
    fnum = np.arange(1000, 1000 + n)
    perm = np.random.default_rng(0).permutation(n)
    frames = {"frame_num": fnum[perm], "t": t[perm], "period": np.ones(n, np.int8),
              "ball_x": np.linspace(10, 90, n)[perm].astype(np.float32), "ball_y": np.full(n, 34, np.float32),
              "ball_z": np.zeros(n, np.float32), "ball_observed": (np.arange(n) % 2 == 0)[perm]}
    # two players per frame, positions in random order
    pf = np.repeat(fnum, 2)
    pidx = np.tile([0, 1], n)
    x = np.where(pidx == 0, 20.0, 80.0) + np.repeat(np.arange(n) * 0.01, 2)
    order = np.random.default_rng(1).permutation(2 * n)
    positions = {"frame_num": pf[order], "player_idx": pidx[order], "x": x[order].astype(np.float32),
                 "y": np.full(2 * n, 30, np.float32), "observed": (pidx == 0)[order]}
    players = [TrackedPlayer(0, "home-fc", "home", "9", "home-fc_striker", "Home Striker"),
               TrackedPlayer(1, "away-fc", "away", "1", None, None)]
    return TrackingTimeline.from_columns("m", "test", frames, positions, players)


def test_frames_sorted_and_past_only():
    tr = make_tracking()
    assert np.all(np.diff(tr.frame_t) >= 0)
    fr = tr.frames_between(-1, 1000)
    assert fr and all(f[0] <= 1000 for f in fr)
    t0, fnum, ball, players = fr[0]
    assert t0 == 0 and fnum == 1000 and ball[3] == 1
    assert sorted(p[0] for p in players) == [0, 1]
    home = next(p for p in players if p[0] == 0)
    assert home[1] == 20.0 and home[3] == 1


def test_thinning_keeps_latest_and_bounds():
    tr = make_tracking()
    fr = tr.frames_between(-1, 5000, max_frames=5)
    assert len(fr) == 5
    assert fr[-1][0] == tr.frame_t[tr.index_at(5000) - 1]


def test_latest_frame_age_and_gaps():
    tr = make_tracking()
    gap_start = int(tr.frame_t[199])
    assert tr.latest_frame(gap_start + 1500, max_age_ms=1000) is None  # inside the 2 s gap: no stale frame
    assert gaps(tr.frame_t) == [(gap_start, int(tr.frame_t[200]))]
    cov = tr.coverage()
    assert cov["frames"] == 300 and cov["player_observed_pct"] == 50.0


def test_state_ball_uses_tracking(timeline):
    tl = MatchTimeline(timeline.match, timeline.events, timeline.frames, tracking=make_tracking())
    ball = tl.state_at(100)["ball"]
    assert ball["source"] == "pff_tracking" and "frame_num" in ball


async def _collect(session, n_ticks):
    out = []
    session.send = lambda m: _append(out, m)
    await session.send_tracking_meta()
    await session.send_reset()
    for _ in range(n_ticks):
        await session.tick()
    return out


async def _append(out, m):
    out.append(m)


def test_session_streams_frames_up_to_clock(timeline):
    import asyncio

    tl = MatchTimeline(timeline.match, timeline.events, timeline.frames, tracking=make_tracking())

    class FakeClock:
        generation, speed, paused, finished, duration_ms = 0, 1.0, False, False, 10_000
        current_ms = 0

    clock = FakeClock()
    session = ReplaySession(tl, None, clock=clock)
    msgs = asyncio.run(_collect(session, 0))
    meta = msgs[0]
    assert meta["type"] == "tracking_meta" and meta["available"] and len(meta["roster"]) == 2
    clock.current_ms = 400
    asyncio.run(session.tick())
    clock.current_ms = 2000  # 10x-style jump: thinned
    sent = []
    session.send = lambda m: _append(sent, m)
    asyncio.run(session.tick())
    frames = [m for m in sent if m["type"] == "frames"][0]["frames"]
    assert 0 < len(frames) <= 6 and all(400 < f[0] <= 2000 for f in frames)


def test_tracking_endpoints(silver_store, timeline):
    tl = silver_store.get("2022-01-01_home-fc_away-fc")
    tl.tracking = make_tracking()
    client = TestClient(create_app(silver_store))
    mid = "2022-01-01_home-fc_away-fc"
    meta = client.get(f"/v1/matches/{mid}/tracking").json()
    assert meta["available"] and meta["roster"][0]["name"] == "Home Striker"
    fr = client.get(f"/v1/matches/{mid}/frames", params={"to_ms": 3000}).json()["frames"]
    assert fr and all(2000 < f[0] <= 3000 for f in fr)
    assert client.get(f"/v1/matches/{mid}/frames", params={"to_ms": 90000, "from_ms": 0}).status_code == 422
    assert client.get(f"/v1/matches/{mid}/overview").json()["tracking"]["frames"] == 300
