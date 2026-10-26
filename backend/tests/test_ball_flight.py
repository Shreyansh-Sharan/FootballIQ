import numpy as np

from footballiq.ball_flight import flight
from footballiq.replay.tracking import TrackingTimeline
from footballiq.schema import MatchEvent


def _tracking(xs, ys, zs, t0=10_000, dt=33):
    n = len(xs)
    frames = {"frame_num": np.arange(n), "t": t0 + dt * np.arange(n), "period": np.ones(n), "ball_x": np.asarray(xs, float),
              "ball_y": np.asarray(ys, float), "ball_z": np.asarray(zs, float), "ball_observed": np.ones(n, bool)}
    pos = {"frame_num": np.array([], int), "player_idx": np.array([], int), "x": np.array([]), "y": np.array([]), "observed": np.array([], bool)}
    return TrackingTimeline.from_columns("m", "pff_tracking", frames, pos, [])


def _shot(x, y, team="h", t=10_000):
    return MatchEvent(event_id="s", match_id="m", provider="statsbomb", source_sequence=1, period=1, period_elapsed_ms=t,
                      match_elapsed_ms=t, clock_label="00:10", team_id=team, team_name=team, type="Shot", outcome="Goal",
                      is_goal=True, x_m=x, y_m=y)


def test_curling_shot_bends_left_for_home_and_away():
    fwd = np.linspace(80, 105, 26)                       # 25 m towards x = 105 at ~30 m/s
    lat = 0.012 * (fwd - 80) ** 2                        # swings to the shooter's left (smaller y for home)
    z = np.linspace(0.2, 2.0, 26)
    home = flight(_tracking(fwd, 40 - lat, z), _shot(80, 40), True, 60_000)
    assert home["available"] and home["bend"] == "left" and home["curve_deg"] > 20
    assert abs(home["swerve_m"] - 0.012 * 25 ** 2 / 4) < 0.05
    assert 80 < home["speed_kmh"] < 120 and home["reached_goal_line"] and home["height_at_line_m"] == 2.0
    away = flight(_tracking(105 - fwd, 28 + lat, z), _shot(25, 28, "a"), False, 60_000)   # mirrored: same bend for the shooter
    assert away["bend"] == "left" and abs(away["curve_deg"] - home["curve_deg"]) < 0.5


def test_straight_shot_and_no_spoilers():
    fwd = np.linspace(85, 105, 21)
    straight = flight(_tracking(fwd, np.full(21, 34.0), np.zeros(21)), _shot(85, 34), True, 60_000)
    assert straight["bend"] == "straight" and abs(straight["curve_deg"]) < 1
    cut = flight(_tracking(fwd, np.full(21, 34.0), np.zeros(21)), _shot(85, 34), True, 10_100)   # clock 0.1 s after the strike
    assert not cut["available"]


def test_events_only_match_has_no_flight():
    assert flight(None, _shot(90, 34), True, 60_000)["available"] is False


def test_penalty_ball_resting_on_the_spot_starts_at_the_kick():
    rest = [94.5] * 40                                       # 1.3 s on the spot, event time stamped ~1.3 s late
    fwd = list(np.linspace(94.5, 105, 12))
    xs = rest + fwd
    ys = [34.0] * 40 + list(34 - 0.02 * (np.asarray(fwd) - 94.5) ** 2)
    f = flight(_tracking(xs, ys, np.zeros(len(xs))), _shot(94.5, 34, t=10_000 + 33 * 40 + 1300), True, 60_000)
    assert f["available"] and f["samples"] >= 10 and f["distance_m"] > 10 and f["bend"] == "left"


def test_straight_line_reconstruction_gives_speed_but_no_curve():
    fwd = np.linspace(80, 105, 26)
    z = 2.5 - 0.01 * (fwd - 92) ** 2
    tr = _tracking(fwd, np.full(26, 30.0) + 0.1 * (fwd - 80), z)
    tr.ball_observed[:] = False                                # provider estimate, never seen
    f = flight(tr, _shot(80, 30), True, 60_000)
    assert f["available"] and not f["curve_measurable"] and f["curve_deg"] is None and f["estimated"]
    assert 80 < f["speed_kmh"] < 120 and f["peak_height_m"] > 2
