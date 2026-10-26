"""Formation detection: z-scored mean positions matched to templates (Hungarian), smoothed with hysteresis.

Confidence is the cost margin over the runner-up template.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _line(x, n, lo=0.1, hi=0.9):
    return [(x, lo + (hi - lo) * i / (n - 1)) if n > 1 else (x, 0.5) for i in range(n)]


FORMATIONS = {
    "4-4-2": _line(0, 4) + _line(.5, 4) + _line(1, 2, .35, .65),
    "4-3-3": _line(0, 4) + _line(.5, 3, .25, .75) + _line(1, 3, .15, .85),
    "4-2-3-1": _line(0, 4) + _line(.33, 2, .35, .65) + _line(.67, 3, .15, .85) + _line(1, 1),
    "4-1-4-1": _line(0, 4) + _line(.3, 1) + _line(.62, 4) + _line(1, 1),
    "4-4-1-1": _line(0, 4) + _line(.45, 4) + _line(.75, 1) + _line(1, 1),
    "4-5-1": _line(0, 4) + _line(.5, 5, .05, .95) + _line(1, 1),
    "3-5-2": _line(0, 3, .25, .75) + _line(.5, 5, .05, .95) + _line(1, 2, .35, .65),
    "3-4-3": _line(0, 3, .25, .75) + _line(.5, 4) + _line(1, 3, .15, .85),
    "3-4-2-1": _line(0, 3, .25, .75) + _line(.45, 4) + _line(.75, 2, .3, .7) + _line(1, 1),
    "5-3-2": _line(0, 5, .05, .95) + _line(.5, 3, .25, .75) + _line(1, 2, .35, .65),
    "5-4-1": _line(0, 5, .05, .95) + _line(.5, 4) + _line(1, 1),
}


def _z(a) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    sd = a.std(axis=0)
    return (a - a.mean(axis=0)) / np.where(sd > 1e-6, sd, 1.0)


TEMPLATES = {k: _z(v) for k, v in FORMATIONS.items()}


@dataclass(frozen=True)
class Assignment:
    formation: str | None
    cost: float
    confidence: float          # 1 - best / runner-up cost, in [0, 1]
    roles: tuple[int, ...]     # template slot per input player


def assign(points) -> Assignment:
    """points: 10 (x, y) mean positions, team attacking towards +x."""
    pts = np.asarray(points, dtype=float)
    if len(pts) != 10 or np.isnan(pts).any():
        return Assignment(None, float("nan"), 0.0, ())
    from scipy.optimize import linear_sum_assignment
    obs = _z(pts)
    scored = []
    for name, tpl in TEMPLATES.items():
        cost = ((obs[:, None, :] - tpl[None, :, :]) ** 2).sum(axis=2)
        r, c = linear_sum_assignment(cost)
        scored.append((float(cost[r, c].sum()), name, tuple(int(x) for x in c[np.argsort(r)])))
    scored.sort()
    (best, name, roles), runner = scored[0], scored[1][0]
    return Assignment(name, best, max(0.0, 1.0 - best / runner) if runner > 0 else 0.0, roles)


def smooth(labels: list[str | None], confidence: list[float], min_run: int = 2, min_conf: float = 0.05) -> list[str | None]:
    """Hysteresis: keep the current shape until another one wins `min_run` consecutive confident segments."""
    out: list[str | None] = []
    cur, cand, run = None, None, 0
    for lab, conf in zip(labels, confidence):
        if lab is None or conf < min_conf:
            out.append(cur)
            continue
        if cur is None:
            cur = lab
        elif lab != cur:
            run = run + 1 if lab == cand else 1
            cand = lab
            if run >= min_run:
                cur, run, cand = lab, 0, None
        else:
            run, cand = 0, None
        out.append(cur)
    return out


def switches(times: list[int], smoothed: list[str | None]) -> list[tuple[int, str | None, str]]:
    """(time, from, to) for every change of the smoothed shape."""
    out, prev = [], None
    for t, s in zip(times, smoothed):
        if s is not None and s != prev:
            if prev is not None:
                out.append((t, prev, s))
            prev = s
    return out
