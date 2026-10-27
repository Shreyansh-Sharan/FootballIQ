"""Goal build-up: the move from the turnover to the shot, positions from tracking, set pieces, rebounds and the clock."""

from __future__ import annotations

import json

import numpy as np

from footballiq.agents.tools import TEAM_TOOL_SPECS, TOOL_SPECS, MatchTools
from footballiq.buildup import goal_buildup
from footballiq.replay.timeline import MatchTimeline
from footballiq.replay.tracking import TrackedPlayer, TrackingTimeline
from test_matchday import LINEUP, MIN, A, H, _Ev, _match

T0 = 10 * MIN


def _events():
    ev = _Ev()
    ev.poss = 1
    # away (attacks towards x = 0) gives the ball away in midfield; home counter: one pass, one carry, goal
    ev.add(T0, "Pass", A, f"{A}_p8", outcome="Incomplete", x_m=60, y_m=34, end_x_m=42, end_y_m=34, play_pattern="Regular Play")
    ev.poss = 2
    ev.add(T0 + 1_000, "Ball Recovery", H, f"{H}_p6", x_m=40, y_m=34, play_pattern="From Counter")
    ev.add(T0 + 3_000, "Pass", H, f"{H}_p6", outcome="Complete", x_m=40, y_m=34, end_x_m=80, end_y_m=34,
           recipient_id=f"{H}_p9", play_pattern="From Counter")
    ev.add(T0 + 5_000, "Pressure", A, f"{A}_p4", x_m=80, y_m=34, play_pattern="From Counter")
    ev.add(T0 + 5_500, "Carry", H, f"{H}_p9", x_m=80, y_m=34, end_x_m=95, end_y_m=34, play_pattern="From Counter")
    ev.add(T0 + 8_000, "Shot", H, f"{H}_p9", subtype="Open Play", outcome="Goal", is_goal=True, x_m=95, y_m=34,
           provider_xg=0.41234, play_pattern="From Counter")
    # 30': away foul in the box, then the penalty
    ev.poss = 3
    ev.add(30 * MIN, "Pass", H, f"{H}_p7", outcome="Complete", x_m=85, y_m=50, end_x_m=95, end_y_m=40, recipient_id=f"{H}_p11")
    ev.add(30 * MIN + 2_000, "Foul Committed", A, f"{A}_p5", x_m=95, y_m=40, card="Yellow Card")
    ev.add(31 * MIN, "Shot", H, f"{H}_p9", subtype="Penalty", outcome="Goal", is_goal=True, x_m=94, y_m=34, provider_xg=0.78)
    return ev.events


def _tracking(events) -> TrackingTimeline:
    """10 Hz around the counter; players in the LINEUP shape (away mirrored); the ball sits on the latest event's spot."""
    t = np.arange(T0 - 3_000, T0 + 10_000, 100, dtype=np.int64)
    located = [(e.match_elapsed_ms, e.x_m, e.y_m) for e in events if e.x_m is not None and e.match_elapsed_ms < T0 + 10_000]
    bx = np.array([next((x for (te, x, _) in reversed(located) if te <= ti), located[0][1]) for ti in t], np.float32)
    by = np.full(len(t), 34, np.float32)
    players, xs, ys = [], [], []
    for side, team in enumerate((H, A)):
        for shirt, code, x, y in LINEUP:
            players.append(TrackedPlayer(len(players), team, ("home", "away")[side], str(shirt), f"{team}_pff-{shirt}", f"Pff {shirt}",
                                         code, True))
            xs.append(x if side == 0 else 105 - x)
            ys.append(y if side == 0 else 68 - y)
    n, k = len(t), len(players)
    frames = {"frame_num": np.arange(n), "t": t, "period": np.ones(n, np.int8), "ball_x": bx, "ball_y": by,
              "ball_z": np.zeros(n, np.float32), "ball_observed": np.ones(n, bool)}
    positions = {"frame_num": np.repeat(np.arange(n), k), "player_idx": np.tile(np.arange(k), n),
                 "x": np.tile(np.array(xs, np.float32), n), "y": np.tile(np.array(ys, np.float32), n),
                 "observed": np.ones(n * k, bool)}
    return TrackingTimeline.from_columns("m-test", "test", frames, positions, players)


def _tl() -> MatchTimeline:
    events = _events()
    return MatchTimeline(_match(), events, tracking=_tracking(events))


def test_counter_goal_move_turnover_and_positions():
    d = goal_buildup(_tl(), T0 + 20_000)
    g, s, mv = d["goal"], d["start"], d["move"]
    assert g["scorer"] == f"{H}_p9" and g["conceding_team"] == "Away FC" and g["benchmark_xg"] == 0.412
    assert s["how"] == "won the ball in open play" and s["lost_by"] == f"{A}_p8" and s["lost_with"] == "Pass, Incomplete"
    assert s["third_for_conceding_team"] == "middle" and s["lost_at_m_from_goal"] == 45.0
    assert mv == {"seconds": 7.0, "passes": 1, "players_involved": 2, "metres_towards_goal": 55, "actions_under_pressure": 0,
                  "actions": 4}
    assert d["defending_actions"]["counts"] == {"Pressure": 1}
    # tracking at the turnover (ball 45 m from goal): the away back four are goal-side, their last line 30 m out
    lost = d["when_the_ball_was_lost"]
    assert lost["source"] == "tracking" and lost["conceding_outfield_counted"] == 10
    assert lost["conceding_outfield_goal_side_of_ball"] == 4 and lost["conceding_last_line_m_from_goal"] == 30.0
    # at the last pass the scorer is found by shirt (tracking ids differ from event ids) and his nearest marker is named
    lp = d["at_the_last_pass"]
    assert lp["passer"] == f"{H}_p6" and lp["scorer_m_from_goal"] == 45.0 and lp["nearest_defender_to_scorer"]["player"] == "Away Player 6"
    assert d["at_the_shot"]["shot_m_from_goal"] == 10.0 and "attackers_in_box" in d["at_the_shot"]
    assert [x["clock"] for x in d["goals_so_far"]] == ["00:00"]


def test_penalty_goal_is_traced_to_the_foul():
    d = goal_buildup(_tl(), 32 * MIN)
    assert d["goal"]["kind"] == "penalty" and len(d["goals_so_far"]) == 2
    assert d["awarded"] == {"how": "penalty", "foul_clock": "00:00", "foul_by": f"{A}_p5", "foul_m_from_goal": 11.7,
                            "card": "Yellow Card"}
    assert "at_the_shot" not in d and d["move"]["passes"] == 1


def test_clock_bound_event_choice_and_tool_wiring():
    tl = _tl()
    assert goal_buildup(tl, T0 + 7_999) == {"unavailable": "no goal has been scored yet at this point of the match"}
    assert goal_buildup(tl, 32 * MIN, "e3")["error"].startswith("event_id is not a goal or shot")      # a pass, not a shot
    first = goal_buildup(tl, 32 * MIN, "e6")
    assert first["goal"]["kind"] == "open play" and first["start"]["lost_by"] == f"{A}_p8"
    out = json.loads(MatchTools(tl, T0 + 20_000).run("get_goal_buildup", {}))
    assert out["goal"]["minute"] == "1'" and len(json.dumps(out)) < 12_000
    # team-only: the Foundry agents' tool list is unchanged
    assert {t["function"]["name"] for t in TEAM_TOOL_SPECS} == {"get_goal_buildup"}
    assert "get_goal_buildup" not in {t["function"]["name"] for t in TOOL_SPECS}


def test_real_final_counter_goal(final_timeline):
    """The 36' goal of the 2022 final: lost with a misplaced pass, then a 75 m, 5-pass counter with no pressure."""
    tl = final_timeline
    shot = next(e for e in tl.events if e.is_goal and e.clock_label == "35:22")
    d = goal_buildup(tl, shot.match_elapsed_ms + 15_000)
    assert d["goal"]["event_id"] == shot.event_id and d["goal"]["play_pattern"] == "From Counter"
    assert d["start"]["how"] == "won the ball in open play" and d["start"]["lost_with"] == "Pass, Incomplete"
    assert d["move"] == {"seconds": 9.8, "passes": 5, "players_involved": 5, "metres_towards_goal": 75,
                         "actions_under_pressure": 0, "actions": 6}
    assert d["at_the_shot"]["keeper_off_line_m"] == 4.8 and d["at_the_shot"]["defenders_in_shot_cone"] == 0
    assert len(d["goals_so_far"]) == 2 and len(json.dumps(d)) < 12_000
