import math

import pytest

from footballiq.ingest.statsbomb import normalize_match
from footballiq.ml import features as feat
from footballiq.ml import windows as WN
from footballiq.ml import xt as XT


def _shot(**shot):
    return {"id": "s1", "type": {"name": "Shot"}, "period": 1, "location": [108, 40], "play_pattern": {"name": "Regular Play"},
            "shot": {"type": {"name": "Open Play"}, "body_part": {"name": "Right Foot"}, "outcome": {"name": "Goal"}, **shot}}


def test_shot_features_geometry_and_freeze_frame():
    f = feat.shot_features(_shot(freeze_frame=[
        {"location": [119, 40], "teammate": False, "position": {"name": "Goalkeeper"}},
        {"location": [112, 40], "teammate": False, "position": {"name": "Center Back"}},
        {"location": [100, 10], "teammate": False, "position": {"name": "Left Back"}},
    ]))
    assert f["distance_m"] == pytest.approx(10.5)
    assert f["angle_rad"] == pytest.approx(2 * math.atan(3.66 / 10.5), rel=1e-3)
    assert f["def_in_cone"] == 1 and f["gk_in_cone"] == 1 and f["type_open_play"] == 1
    assert f["gk_off_line_m"] == pytest.approx(105 - 119 * 105 / 120)
    assert feat.shot_label(_shot()) == 1
    assert math.isnan(feat.shot_features(_shot())["def_in_cone"])  # no freeze frame -> missing, not zero


def test_pass_features_ignore_outcome():
    ev = {"type": {"name": "Pass"}, "period": 1, "location": [60, 40], "duration": 1.2,
          "pass": {"end_location": [90, 40], "outcome": {"name": "Incomplete"}}}
    done = {**ev, "pass": {"end_location": [90, 40]}}
    assert feat.pass_features(ev) == feat.pass_features(done)
    assert feat.pass_label(ev) == 0 and feat.pass_label(done) == 1
    assert not feat.is_model_pass({**ev, "pass": {"end_location": [90, 40], "outcome": {"name": "Injury Clearance"}}})


def test_xt_grid_rewards_final_third():
    events = [_shot(), _shot(outcome={"name": "Saved"}),
              {"type": {"name": "Pass"}, "period": 1, "location": [100, 40], "pass": {"end_location": [108, 40]}},
              {"type": {"name": "Pass"}, "period": 1, "location": [100, 40],
               "pass": {"end_location": [108, 40], "outcome": {"name": "Incomplete"}}}]
    grid = XT.fit(events)
    assert XT.value(grid, 94.5, 34) > XT.value(grid, 10, 34) == 0
    assert XT.added(grid, events[2])[2] == pytest.approx(0.25)  # start zone: half its moves reach a 0.5 zone
    assert XT.added(grid, events[3]) is None                     # failed moves add nothing


@pytest.fixture
def match_events(raw_match):
    match, events, _ = normalize_match(raw_match, 99)
    return match, events


def _row(rows, team, t):
    return next(r for r in rows if r["team_id"] == team and r["t_ms"] == t)


def test_window_labels_and_no_future_features(match_events):
    match, events = match_events
    rows = WN.examples(match, events, step_s=60)
    p2 = next(p for p in match.periods if p.period == 2).start_match_ms
    home, away = match.home.team_id, match.away.team_id
    assert _row(rows, home, 300_000)["goal_10m"] == 1           # goal at 10:00 is within (5:00, 15:00]
    at_goal = _row(rows, home, 600_000)
    assert at_goal["score_for"] == 1 and at_goal["goal_10m"] == 0  # the goal itself is a feature, not a label
    assert _row(rows, home, 0)["goals_rest"] == 1 and _row(rows, away, 0)["goals_rest"] == 1
    assert _row(rows, away, p2 + 16 * 60_000)["penalty_5m"] == 1
    assert _row(rows, away, p2 + 14 * 60_000)["penalty_5m"] == 0
    assert _row(rows, away, p2 + 19 * 60_000)["score_for"] == 0
    assert _row(rows, home, p2 + 29 * 60_000)["corner_2m"] == 1 and _row(rows, away, p2 + 29 * 60_000)["corner_2m"] == 0
    # censored at the real end of the period: no first-half label can see a second-half event
    assert all(r["goal_10m"] == 0 for r in rows if r["team_id"] == away and r["t_ms"] < p2)
    assert set(WN.FEATURES) <= set(rows[0])


def test_outcome_probabilities():
    w, d, l = WN.outcome_probs(1, 0, 0.2, 0.2)
    assert w + d + l == pytest.approx(1) and w > 0.75
    w, d, l = WN.outcome_probs(0, 0, 0.0, 0.0)
    assert d == pytest.approx(1)
