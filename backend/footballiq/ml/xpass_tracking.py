"""Tracking-based xPass features (xpass_tracking_v1), separate from the event-based xpass_event_v1.

One row per pass in the attacking frame, aimed at the intended receiver so the outcome never leaks.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

L, W = 105.0, 68.0
GOAL = np.array([L, W / 2])
BOX_X, BOX_Y0, BOX_Y1 = L - 16.5, W / 2 - 20.16, W / 2 + 20.16

HEIGHT = {"G": "ground", "L": "low", "H": "high"}
BODY = {"R": "right_foot", "L": "left_foot", "H": "head"}
SETPIECE = {"O": "open_play", "C": "corner", "F": "free_kick", "T": "throw_in", "G": "goal_kick", "K": "kick_off", "P": "penalty"}

EVENT_FEATURES = [
    "x", "y_abs", "tx", "ty_abs", "length_m", "dx", "forward_ratio", "progress_m", "target_in_box", "target_final_third",
    *[f"height_{v}" for v in HEIGHT.values()], *[f"body_{v}" for v in BODY.values()], *[f"sp_{v}" for v in SETPIECE.values()],
    "is_cross",
]
# *_observed flags: broadcast tracking estimates off-camera players
TRACKING_FEATURES = [
    "press_nearest_m", "press_within_3m", "press_within_5m",
    "lane_min_dist_m", "lane_within_1_5m", "lane_within_3m",
    "target_nearest_opp_m", "target_opps_within_5m", "target_mates_within_10m", "opps_goal_side_of_target",
    "target_speed_mps", "passer_observed", "target_observed", "opps_observed_share",
]


def _seg_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Distance from points p [N, 2] to segment a-b."""
    d = b - a
    dd = float(d @ d) or 1e-9
    t = np.clip(((p - a) @ d) / dd, 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * d), axis=1)


def features(passer_xy, target_xy, mates_xy, opps_xy, *, attack_right: bool, height: str | None, body: str | None,
             setpiece: str | None, is_cross: bool, target_speed: float | None, passer_observed: bool | None,
             target_observed: bool | None, opps_observed: list[bool | None]) -> dict[str, float]:
    """All coordinates canonical; flipped here so the passing team attacks towards x = 105."""
    def flip(a):
        a = np.asarray(a, dtype=float).reshape(-1, 2)
        return a if attack_right else np.column_stack([L - a[:, 0], W - a[:, 1]])

    p, t = flip(passer_xy)[0], flip(target_xy)[0]
    mates, opps = flip(mates_xy), flip(opps_xy)
    d = t - p
    length = float(np.hypot(*d))
    f: dict[str, float] = {
        "x": p[0], "y_abs": abs(p[1] - W / 2), "tx": t[0], "ty_abs": abs(t[1] - W / 2), "length_m": length, "dx": d[0],
        "forward_ratio": d[0] / length if length > 0 else 0.0,
        "progress_m": float(np.hypot(*(GOAL - p)) - np.hypot(*(GOAL - t))),
        "target_in_box": float(t[0] >= BOX_X and BOX_Y0 <= t[1] <= BOX_Y1), "target_final_third": float(t[0] >= 2 * L / 3),
        "is_cross": float(bool(is_cross)),
    }
    f.update({f"height_{v}": float(height == k) for k, v in HEIGHT.items()})
    f.update({f"body_{v}": float(body == k) for k, v in BODY.items()})
    f.update({f"sp_{v}": float(setpiece == k) for k, v in SETPIECE.items()})
    if len(opps):
        dp = np.linalg.norm(opps - p, axis=1)
        dl = _seg_dist(opps, p, t)
        dt = np.linalg.norm(opps - t, axis=1)
        f.update({"press_nearest_m": float(dp.min()), "press_within_3m": float((dp < 3).sum()), "press_within_5m": float((dp < 5).sum()),
                  "lane_min_dist_m": float(dl.min()), "lane_within_1_5m": float((dl < 1.5).sum()), "lane_within_3m": float((dl < 3).sum()),
                  "target_nearest_opp_m": float(dt.min()), "target_opps_within_5m": float((dt < 5).sum()),
                  "opps_goal_side_of_target": float((opps[:, 0] > t[0]).sum())})
    else:
        f.update({k: math.nan for k in ("press_nearest_m", "press_within_3m", "press_within_5m", "lane_min_dist_m",
                                        "lane_within_1_5m", "lane_within_3m", "target_nearest_opp_m", "target_opps_within_5m",
                                        "opps_goal_side_of_target")})
    dm = np.linalg.norm(mates - t, axis=1) if len(mates) else np.array([])
    f["target_mates_within_10m"] = float((dm < 10).sum()) if len(dm) else math.nan
    f["target_speed_mps"] = math.nan if target_speed is None else float(target_speed)
    f["passer_observed"] = math.nan if passer_observed is None else float(passer_observed)
    f["target_observed"] = math.nan if target_observed is None else float(target_observed)
    known = [v for v in opps_observed if v is not None]
    f["opps_observed_share"] = float(np.mean(known)) if known else math.nan
    return f


def build_rows(passes: list[dict[str, Any]], frames: dict[tuple[int, int], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """One row per pass whose passer and target are on its frame.

    frames: (pff_game_id, frame_num) -> player rows (side, jersey_num, x, y, speed_mps, is_observed)."""
    rows = []
    for ps in passes:
        players = frames.get((ps["pff_game_id"], ps["frame_num"]))
        if not players:
            continue
        own = [r for r in players if r["side"] == ps["side"]]
        opp = [r for r in players if r["side"] != ps["side"]]
        passer = next((r for r in own if str(r["jersey_num"]) == str(ps["passer_jersey"])), None)
        target = next((r for r in own if str(r["jersey_num"]) == str(ps["target_jersey"])), None)
        if passer is None or target is None or passer is target:
            continue
        mates = [r for r in own if r is not passer and r is not target]
        f = features((passer["x"], passer["y"]), (target["x"], target["y"]), [(r["x"], r["y"]) for r in mates],
                     [(r["x"], r["y"]) for r in opp], attack_right=ps["side"] == "home", height=ps.get("height"),
                     body=ps.get("body"), setpiece=ps.get("setpiece"), is_cross=bool(ps.get("is_cross")),
                     target_speed=target.get("speed_mps"), passer_observed=passer.get("is_observed"),
                     target_observed=target.get("is_observed"), opps_observed=[r.get("is_observed") for r in opp])
        rows.append({"match_id": ps["match_id"], "match_date": ps["match_date"], "event_id": ps["event_id"],
                     "pff_game_id": ps["pff_game_id"], "team_id": ps["team_id"], "label": int(ps["label"]), **f})
    return rows
