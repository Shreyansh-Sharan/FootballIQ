import json

import pandas as pd

from footballiq.ingest import skillcorner as SC

META = {
    "id": 1, "date_time": "2025-01-01T10:00:00Z", "pitch_length": 105, "pitch_width": 68,
    "home_team": {"id": 10, "name": "Home FC"}, "away_team": {"id": 20, "name": "Away FC"},
    "home_team_score": 1, "away_team_score": 0, "home_team_side": ["left_to_right", "right_to_left"],
    "match_periods": [{"period": 1, "start_frame": 100, "end_frame": 27100}, {"period": 2, "start_frame": 30000, "end_frame": 57000}],
    "competition_edition": {"name": "Test League"}, "competition_round": {"name": "Round 1"}, "stadium": {"name": "Ground"},
    "players": [
        {"id": 1, "team_id": 10, "short_name": "H One", "number": 9, "start_time": "00:00:00", "playing_time": {"total": {"start_frame": 100, "end_frame": 40000}}},
        {"id": 2, "team_id": 10, "short_name": "H Two", "number": 10, "start_time": "00:00:00", "playing_time": {"total": {"start_frame": 100, "end_frame": 40000}}},
        {"id": 3, "team_id": 10, "short_name": "H Sub A", "number": 18, "start_time": "01:00:00", "playing_time": {"total": {"start_frame": 40000, "end_frame": 57000}}},
        {"id": 4, "team_id": 10, "short_name": "H Sub B", "number": 19, "start_time": "01:00:00", "playing_time": {"total": {"start_frame": 40000, "end_frame": 57000}}},
        {"id": 5, "team_id": 20, "short_name": "A One", "number": 1, "start_time": "00:00:00", "playing_time": {"total": {"start_frame": 100, "end_frame": 57000}}},
    ],
}


def test_events_goal_and_substitutions():
    ev = pd.DataFrame([
        {"event_id": "8_1", "index": 1, "event_type": "player_possession", "end_type": "shot", "period": 1, "frame_end": 6100,
         "team_id": 10, "team_shortname": "Home", "player_id": 1, "player_name": "H One", "x_end": 40.0, "y_end": 5.0,
         "pass_outcome": None, "lead_to_goal": True},
        {"event_id": "8_2", "index": 2, "event_type": "player_possession", "end_type": "pass", "period": 2, "frame_end": 31000,
         "team_id": 20, "team_shortname": "Away", "player_id": 5, "player_name": "A One", "x_end": 30.0, "y_end": -4.0,
         "pass_outcome": "unsuccessful", "lead_to_goal": False},
        {"event_id": "9_1", "index": 3, "event_type": "off_ball_run", "end_type": None, "period": 1, "frame_end": 200,
         "team_id": 10, "team_shortname": "Home", "player_id": 2, "player_name": "H Two", "x_end": 0.0, "y_end": 0.0,
         "pass_outcome": None, "lead_to_goal": False},
    ])
    match, events = SC.normalize(META, ev)
    shot = next(e for e in events if e.type == "Shot")
    assert shot.is_goal and shot.clock_label.startswith("10:") and (shot.x_m, shot.y_m) == (92.5, 29.0)
    pas = next(e for e in events if e.type == "Pass")       # away attacks right-to-left in the canonical frame
    assert pas.outcome == "Incomplete" and (pas.x_m, pas.y_m) == (22.5, 30.0)
    subs = [(e.player_name, e.recipient_name) for e in events if e.type == "Substitution"]
    assert sorted(subs) == [("H One", "H Sub A"), ("H Two", "H Sub B")]   # each player off is used once
    assert match.result["home_score"] == 1 and len(match.periods) == 2


def test_tracking_flip_and_flags():
    match, _ = SC.normalize(META, pd.DataFrame(columns=["event_type"]))
    lines = [json.dumps({"frame": 200, "period": 1, "ball_data": {"x": 1.0, "y": 2.0, "z": 0.1, "is_detected": True},
                         "player_data": [{"player_id": 1, "x": -50.0, "y": 10.0, "is_detected": False}]}),
             json.dumps({"frame": 31000, "period": 2, "ball_data": {"x": None, "y": None, "z": None, "is_detected": None},
                         "player_data": [{"player_id": 1, "x": -50.0, "y": 10.0, "is_detected": True}]})]
    fr, po = SC.tracking_columns(lines, META, match)
    assert (po["x_m"][0], po["y_m"][0], po["is_observed"][0], po["is_extrapolated"][0]) == (2.5, 24.0, False, True)
    assert (po["x_m"][1], po["y_m"][1], po["is_observed"][1]) == (102.5, 44.0, True)   # second half: home attacks right-to-left
    assert fr["ball_is_observed"][1] is None and fr["ball_x_m"][1] is None             # missing ball stays unknown
    assert fr["coverage_score"][0] == 0.0 and fr["coverage_score"][1] == 1.0
