"""Shot ball flight from tracking: bend, swerve, speed, launch and height at the goal line.

Fits lateral = a + b*fwd + c*fwd^2 in the shooter's frame; positive curve bends to the shooter's left.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from footballiq.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M
from footballiq.schema import MatchEvent

GOAL_Y = PITCH_WIDTH_M / 2
# event and tracking clocks disagree by up to ~2 s
SEARCH_BEFORE_MS, SEARCH_AFTER_MS, MAX_FLIGHT_MS = 3000, 1000, 3000
MAX_START_GAP_M = 5.0
MIN_FORWARD_M = 6.0
TAKE_OFF_MPS = 12.0
GLITCH_MS = 250
# bend is reported only for a path that is mostly seen, smooth and long enough
CURVE_MIN_OBSERVED, CURVE_MAX_RESID_M, CURVE_MIN_SAMPLES, CURVE_MAX_DEG = 0.5, 0.5, 8, 45.0


def _attacker_frame(x: np.ndarray, y: np.ndarray, is_home: bool) -> tuple[np.ndarray, np.ndarray]:
    """Forward towards the attacked goal; lateral positive to the shooter's left (y grows to the bottom touchline)."""
    return (x, GOAL_Y - y) if is_home else (PITCH_LENGTH_M - x, y - GOAL_Y)


def _clean(t: np.ndarray, xyz: np.ndarray, obs: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Drop repeated samples from upsampled feeds and single-frame tracker glitches."""
    if len(t) < 3:
        return t, xyz, obs
    rep = np.r_[False, np.all(np.isclose(xyz[1:, :2], xyz[:-1, :2]), axis=1)]
    t, xyz, obs = t[~rep], xyz[~rep], obs[~rep]
    if len(t) < 3:
        return t, xyz, obs
    mid = (xyz[:-2, :2] + xyz[2:, :2]) / 2
    off = np.hypot(*(xyz[1:-1, :2] - mid).T)
    span = np.hypot(*(xyz[2:, :2] - xyz[:-2, :2]).T)
    glitch = np.r_[False, (off > 1.0) & (off > 0.6 * span), False]   # far off the line its neighbours agree on
    return t[~glitch], xyz[~glitch], obs[~glitch]


def _interpolated(fwd: np.ndarray, lat: np.ndarray) -> bool:
    """True when the path is straight-line fill between a few key points (constant step vectors)."""
    if len(fwd) < 5:
        return False
    d = np.c_[np.diff(fwd), np.diff(lat)]
    same = np.all(np.abs(np.diff(d, axis=0)) < 0.02, axis=1)
    return bool(same.mean() > 0.7)


def unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def flight(tr, shot: MatchEvent, is_home: bool, at_ms: int) -> dict[str, Any]:
    if tr is None:
        return unavailable("No ball tracking for this match (events only), so the flight path is unknown.")
    if shot.x_m is None or shot.y_m is None:
        return unavailable("Shot has no location.")
    lo, hi = tr.index_at(shot.match_elapsed_ms - SEARCH_BEFORE_MS), tr.index_at(min(at_ms, shot.match_elapsed_ms + SEARCH_AFTER_MS))
    if hi - lo < 2:
        return unavailable("No tracking frames around the shot.")
    b = tr.ball[lo:hi].astype(np.float64)
    d = np.hypot(b[:, 0] - shot.x_m, b[:, 1] - shot.y_m)
    if np.all(np.isnan(d)) or np.nanmin(d) > MAX_START_GAP_M:
        return unavailable("The tracked ball is not near the shot location (ball not visible at the strike).")
    # strike = first take-off near the spot; a penalty ball can rest there for seconds
    ft = tr.frame_t[lo:hi].astype(np.float64)
    step = np.hypot(np.diff(b[:, 0]), np.diff(b[:, 1])) / np.maximum(np.diff(ft) / 1000, 1e-3)
    take_off = [i for i in range(len(step) - 1) if d[i] <= MAX_START_GAP_M and min(step[i], step[i + 1]) > TAKE_OFF_MPS]
    start = lo + (take_off[0] if take_off else int(np.nanargmin(d)))
    end = tr.index_at(min(at_ms, int(tr.frame_t[start]) + MAX_FLIGHT_MS))

    t = tr.frame_t[start:end].astype(np.int64)
    xyz = tr.ball[start:end].astype(np.float64)
    obs = tr.ball_observed[start:end].astype(bool)
    keep = ~np.isnan(xyz[:, 0])
    t, xyz, obs = t[keep], xyz[keep], obs[keep]
    t, xyz, obs = _clean(t, xyz, obs)
    fwd, lat = _attacker_frame(xyz[:, 0], xyz[:, 1], is_home)
    # stop at the goal line, touchline or a real turn back; reversals within GLITCH_MS are noise
    idx = [0]
    for i in range(1, len(fwd)):
        last = idx[-1]
        if fwd[last] >= PITCH_LENGTH_M or abs(lat[i]) > GOAL_Y + 1:
            break
        if fwd[i] < fwd[last] - 0.5:
            ahead = [j for j in range(i + 1, len(fwd)) if t[j] - t[i] <= GLITCH_MS]
            if any(fwd[j] > fwd[last] for j in ahead):
                continue
            break
        idx.append(i)
    sel = np.asarray(idx)
    t, xyz, obs, fwd, lat = t[sel], xyz[sel], obs[sel], fwd[sel], lat[sel]
    n = len(t)
    if n < 5:
        return unavailable("Too few tracked ball samples in flight.")
    length = float(fwd[-1] - fwd[0])
    if length < MIN_FORWARD_M:
        return unavailable(f"Ball travelled only {length:.1f} m forward: too short to measure bend.")

    w = np.where(obs, 1.0, 0.3)
    c, b1, a = np.polyfit(fwd, lat, 2, w=w)
    slope = lambda f: b1 + 2 * c * f
    curve = math.degrees(math.atan(slope(fwd[-1])) - math.atan(slope(fwd[0])))
    swerve = abs(c) * length ** 2 / 4
    resid = float(np.sqrt(np.average((lat - (a + b1 * fwd + c * fwd ** 2)) ** 2, weights=w)))
    observed = float(obs.mean())
    # an unseen ball is reconstructed as a straight line, so its curve is not in the data
    straight_fill = observed < 0.5 and (_interpolated(fwd, lat) or resid < 0.05)
    curve_reason = None
    if straight_fill:
        curve_reason = "The tracking provider did not see the ball in flight and reconstructed it as a straight line, so the curve is not in this data."
    elif observed < CURVE_MIN_OBSERVED or n < CURVE_MIN_SAMPLES or resid > CURVE_MAX_RESID_M or abs(curve) > CURVE_MAX_DEG:
        curve_reason = (f"The tracked path is too short or noisy to measure the bend ({n} samples, {100 * observed:.0f}% seen, "
                        f"{resid:.2f} m scatter).")
    measurable = curve_reason is None

    # median step speed over the first 0.4 s, in km/h, sanity-capped
    k = max(3, int(np.searchsorted(t, t[0] + 400)))
    steps = np.hypot(np.diff(xyz[:k, 0]), np.diff(xyz[:k, 1])) / np.maximum(np.diff(t[:k]) / 1000, 1e-3)
    speed = float(np.median(steps)) * 3.6 if len(steps) else None
    if speed is not None and not 10 <= speed <= 150:
        speed = None
    z = xyz[:, 2]
    has_z = not np.all(np.isnan(z))
    launch = None
    j = min(k - 1, n - 1)
    if has_z and not np.isnan(z[0]) and not np.isnan(z[j]):
        launch = math.degrees(math.atan2(z[j] - z[0], max(1e-3, float(np.hypot(*(xyz[j, :2] - xyz[0, :2]))))))
    reached = fwd[-1] >= PITCH_LENGTH_M - 0.75
    conf = "high" if observed >= 0.8 and n >= 10 and resid < 0.4 else "medium" if observed >= 0.5 and n >= 6 else "low"
    return {
        "available": True,
        "curve_measurable": measurable, "curve_reason": curve_reason,
        "curve_deg": round(curve, 1) if measurable else None,
        "bend": ("left" if curve > 2 else "right" if curve < -2 else "straight") if measurable else None,
        "swerve_m": round(swerve, 2) if measurable else None,
        "speed_kmh": round(speed, 1) if speed is not None else None,
        "launch_deg": round(launch, 1) if launch is not None else None,
        "peak_height_m": round(float(np.nanmax(z)), 2) if has_z else None,
        "height_at_line_m": round(float(z[-1]), 2) if has_z and reached and not np.isnan(z[-1]) else None,
        "lateral_at_line_m": round(float(lat[-1]), 2) if reached else None,
        "flight_ms": int(t[-1] - t[0]), "distance_m": round(float(np.hypot(*(xyz[-1, :2] - xyz[0, :2]))), 1),
        "samples": n, "observed_pct": round(100 * observed, 0), "fit_residual_m": round(resid, 2), "confidence": conf,
        "reached_goal_line": bool(reached), "source": tr.source, "estimated": observed < 0.5,
        "note": None if observed >= 0.5 else "Ball not seen by the cameras for most of the flight: values are the tracking provider's reconstruction.",
        "path": [[int(tt), round(float(x), 2), round(float(y), 2), None if np.isnan(zz) else round(float(zz), 2), int(o)]
                 for tt, (x, y, zz), o in zip(t, xyz, obs)],
    }
