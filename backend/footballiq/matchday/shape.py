"""Team shape in metres from tracking: depth, width, area, unit lines and the gaps between them.

Only players observed within RECENT_MS count; PFF estimates for off-camera players are often placeholders.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from footballiq.pitch import PITCH_LENGTH_M
from footballiq.replay.timeline import MatchTimeline

ROLE_BY_POSITION = {
    "GK": "GK",
    **dict.fromkeys(("RB", "LB", "CB", "RCB", "LCB", "MCB", "RWB", "LWB", "D", "DEF", "SW"), "DEF"),
    **dict.fromkeys(("DM", "CDM", "RDM", "LDM", "CM", "RCM", "LCM", "AM", "CAM", "RAM", "LAM", "RM", "LM", "M", "MID"), "MID"),
    **dict.fromkeys(("LW", "RW", "CF", "ST", "RF", "LF", "SS", "F", "FW", "ATT"), "ATT"),
}
POSITION_LABEL = {
    "GK": "Goalkeeper", "RB": "Right Back", "LB": "Left Back", "CB": "Centre Back", "RCB": "Right Centre Back",
    "LCB": "Left Centre Back", "MCB": "Centre Back", "RWB": "Right Wing Back", "LWB": "Left Wing Back",
    "DM": "Defensive Midfield", "CM": "Centre Midfield", "AM": "Attacking Midfield", "RM": "Right Midfield",
    "LM": "Left Midfield", "LW": "Left Wing", "RW": "Right Wing", "CF": "Centre Forward", "ST": "Striker",
}
STEP_MS = 30_000
SAMPLE_MS = 1_000
RECENT_MS = 5_000
MIN_OUTFIELD = 8
COMPACT = {"length": 35.0, "width": 40.0, "gap": 14.0}
UNITS = ("DEF", "MID", "ATT")


def hull_area(pts: np.ndarray) -> float:
    """Convex hull area (monotone chain + shoelace)."""
    if len(pts) < 3:
        return 0.0
    p = sorted(map(tuple, pts))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo: list = []
    for q in p:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    up: list = []
    for q in reversed(p):
        while len(up) >= 2 and cross(up[-2], up[-1], q) <= 0:
            up.pop()
        up.append(q)
    h = np.array(lo[:-1] + up[:-1])
    x, y = h[:, 0], h[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)


def tracking_to_match(tl: MatchTimeline) -> dict[str, str]:
    """Tracking id -> match player id by (team, shirt), since provider ids differ; unmatched map to themselves."""
    by_shirt = {(p.team_id, str(p.jersey_number)): p.player_id for p in tl.match.players if p.jersey_number is not None}
    out: dict[str, str] = {}
    if tl.tracking is not None:
        for p in tl.tracking.players:
            if p.player_id:
                out[p.player_id] = by_shirt.get((p.team_id, str(p.jersey_num).lstrip("0") or "0"), p.player_id)
    return out


def match_id_for(tl: MatchTimeline, team_id: str | None, jersey: Any, fallback: str | None) -> str | None:
    by_shirt = {(p.team_id, str(p.jersey_number)): p.player_id for p in tl.match.players if p.jersey_number is not None}
    return by_shirt.get((team_id, str(jersey).lstrip("0") or "0"), fallback)


def player_roles(tl: MatchTimeline) -> dict[str, dict[str, Any]]:
    """player_id -> {role, position, position_code}, from the tracking roster, else median event depth."""
    out: dict[str, dict[str, Any]] = {}
    if tl.tracking is not None:
        to_match = tracking_to_match(tl)
        for p in tl.tracking.players:
            code = (p.position_group or "").upper()
            if p.player_id and code in ROLE_BY_POSITION:
                out[to_match.get(p.player_id, p.player_id)] = {"role": ROLE_BY_POSITION[code], "position": POSITION_LABEL.get(code, code),
                                                               "position_code": code}
    home = tl.match.home.team_id
    depth: dict[str, list[float]] = {}
    keeper: set[str] = set()
    for e in tl.events:
        if not e.player_id or e.player_id in out:
            continue
        if e.type == "Goal Keeper":
            keeper.add(e.player_id)
        if e.x_m is not None and e.type in ("Pass", "Carry", "Ball Receipt*", "Pressure", "Shot", "Duel"):
            depth.setdefault(e.player_id, []).append(e.x_m if e.team_id == home else PITCH_LENGTH_M - e.x_m)
    for pid in keeper:
        out.setdefault(pid, {"role": "GK", "position": "Goalkeeper", "position_code": "GK"})
    for pid, xs in depth.items():
        if pid in out:
            continue
        h = float(np.median(xs))
        role = "DEF" if h < 40 else "MID" if h < 60 else "ATT"
        out[pid] = {"role": role, "position": {"DEF": "Defender", "MID": "Midfielder", "ATT": "Forward"}[role], "position_code": role}
    return out


def _team_shape(xy: np.ndarray, units: np.ndarray, home: bool) -> dict[str, Any] | None:
    """One team's outfield rows in one frame; heights are metres from its own goal line."""
    if len(xy) < MIN_OUTFIELD:
        return None
    h = xy[:, 0] if home else PITCH_LENGTH_M - xy[:, 0]
    y = xy[:, 1]
    out: dict[str, Any] = {"length": float(h.max() - h.min()), "width": float(y.max() - y.min()), "area": hull_area(xy)}
    for u, key in zip(UNITS, ("def", "mid", "att")):
        m = units == u
        out[key] = float(h[m].mean()) if m.any() else None
        out[f"{key}_w"] = float(y[m].max() - y[m].min()) if m.sum() >= 2 else None
    out["gap_dm"] = out["mid"] - out["def"] if out["mid"] is not None and out["def"] is not None else None
    out["gap_ma"] = out["att"] - out["mid"] if out["att"] is not None and out["mid"] is not None else None
    return out


class ShapeIndex:
    """Per-second team shapes for one match (tracking required)."""

    KEYS = ("length", "width", "area", "def", "mid", "att", "gap_dm", "gap_ma", "def_w", "mid_w", "att_w")

    def __init__(self, tl: MatchTimeline, dead: np.ndarray | None = None):
        """dead: [n, 2] dead-ball intervals (ms); samples inside them are skipped (set pieces bunch teams up)."""
        tr = tl.tracking
        if tr is None or tr.n_frames == 0:
            raise ValueError("match has no tracking")
        roles = player_roles(tl)
        to_match = tracking_to_match(tl)
        home_id = tl.match.home.team_id
        n_roster = len(tr.players)
        self.unit = np.array([roles.get(to_match.get(p.player_id or "", ""), {}).get("role", "MID") for p in tr.players] + ["MID"], dtype=object)
        self.side = np.array([0 if p.team_id == home_id else 1 for p in tr.players] + [0], dtype=np.int8)
        # last frame at or before each whole second
        secs = np.arange(int(tr.frame_t[0] // SAMPLE_MS) + 1, int(tr.frame_t[-1] // SAMPLE_MS) + 1) * SAMPLE_MS
        fidx = np.searchsorted(tr.frame_t, secs, side="right") - 1
        fresh = (fidx >= 0) & (secs - tr.frame_t[np.clip(fidx, 0, None)] <= 1_000)
        if dead is not None and len(dead):
            k = np.searchsorted(dead[:, 0], secs, side="right") - 1
            fresh &= ~((k >= 0) & (secs < dead[np.clip(k, 0, None), 1]))
        self.t = secs[fresh]
        # per roster index: observed times (ascending) and positions
        row_t = np.repeat(tr.frame_t, np.diff(tr.offsets))
        obs = tr.p_observed & ~np.isnan(tr.p_xy[:, 0])
        seen: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        for p in np.unique(tr.p_idx):
            m = obs & (tr.p_idx == p)
            seen[int(p)] = (row_t[m], tr.p_xy[m].astype(np.float64))
        # keyed by match player id (heat maps, player focus)
        self.seen = {to_match.get(tr.players[p].player_id, tr.players[p].player_id): v
                     for p, v in seen.items() if p < n_roster and tr.players[p].player_id}
        self.shapes: list[list[dict[str, Any] | None]] = []
        for t, i in zip(self.t, fidx[fresh]):
            s, e = tr.offsets[i], tr.offsets[i + 1]
            on = [int(p) for p in tr.p_idx[s:e] if int(p) < n_roster and self.unit[int(p)] != "GK"]
            pos, unit, side = [], [], []
            for p in on:
                ts, xy = seen.get(p, (np.empty(0, np.int64), None))
                j = int(np.searchsorted(ts, t, side="right")) - 1
                if j >= 0 and t - ts[j] <= RECENT_MS:
                    pos.append(xy[j])
                    unit.append(self.unit[p])
                    side.append(self.side[p])
            pos_a, unit_a, side_a = np.array(pos).reshape(-1, 2), np.array(unit, dtype=object), np.array(side)
            self.shapes.append([_team_shape(pos_a[side_a == k], unit_a[side_a == k], k == 0) for k in (0, 1)])

    def at(self, t_ms: int, window_ms: int = STEP_MS) -> list[dict[str, Any] | None]:
        """Median shape per team over the samples in (t - window, t]."""
        a, b = np.searchsorted(self.t, t_ms - window_ms, side="right"), np.searchsorted(self.t, t_ms, side="right")
        out: list[dict[str, Any] | None] = []
        for k in (0, 1):
            rows = [r[k] for r in self.shapes[a:b] if r[k] is not None]
            if len(rows) < max(3, (b - a) // 3):
                out.append(None)
                continue
            agg: dict[str, Any] = {}
            for key in self.KEYS:
                vals = [r[key] for r in rows if r[key] is not None]
                agg[key] = round(float(np.median(vals)), 1) if vals else None
            out.append(agg)
        return out
