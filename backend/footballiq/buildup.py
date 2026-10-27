"""How a goal (or any shot) was made, up to the replay clock: the move from the turnover or restart to the shot, the
pressure on it, and where the conceding team stood when the ball was lost, at the last pass and at the shot.

Events give the move. Positions come from tracking (every player) or, without tracking, from the event's 360 snapshot
(only the players in the camera view). Tracking is matched to an event by the frame, within a couple of seconds, whose
ball is nearest the event's location (the two feeds are not perfectly in sync). Distances are metres from the goal that
was scored in, so they read the same for both teams.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np

from footballiq.matchday.shape import tracking_to_match
from footballiq.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M
from footballiq.replay.timeline import MatchTimeline
from footballiq.schema import FreezeFrame, MatchEvent
from footballiq.shots import pressure as shot_pressure

RESTARTS = {"Throw-in", "Corner", "Free Kick", "Goal Kick", "Kick Off"}
# the conceding team had or touched the ball: the scoring move starts after the latest of these
ON_BALL = {"Pass", "Ball Receipt*", "Carry", "Dribble", "Shot", "Ball Recovery", "Dispossessed", "Miscontrol", "Clearance",
           "Interception", "Goal Keeper"}
MOVE_ACTIONS = {"Pass", "Carry", "Dribble", "Shot", "Ball Recovery", "Interception", "Duel", "50/50"}
SET_PIECE_SHOTS = {"Penalty", "Free Kick"}
SECOND_BALL = {"Goal Keeper", "Clearance", "Interception"}   # a goal straight after one of these is a rebound
SECOND_BALL_MS = 6_000
WON = "won the ball in open play"
LOOKBACK_MS = 120_000
FOUL_LOOKBACK_MS = 240_000          # a penalty can follow its foul by minutes (review)
MAX_ACTIONS, MAX_DEFENDING = 14, 8
MIN_CARRY_M = 3.0
SNAP_BEFORE_MS, SNAP_AFTER_MS, SNAP_MAX_M = 2_000, 800, 6.0
BOX_DEPTH_M, BOX_HALF_WIDTH_M = 16.5, 20.16


def _depth(x: float, attack_home: bool) -> float:
    """Metres from the goal line being attacked (home attacks x = 105 in every period)."""
    return PITCH_LENGTH_M - x if attack_home else x


def _to_goal(x: float | None, y: float | None, attack_home: bool) -> float | None:
    if x is None or y is None:
        return None
    return round(math.hypot(_depth(x, attack_home), y - PITCH_WIDTH_M / 2), 1)


def _third(depth: float) -> str:
    """Third of the pitch seen from the conceding team."""
    return "defensive" if depth <= PITCH_LENGTH_M / 3 else "middle" if depth <= 2 * PITCH_LENGTH_M / 3 else "attacking"


def _in_box(x: float, y: float, attack_home: bool) -> bool:
    return _depth(x, attack_home) <= BOX_DEPTH_M and abs(y - PITCH_WIDTH_M / 2) <= BOX_HALF_WIDTH_M


def _action(e: MatchEvent) -> str:
    return e.type + (f" ({e.subtype})" if e.subtype else "")


def move_start(events: list[MatchEvent], i_end: int, attack: str) -> tuple[int, int | None]:
    """(first action of the move by ``attack``, the conceding team's last action before it or None).

    Walks back from ``i_end`` to the conceding team's latest on-ball action, or to the attacking team's restart (then the
    conceding action is the one that gave the restart away, if it is recent)."""
    end = events[i_end]
    first, i = i_end, i_end - 1
    while i >= 0:
        e = events[i]
        if e.period != end.period or end.match_elapsed_ms - e.match_elapsed_ms > LOOKBACK_MS or e.type == "Half Start":
            return first, None
        if e.team_id == attack:
            if e.type in MOVE_ACTIONS or e.type == "Ball Receipt*":
                first = i
            if e.type == "Pass" and e.subtype in RESTARTS:
                return i, _gave_away(events, i, attack)
        elif e.team_id and e.type in ON_BALL:
            return first, i
        i -= 1
    return first, None


def _gave_away(events: list[MatchEvent], i_restart: int, attack: str) -> int | None:
    t = events[i_restart].match_elapsed_ms
    for i in range(i_restart - 1, -1, -1):
        e = events[i]
        if t - e.match_elapsed_ms > 30_000 or e.period != events[i_restart].period:
            return None
        if e.team_id and e.team_id != attack and (e.type in ON_BALL or e.type in ("Block", "Foul Committed")):
            return i
    return None


def _snap(tl: MatchTimeline, ev: MatchEvent, at_ms: int, ids: dict[str, str],
          frames: dict[str, FreezeFrame]) -> tuple[str, list[dict[str, Any]]] | None:
    """Every player's position at ``ev``: tracking frame nearest the event's ball location, else its 360 snapshot."""
    if ev.x_m is None or ev.y_m is None:
        return None
    tr = tl.tracking
    if tr is not None and tr.n_frames:
        lo = tr.index_at(ev.match_elapsed_ms - SNAP_BEFORE_MS)
        hi = tr.index_at(min(ev.match_elapsed_ms + SNAP_AFTER_MS, at_ms))        # never a frame after the clock
        if hi > lo:
            d = np.hypot(tr.ball[lo:hi, 0] - ev.x_m, tr.ball[lo:hi, 1] - ev.y_m)
            if not np.all(np.isnan(d)) and np.nanmin(d) <= SNAP_MAX_M:
                i = lo + int(np.nanargmin(d))
                s, e = tr.offsets[i], tr.offsets[i + 1]
                out = []
                for p, (x, y) in zip(tr.p_idx[s:e], tr.p_xy[s:e]):
                    if np.isnan(x):
                        continue
                    tp = tr.players[int(p)]
                    out.append({"team_id": tp.team_id, "keeper": (tp.position_group or "").upper() == "GK", "x": float(x),
                                "y": float(y), "pid": ids.get(tp.player_id or "", tp.player_id)})
                if out:
                    return "tracking", out
    ff = frames.get(ev.event_id)
    if ff is not None and ff.players:
        return "360 snapshot (players in the camera view only)", [
            {"team_id": p.team_id, "keeper": p.keeper, "x": p.x_m, "y": p.y_m, "pid": None} for p in ff.players]
    return None


def _nearest(players: list[dict[str, Any]], x: float, y: float, names: dict[str, str]) -> dict[str, Any] | None:
    if not players:
        return None
    p = min(players, key=lambda q: math.hypot(q["x"] - x, q["y"] - y))
    out: dict[str, Any] = {"m": round(math.hypot(p["x"] - x, p["y"] - y), 1)}
    if p["pid"] in names:                 # only line-up players: the id lets the privacy layer swap in the fictional name
        out |= {"player": names[p["pid"]], "player_id": p["pid"]}
    return out


def _at_turnover(snap, ev: MatchEvent, attack: str, attack_home: bool, names: dict[str, str]) -> dict[str, Any] | None:
    if snap is None:
        return None
    source, pos = snap
    ball = _depth(ev.x_m, attack_home)
    defs = [p for p in pos if p["team_id"] != attack and not p["keeper"]]
    atts = [p for p in pos if p["team_id"] == attack and not p["keeper"]]
    return {"source": source,
            "conceding_outfield_goal_side_of_ball": sum(_depth(p["x"], attack_home) < ball for p in defs),
            "conceding_outfield_counted": len(defs),
            "attackers_ahead_of_ball": sum(_depth(p["x"], attack_home) < ball - 1 for p in atts),
            "conceding_last_line_m_from_goal": round(min(_depth(p["x"], attack_home) for p in defs), 1) if defs else None,
            "nearest_conceding_player_to_ball": _nearest(defs, ev.x_m, ev.y_m, names)}


def _at_shot(snap, ev: MatchEvent, ff: FreezeFrame | None, attack: str, attack_home: bool, names: dict[str, str]) -> dict[str, Any]:
    cone = shot_pressure(ev, ff, attack_home)
    out: dict[str, Any] = {"shot_m_from_goal": _to_goal(ev.x_m, ev.y_m, attack_home),
                           "defenders_in_shot_cone": cone["defenders_in_cone"], "keeper_off_line_m": cone["keeper_off_line_m"]}
    if snap is not None:
        source, pos = snap
        defs = [p for p in pos if p["team_id"] != attack and not p["keeper"]]
        out |= {"source": source,
                "attackers_in_box": sum(_in_box(p["x"], p["y"], attack_home) for p in pos if p["team_id"] == attack),
                "conceding_outfield_in_box": sum(_in_box(p["x"], p["y"], attack_home) for p in defs),
                "nearest_defender_to_shooter": _nearest(defs, ev.x_m, ev.y_m, names)}
    return out


def _start_and_move(events: list[MatchEvent], first: int, i_lost: int | None, i_end: int, attack: str,
                    attack_home: bool) -> tuple[dict[str, Any], dict[str, Any], list[MatchEvent]]:
    """How the move started (and who lost the ball), its tempo and pressure, and the attacking actions in it."""
    acts = [e for e in events[first:i_end + 1] if e.team_id == attack and e.type in MOVE_ACTIONS
            and not (e.type == "Carry" and e.end_x_m is not None and e.x_m is not None
                     and math.hypot(e.end_x_m - e.x_m, (e.end_y_m or 0) - (e.y_m or 0)) < MIN_CARRY_M)]
    s, end = events[first], events[i_end]
    lost = events[i_lost] if i_lost is not None else None
    restart = s.subtype if s.type == "Pass" and s.subtype in RESTARTS else None
    d0 = _depth(s.x_m, attack_home) if s.x_m is not None else None
    d1 = _depth(end.x_m, attack_home) if end.x_m is not None else None
    start = {"how": restart.lower() if restart else WON if lost else "long spell of possession",
             "clock": s.clock_label, "by": s.player_name, "first_action": _action(s),
             "m_from_goal": _to_goal(s.x_m, s.y_m, attack_home),
             "third_for_conceding_team": _third(d0) if d0 is not None else None}
    if lost is not None:
        start |= {"lost_by": lost.player_name, "lost_with": _action(lost) + (f", {lost.outcome}" if lost.outcome else ""),
                  "lost_clock": lost.clock_label, "lost_at_m_from_goal": _to_goal(lost.x_m, lost.y_m, attack_home),
                  "lost_under_pressure": lost.under_pressure}
    move = {"seconds": round((end.match_elapsed_ms - s.match_elapsed_ms) / 1000, 1),
            "passes": sum(e.type == "Pass" for e in acts),
            "players_involved": len({e.player_id for e in acts if e.player_id}),
            "metres_towards_goal": round(d0 - d1) if d0 is not None and d1 is not None else None,
            "actions_under_pressure": sum(e.under_pressure for e in acts), "actions": len(acts)}
    return start, move, acts


def _last_pass(events: list[MatchEvent], first: int, i_shot: int, attack: str, shooter: str | None) -> int | None:
    for i in range(i_shot - 1, first - 1, -1):
        e = events[i]
        if e.team_id == attack and e.type == "Pass" and shooter and e.recipient_id == shooter:
            return i
    return None


def goal_buildup(tl: MatchTimeline, at_ms: int, event_id: str | None = None) -> dict[str, Any]:
    """The move behind the latest goal before ``at_ms`` (or behind ``event_id``: any goal or shot up to the clock)."""
    events = tl.events_between(-1, at_ms)
    goals = [i for i, e in enumerate(events) if (e.is_goal or e.is_own_goal) and not e.is_shootout]
    listed = [{"event_id": events[i].event_id, "clock": events[i].clock_label, "team_id": events[i].team_id,
               "scorer": events[i].player_name, "own_goal": events[i].is_own_goal} for i in goals]
    if event_id:
        hit = [i for i, e in enumerate(events) if e.event_id == event_id and (e.type == "Shot" or e.is_goal or e.is_own_goal)]
        if not hit:
            return {"error": "event_id is not a goal or shot up to the replay clock", "goals_so_far": listed}
        i_shot = hit[0]
    elif goals:
        i_shot = goals[-1]
    else:
        return {"unavailable": "no goal has been scored yet at this point of the match"}

    m = tl.match
    shot = events[i_shot]
    attack = shot.team_id or ""
    attack_home = attack == m.home.team_id
    conceding = m.away if attack_home else m.home
    names = {p.player_id: p.name for p in m.players} | {e.player_id: e.player_name for e in events if e.player_id and e.player_name}
    ids = tracking_to_match(tl)
    frames = {f.event_id: f for f in tl.frames}

    # a penalty or direct free kick: the move is the one that drew the foul
    i_end, awarded = i_shot, None
    if shot.subtype in SET_PIECE_SHOTS:
        for i in range(i_shot - 1, -1, -1):
            e = events[i]
            if shot.match_elapsed_ms - e.match_elapsed_ms > FOUL_LOOKBACK_MS:
                break
            if e.type == "Foul Committed" and e.team_id == conceding.team_id:
                i_end = i
                awarded = {"how": shot.subtype.lower(), "foul_clock": e.clock_label, "foul_by": e.player_name,
                           "foul_m_from_goal": _to_goal(e.x_m, e.y_m, attack_home), "card": e.card}
                break
    first, i_lost = move_start(events, i_end, attack)
    start, move, acts = _start_and_move(events, first, i_lost, i_end, attack, attack_home)
    defending = [e for e in events[first:i_end + 1] if e.team_id == conceding.team_id]
    lost = events[i_lost] if i_lost is not None else None

    out: dict[str, Any] = {
        "goal": {"event_id": shot.event_id, "clock": shot.clock_label, "scorer": shot.player_name,
                 "scoring_team": m.home.name if attack_home else m.away.name, "conceding_team": conceding.name,
                 "kind": "own goal" if shot.is_own_goal else (shot.subtype or "open play").lower() if shot.is_goal else "shot",
                 "outcome": shot.outcome, "play_pattern": shot.play_pattern,
                 "benchmark_xg": None if shot.provider_xg is None else round(shot.provider_xg, 3)},
        "start": start,
        "move": move,
        "actions": [{"clock": e.clock_label, "player": e.player_name, "action": _action(e),
                     "from_m": _to_goal(e.x_m, e.y_m, attack_home), "to_m": _to_goal(e.end_x_m, e.end_y_m, attack_home),
                     "under_pressure": e.under_pressure,
                     **({"outcome": e.outcome} if e.outcome and e.outcome != "Complete" else {})} for e in acts[-MAX_ACTIONS:]],
        "defending_actions": {"counts": dict(Counter(_action(e) + (f", {e.outcome}" if e.type == "Duel" and e.outcome else "")
                                                     for e in defending)),
                              "list": [{"clock": e.clock_label, "player": e.player_name, "action": _action(e),
                                        **({"outcome": e.outcome} if e.outcome else {})} for e in defending[-MAX_DEFENDING:]]},
    }
    if awarded:
        out["awarded"] = awarded
    # a rebound or second ball: the move that forced the save, block or clearance
    if lost is not None and lost.type in SECOND_BALL and events[i_end].match_elapsed_ms - lost.match_elapsed_ms <= SECOND_BALL_MS:
        j = next((k for k in range(i_lost - 1, -1, -1) if events[k].team_id == attack and events[k].type in MOVE_ACTIONS), None)
        if j is not None and lost.match_elapsed_ms - events[j].match_elapsed_ms <= SECOND_BALL_MS:
            f2, l2 = move_start(events, j, attack)
            s2, m2, _ = _start_and_move(events, f2, l2, j, attack, attack_home)
            out["before_the_second_ball"] = {"last_action": f"{_action(events[j])} by {events[j].player_name} at "
                                                            f"{events[j].clock_label}", "start": s2, "move": m2}
    # positions where the move began: the turnover in open play, otherwise the restart
    turn_ev = lost if lost is not None and lost.x_m is not None and start["how"] == WON else events[first]
    key = "when_the_ball_was_lost" if turn_ev is lost else "at_the_start_of_the_move"
    out[key] = _at_turnover(_snap(tl, turn_ev, at_ms, ids, frames), turn_ev, attack, attack_home, names)
    if shot.subtype not in SET_PIECE_SHOTS and shot.x_m is not None:
        i_pass = _last_pass(events, first, i_shot, attack, shot.player_id)
        if i_pass is not None:
            p = events[i_pass]
            snap = _snap(tl, p, at_ms, ids, frames)
            scorer = next((q for q in snap[1] if q["pid"] == shot.player_id), None) if snap else None
            row: dict[str, Any] = {"clock": p.clock_label, "passer": p.player_name}
            if scorer is not None:
                defs = [q for q in snap[1] if q["team_id"] != attack and not q["keeper"]]
                row |= {"source": snap[0], "scorer_m_from_goal": _to_goal(scorer["x"], scorer["y"], attack_home),
                        "nearest_defender_to_scorer": _nearest(defs, scorer["x"], scorer["y"], names),
                        "conceding_last_line_m_from_goal": round(min(_depth(q["x"], attack_home) for q in defs), 1) if defs else None}
            out["at_the_last_pass"] = row
        out["at_the_shot"] = _at_shot(_snap(tl, shot, at_ms, ids, frames), shot, frames.get(shot.event_id), attack, attack_home, names)
    out["goals_so_far"] = listed
    out["how_to_read"] = ("Distances are metres from the goal that was scored in. 'Goal-side of the ball' = between the ball "
                          "and that goal. Positions come from tracking (every player; some positions are estimates) or a 360 "
                          "snapshot (players in view only). Nothing after the replay clock exists.")
    return out
