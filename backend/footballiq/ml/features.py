"""Per-action features for the xG and xPass models, shared by the Fabric notebooks and tests.

Metres on a 105 x 68 attacking frame; only information known when the ball is struck.
"""

from __future__ import annotations

import math
from typing import Any

L, W = 105.0, 68.0
GOAL_X, GOAL_Y, HALF_GOAL = L, W / 2, 7.32 / 2
BOX_X, BOX_Y0, BOX_Y1 = L - 16.5, W / 2 - 20.16, W / 2 + 20.16
NAN = float("nan")

FEATURE_VERSION = "1"


def to_m(loc: list[float] | None) -> tuple[float, float] | None:
    if not loc or len(loc) < 2:
        return None
    return loc[0] * L / 120.0, loc[1] * W / 80.0


def _name(obj: Any) -> str | None:
    return obj.get("name") if isinstance(obj, dict) else None


def goal_angle(x: float, y: float) -> float:
    """Angle (radians) subtended by the goal mouth from (x, y)."""
    a = math.atan2(GOAL_Y + HALF_GOAL - y, GOAL_X - x)
    b = math.atan2(GOAL_Y - HALF_GOAL - y, GOAL_X - x)
    return abs(a - b)


def _in_triangle(p, a, b, c) -> bool:
    def s(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def _onehot(prefix: str, value: str | None, options: tuple[str, ...]) -> dict[str, float]:
    return {f"{prefix}_{o.lower().replace(' ', '_').replace('-', '_')}": float(value == o) for o in options}


PLAY_PATTERNS = ("Regular Play", "From Counter", "From Corner", "From Free Kick", "From Throw In", "From Goal Kick", "From Keeper", "From Kick Off")

# --------------------------------------------------------------------------- shots

SHOT_TYPES = ("Open Play", "Free Kick", "Penalty", "Corner")
SHOT_TECHNIQUES = ("Normal", "Volley", "Half Volley", "Lob", "Overhead Kick", "Diving Header", "Backheel")


def shot_features(ev: dict[str, Any]) -> dict[str, float]:
    shot = ev.get("shot") or {}
    xy = to_m(ev.get("location")) or (NAN, NAN)
    x, y = xy
    dist = math.hypot(GOAL_X - x, GOAL_Y - y)
    body = _name(shot.get("body_part"))
    f: dict[str, float] = {
        "x": x, "y_abs": abs(y - GOAL_Y), "distance_m": dist, "angle_rad": goal_angle(x, y),
        "is_header": float(body == "Head"), "is_other_body": float(body not in ("Head", "Right Foot", "Left Foot")),
        "first_time": float(bool(shot.get("first_time"))), "one_on_one": float(bool(shot.get("one_on_one"))),
        "open_goal": float(bool(shot.get("open_goal"))), "follows_dribble": float(bool(shot.get("follows_dribble"))),
        "aerial_won": float(bool(shot.get("aerial_won"))), "under_pressure": float(bool(ev.get("under_pressure"))),
    }
    f.update(_onehot("type", _name(shot.get("type")), SHOT_TYPES))
    f.update(_onehot("tech", _name(shot.get("technique")), SHOT_TECHNIQUES))
    f.update(_onehot("pp", _name(ev.get("play_pattern")), PLAY_PATTERNS))

    ff = shot.get("freeze_frame")
    f["has_freeze_frame"] = float(bool(ff))
    keys = ("def_in_cone", "att_in_cone", "def_within_3m", "nearest_def_m", "gk_dist_goal_m", "gk_dist_shooter_m", "gk_in_cone", "gk_off_line_m")
    if not ff:
        f.update({k: NAN for k in keys})
        return f
    post_a, post_b = (GOAL_X, GOAL_Y - HALF_GOAL), (GOAL_X, GOAL_Y + HALF_GOAL)
    defs, atts, gk = [], [], None
    for p in ff:
        loc = to_m(p.get("location"))
        if loc is None:
            continue
        if not p.get("teammate") and _name(p.get("position")) == "Goalkeeper":
            gk = loc
        elif p.get("teammate"):
            atts.append(loc)
        else:
            defs.append(loc)
    tri = lambda q: _in_triangle(q, (x, y), post_a, post_b)  # noqa: E731
    f["def_in_cone"] = float(sum(tri(d) for d in defs))
    f["att_in_cone"] = float(sum(tri(a) for a in atts))
    f["def_within_3m"] = float(sum(math.hypot(d[0] - x, d[1] - y) < 3 for d in defs))
    f["nearest_def_m"] = min((math.hypot(d[0] - x, d[1] - y) for d in defs), default=NAN)
    if gk:
        f["gk_dist_goal_m"] = math.hypot(GOAL_X - gk[0], GOAL_Y - gk[1])
        f["gk_dist_shooter_m"] = math.hypot(gk[0] - x, gk[1] - y)
        f["gk_in_cone"] = float(tri(gk))
        f["gk_off_line_m"] = GOAL_X - gk[0]
    else:
        f.update({k: NAN for k in ("gk_dist_goal_m", "gk_dist_shooter_m", "gk_in_cone", "gk_off_line_m")})
    return f


def is_model_shot(ev: dict[str, Any]) -> bool:
    """xG model scope: shots, penalties included, in periods 1-4."""
    return _name(ev.get("type")) == "Shot" and ev.get("period", 1) <= 4 and ev.get("location") is not None


def shot_label(ev: dict[str, Any]) -> int:
    return int(_name((ev.get("shot") or {}).get("outcome")) == "Goal")

# --------------------------------------------------------------------------- passes

PASS_TYPES = ("Corner", "Free Kick", "Throw-in", "Goal Kick", "Kick Off", "Recovery", "Interception")
PASS_HEIGHTS = ("Ground Pass", "Low Pass", "High Pass")
PASS_TECHNIQUES = ("Through Ball", "Inswinging", "Outswinging", "Straight")
FAILED = ("Incomplete", "Out", "Pass Offside", "Unknown")


def pass_features(ev: dict[str, Any]) -> dict[str, float]:
    p = ev.get("pass") or {}
    x, y = to_m(ev.get("location")) or (NAN, NAN)
    ex, ey = to_m(p.get("end_location")) or (NAN, NAN)
    dx, dy = ex - x, ey - y
    length = math.hypot(dx, dy)
    d0, d1 = math.hypot(GOAL_X - x, GOAL_Y - y), math.hypot(GOAL_X - ex, GOAL_Y - ey)
    body = _name(p.get("body_part"))
    f: dict[str, float] = {
        "x": x, "y": y, "end_x": ex, "end_y": ey, "dx": dx, "dy_abs": abs(dy), "length_m": length,
        "forward_ratio": dx / length if length > 0 else 0.0, "progress_m": d0 - d1, "end_dist_goal_m": d1,
        "end_in_box": float(ex >= BOX_X and BOX_Y0 <= ey <= BOX_Y1), "start_own_third": float(x < L / 3),
        "end_final_third": float(ex >= 2 * L / 3), "end_y_central": abs(ey - GOAL_Y),
        "is_head": float(body == "Head"), "is_hands": float(body in ("Keeper Arm", "Drop Kick")),
        "cross": float(bool(p.get("cross"))), "switch": float(bool(p.get("switch"))),
        "cut_back": float(bool(p.get("cut_back"))), "under_pressure": float(bool(ev.get("under_pressure"))),
    }
    f.update(_onehot("type", _name(p.get("type")), PASS_TYPES))
    f.update(_onehot("height", _name(p.get("height")), PASS_HEIGHTS))
    f.update(_onehot("tech", _name(p.get("technique")), PASS_TECHNIQUES))
    f.update(_onehot("pp", _name(ev.get("play_pattern")), PLAY_PATTERNS))
    return f


def is_model_pass(ev: dict[str, Any]) -> bool:
    p = ev.get("pass") or {}
    return (_name(ev.get("type")) == "Pass" and ev.get("period", 1) <= 4 and ev.get("location") is not None
            and p.get("end_location") is not None and _name(p.get("outcome")) != "Injury Clearance")


def pass_label(ev: dict[str, Any]) -> int:
    return int(_name((ev.get("pass") or {}).get("outcome")) not in FAILED)
