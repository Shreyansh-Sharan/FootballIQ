"""Tracking timeline: 30 Hz positions as flat numpy arrays with per-frame offsets.

Only frames with t <= replay_t are served, and each position keeps its PFF ``observed`` flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class TrackedPlayer:
    idx: int
    team_id: str
    side: str
    jersey_num: str
    player_id: str | None = None
    name: str | None = None
    position_group: str | None = None
    started: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"idx": self.idx, "team_id": self.team_id, "side": self.side, "jersey": self.jersey_num,
                "player_id": self.player_id, "name": self.name, "position_group": self.position_group,
                "started": self.started}


@dataclass
class TrackingTimeline:
    match_id: str
    source: str
    frame_t: np.ndarray          # int64 [F] match_elapsed_ms, ascending
    frame_num: np.ndarray        # int64 [F]
    period: np.ndarray           # int8  [F]
    ball: np.ndarray             # float32 [F, 3] (nan when absent)
    ball_observed: np.ndarray    # bool [F]
    offsets: np.ndarray          # int64 [F + 1] into the player arrays
    p_idx: np.ndarray            # int16 [N] index into ``players``
    p_xy: np.ndarray             # float32 [N, 2]
    p_observed: np.ndarray       # bool [N]
    players: list[TrackedPlayer] = field(default_factory=list)
    hz: float = 29.97

    # ---------------------------------------------------------------- construction
    @classmethod
    def from_columns(cls, match_id: str, source: str, frames: dict[str, np.ndarray],
                     positions: dict[str, np.ndarray], players: list[TrackedPlayer]) -> TrackingTimeline:
        """frames: frame_num, t, period, ball_x/y/z, ball_observed; positions: frame_num, player_idx, x, y, observed."""
        order = np.argsort(frames["frame_num"], kind="stable")
        fnum = frames["frame_num"][order].astype(np.int64)
        ft = frames["t"][order].astype(np.int64)
        # canonical time must be monotonic for bisect; order by (t, frame_num)
        torder = np.lexsort((fnum, ft))
        fnum, ft = fnum[torder], ft[torder]
        sel = order[torder]

        porder = np.argsort(positions["frame_num"], kind="stable")
        pf = positions["frame_num"][porder].astype(np.int64)
        # offsets in frame_num order, then re-ordered to time order
        starts_by_num = np.searchsorted(pf, fnum, side="left")
        ends_by_num = np.searchsorted(pf, fnum, side="right")
        take = np.concatenate([np.arange(s, e) for s, e in zip(starts_by_num, ends_by_num)]) if len(fnum) else np.array([], int)
        counts = ends_by_num - starts_by_num
        offsets = np.zeros(len(fnum) + 1, dtype=np.int64)
        np.cumsum(counts, out=offsets[1:])
        pi = porder[take]
        ball = np.stack([frames["ball_x"][sel], frames["ball_y"][sel], frames["ball_z"][sel]], axis=1).astype(np.float32)
        span_s = (ft[-1] - ft[0]) / 1000 if len(ft) > 1 else 0
        return cls(
            match_id=match_id, source=source, frame_t=ft, frame_num=fnum,
            period=frames["period"][sel].astype(np.int8), ball=ball,
            ball_observed=frames["ball_observed"][sel].astype(bool), offsets=offsets,
            p_idx=positions["player_idx"][pi].astype(np.int16),
            p_xy=np.stack([positions["x"][pi], positions["y"][pi]], axis=1).astype(np.float32),
            p_observed=positions["observed"][pi].astype(bool), players=players,
            hz=float(round(len(ft) / span_s, 2)) if span_s else 0.0,
        )

    # ---------------------------------------------------------------- queries
    @property
    def n_frames(self) -> int:
        return len(self.frame_t)

    def index_at(self, t_ms: int) -> int:
        """Number of frames with t <= t_ms."""
        return int(np.searchsorted(self.frame_t, t_ms, side="right"))

    def frame(self, i: int) -> list[Any]:
        """Compact wire format: [t_ms, frame_num, [bx, by, bz, ball_obs] | None, [[idx, x, y, obs], ...]]."""
        b = self.ball[i]
        ball = None if np.isnan(b[0]) else [round(float(b[0]), 2), round(float(b[1]), 2),
                                             round(float(b[2]), 2) if not np.isnan(b[2]) else None,
                                             int(self.ball_observed[i])]
        s, e = self.offsets[i], self.offsets[i + 1]
        xy = self.p_xy[s:e].astype(np.float64)
        players = [[int(p), round(float(x), 2), round(float(y), 2), int(o)]
                   for p, (x, y), o in zip(self.p_idx[s:e], xy, self.p_observed[s:e]) if not np.isnan(x)]
        return [int(self.frame_t[i]), int(self.frame_num[i]), ball, players]

    def frames_between(self, from_ms: int, to_ms: int, max_frames: int | None = None) -> list[list[Any]]:
        """Frames with from_ms < t <= to_ms, evenly thinned to at most max_frames (latest always kept)."""
        lo = self.index_at(from_ms)
        hi = self.index_at(to_ms)
        idx = range(lo, hi)
        if max_frames and hi - lo > max_frames:
            step = (hi - lo) / max_frames
            idx = sorted({min(hi - 1, int(lo + step * (k + 1)) - 1) for k in range(max_frames)})
        return [self.frame(i) for i in idx]

    def latest_frame(self, t_ms: int, max_age_ms: int = 2000) -> list[Any] | None:
        i = self.index_at(t_ms) - 1
        if i < 0 or t_ms - self.frame_t[i] > max_age_ms:
            return None
        return self.frame(i)

    def coverage(self) -> dict[str, Any]:
        return {
            "frames": self.n_frames, "hz": self.hz,
            "player_observed_pct": round(100 * float(self.p_observed.mean()), 1) if len(self.p_observed) else None,
            "ball_observed_pct": round(100 * float(self.ball_observed.mean()), 1) if self.n_frames else None,
            "periods": sorted({int(p) for p in np.unique(self.period)}),
        }

    def roster(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self.players]


def gaps(frame_t: np.ndarray, min_gap_ms: int = 1000) -> list[tuple[int, int]]:
    """Intervals (start_ms, end_ms) with no tracking frames longer than min_gap_ms."""
    d = np.diff(frame_t)
    idx = np.nonzero(d > min_gap_ms)[0]
    return [(int(frame_t[i]), int(frame_t[i + 1])) for i in idx]
