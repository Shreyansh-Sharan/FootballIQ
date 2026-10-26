"""Shot geometry, difficulty and 360 pressure up to the replay clock, from canonical events.

Model xG (with band) is joined in by the API when available.
"""

from __future__ import annotations

import math
from typing import Any

from footballiq.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M
from footballiq.schema import FreezeFrame, MatchEvent

GOAL_HALF_M = 7.32 / 2
ON_TARGET = {"Goal", "Saved", "Saved To Post"}
BIG_CHANCE_XG = 0.3
BODY_M = 0.5   # half a body width plus 360 position error


def _goal(is_home: bool) -> tuple[float, float]:
    return (PITCH_LENGTH_M if is_home else 0.0), PITCH_WIDTH_M / 2


def _in_triangle(p, a, b, c) -> bool:
    def s(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def _seg_dist(p, a, b) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy or 1e-9)))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def in_cone(p, shot, pa, pb, body_m: float = BODY_M) -> bool:
    """Inside the shooter->posts triangle, or within body_m of its sides (a player is not a point)."""
    return _in_triangle(p, shot, pa, pb) or min(_seg_dist(p, shot, pa), _seg_dist(p, shot, pb)) <= body_m


def zone(depth_m: float, lateral_m: float) -> str:
    """Depth = metres from the goal line, lateral = metres from the centre line of the goal."""
    if depth_m <= 5.5 and lateral_m <= 9.16:
        return "six-yard box"
    if depth_m <= 16.5 and lateral_m <= 20.16:
        return "penalty area"
    return "outside the box"


def difficulty(xg: float | None) -> str | None:
    if xg is None:
        return None
    return "big chance" if xg >= BIG_CHANCE_XG else "good" if xg >= 0.12 else "half chance" if xg >= 0.05 else "low"


def geometry(x: float, y: float, is_home: bool) -> dict[str, float]:
    gx, gy = _goal(is_home)
    depth = abs(gx - x)
    a = math.atan2(gy + GOAL_HALF_M - y, depth) - math.atan2(gy - GOAL_HALF_M - y, depth)
    return {
        "distance_m": math.hypot(depth, y - gy),
        "angle_deg": math.degrees(abs(a)),                                   # goal mouth visible from the shot
        "centrality_deg": math.degrees(math.atan2(abs(y - gy), depth)),      # 0 = straight in front of goal
        "depth_m": depth, "lateral_m": abs(y - gy),
    }


def pressure(ev: MatchEvent, ff: FreezeFrame | None, is_home: bool) -> dict[str, Any]:
    """Defenders between the ball and the posts, nearest defender, keeper position (360 snapshot only)."""
    if ff is None or ev.x_m is None or ev.y_m is None:
        return {"has_360": False, "defenders_in_cone": None, "nearest_defender_m": None, "keeper_off_line_m": None, "keeper_in_cone": None}
    gx, gy = _goal(is_home)
    shot, pa, pb = (ev.x_m, ev.y_m), (gx, gy - GOAL_HALF_M), (gx, gy + GOAL_HALF_M)
    opp = [p for p in ff.players if not p.teammate]
    keeper = next((p for p in opp if p.keeper), None)
    outfield = [p for p in opp if not p.keeper]
    return {
        "has_360": True,
        "defenders_in_cone": sum(in_cone((p.x_m, p.y_m), shot, pa, pb) for p in outfield),
        "nearest_defender_m": round(min(math.hypot(p.x_m - shot[0], p.y_m - shot[1]) for p in outfield), 1) if outfield else None,
        "keeper_off_line_m": round(abs(gx - keeper.x_m), 1) if keeper else None,
        "keeper_in_cone": in_cone((keeper.x_m, keeper.y_m), shot, pa, pb) if keeper else None,
    }


def placement(ev: MatchEvent, is_home: bool) -> str | None:
    """Left / centre / right of the goal from the shooter's view, for shots that end on the goal line."""
    if ev.outcome not in ON_TARGET or ev.end_y_m is None:
        return None
    _, gy = _goal(is_home)
    # y grows downward: facing x = 105, the shooter's left is smaller y
    off = (gy - ev.end_y_m) if is_home else (ev.end_y_m - gy)
    if abs(off) <= GOAL_HALF_M / 3:
        return "centre"
    return "left" if off > 0 else "right"


def shot_rows(events: list[MatchEvent], frames: dict[str, FreezeFrame], home_id: str, model_xg: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = []
    for e in events:
        if e.type != "Shot" or e.is_shootout or e.x_m is None or e.y_m is None:
            continue
        is_home = e.team_id == home_id
        g = geometry(e.x_m, e.y_m, is_home)
        m = (model_xg or {}).get(e.event_id) or {}
        xg = m.get("xg") if m.get("xg") is not None else e.provider_xg
        out.append({
            "event_id": e.event_id, "match_elapsed_ms": e.match_elapsed_ms, "clock_label": e.clock_label, "period": e.period,
            "team_id": e.team_id, "player_id": e.player_id, "player_name": e.player_name,
            "type": e.subtype, "outcome": e.outcome, "is_goal": e.is_goal, "on_target": e.outcome in ON_TARGET,
            "blocked": e.outcome == "Blocked", "under_pressure": e.under_pressure, "play_pattern": e.play_pattern,
            "x_m": e.x_m, "y_m": e.y_m, "end_x_m": e.end_x_m, "end_y_m": e.end_y_m,
            **{k: round(v, 1) for k, v in g.items()}, "zone": zone(g["depth_m"], g["lateral_m"]),
            "placement": placement(e, is_home),
            "xg": m.get("xg"), "xg_lo": m.get("xg_lo"), "xg_hi": m.get("xg_hi"), "xg_statsbomb": e.provider_xg,
            "difficulty": difficulty(xg), **pressure(e, frames.get(e.event_id), is_home),
        })
    return out


def summary(rows: list[dict[str, Any]], team_ids: list[str]) -> dict[str, dict[str, Any]]:
    out = {}
    for t in team_ids:
        r = [s for s in rows if s["team_id"] == t]
        n = len(r)
        xg = [s["xg"] if s["xg"] is not None else s["xg_statsbomb"] for s in r]
        xg = [v for v in xg if v is not None]
        on = sum(s["on_target"] for s in r)
        out[t] = {
            "shots": n, "on_target": on, "blocked": sum(s["blocked"] for s in r), "goals": sum(s["is_goal"] for s in r),
            "accuracy_pct": round(100 * on / n, 1) if n else None,
            "conversion_pct": round(100 * sum(s["is_goal"] for s in r) / n, 1) if n else None,
            "xg": round(sum(xg), 2) if xg else None, "xg_per_shot": round(sum(xg) / len(xg), 3) if xg else None,
            "goals_minus_xg": round(sum(s["is_goal"] for s in r) - sum(xg), 2) if xg else None,
            "avg_distance_m": round(sum(s["distance_m"] for s in r) / n, 1) if n else None,
            "avg_angle_deg": round(sum(s["angle_deg"] for s in r) / n, 1) if n else None,
            "big_chances": sum((v or 0) >= BIG_CHANCE_XG for v in xg),
            "under_pressure_pct": round(100 * sum(s["under_pressure"] for s in r) / n, 1) if n else None,
            "zones": {z: sum(s["zone"] == z for s in r) for z in ("six-yard box", "penalty area", "outside the box")},
        }
    return out
