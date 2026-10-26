"""Win / draw / loss chance at the end of the current phase (90' or 120').

Model forecast when available, else neutral-rate Poisson goals; both use only score and clock at t.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

from footballiq.replay.timeline import MatchTimeline
from footballiq.schema import PERIOD_BASE_MINUTE

GOALS_PER_TEAM_90 = 1.3


def match_minute(tl: MatchTimeline, t_ms: int) -> tuple[float, int]:
    """(minutes on the scoreboard clock, period) at t; stoppage time keeps counting past 45/90."""
    period = tl.period_at(t_ms)
    start = next((p.start_match_ms for p in tl.match.periods if p.period == period), 0)
    return PERIOD_BASE_MINUTE.get(period, 0) + (t_ms - start) / 60_000, period


def _pois(lam: float, k: int) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def poisson_wdl(score: tuple[int, int], minutes_left: float, rate: float = GOALS_PER_TEAM_90) -> list[float]:
    lam = rate * max(0.0, minutes_left) / 90
    w = d = l = 0.0
    for i in range(9):
        for j in range(9):
            p = _pois(lam, i) * _pois(lam, j)
            a, b = score[0] + i, score[1] + j
            if a > b:
                w += p
            elif a == b:
                d += p
            else:
                l += p
    s = w + d + l
    return [w / s, d / s, l / s]


def poisson_at(tl: MatchTimeline, t_ms: int, score: tuple[int, int]) -> list[float] | None:
    minute, period = match_minute(tl, t_ms)
    if period >= 5:
        return None
    end = 90 if period <= 2 else 120
    return poisson_wdl(score, max(end - minute, 0.5))


class ModelWin:
    """Latest model forecast at or before t, as [home, draw, away]."""

    def __init__(self, series: dict[str, Any], home: str, away: str):
        def arr(points):
            return (np.array([p["t_ms"] for p in points], dtype=np.int64), np.array([p["p"] for p in points], dtype=np.float64))

        self.h, self.a, self.d = arr(series["win"].get(home, [])), arr(series["win"].get(away, [])), arr(series.get("draw", []))
        self.ok = all(len(x[0]) for x in (self.h, self.a, self.d))

    def at(self, t_ms: int) -> list[float] | None:
        vals = []
        for ts, ps in (self.h, self.d, self.a):
            k = int(np.searchsorted(ts, t_ms, side="right")) - 1
            if k < 0:
                return None
            vals.append(float(ps[k]))
        s = sum(vals)
        return [v / s for v in vals] if s > 0 else None


def win_series(tl: MatchTimeline, times: list[int], score_at: Callable[[int], tuple[int, int]],
               model: ModelWin | None = None) -> list[list[float] | None]:
    out = []
    for t in times:
        v = model.at(t) if model is not None and model.ok else None
        out.append([round(x, 3) for x in v] if v else (lambda p: [round(x, 3) for x in p] if p else None)(poisson_at(tl, t, score_at(t))))
    return out
