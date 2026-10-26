"""Expected threat (xT) grid: xT(z) = s(z) g(z) + m(z) sum_z' T(z -> z') xT(z') (Karun Singh).

Fit on StatsBomb events in the attacking frame (metres); failed moves add no value.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from footballiq.ml.features import L, W, _name, to_m

NX, NY = 16, 12


def zone(x: float, y: float) -> int:
    ix = min(max(int(x / L * NX), 0), NX - 1)
    iy = min(max(int(y / W * NY), 0), NY - 1)
    return ix * NY + iy


def _moves(ev: dict[str, Any]):
    """(start, end, success) for passes and carries; None otherwise."""
    t = _name(ev.get("type"))
    if t == "Pass":
        p = ev.get("pass") or {}
        a, b = to_m(ev.get("location")), to_m(p.get("end_location"))
        if a and b and _name(p.get("type")) not in ("Kick Off",):
            return a, b, _name(p.get("outcome")) is None
    elif t == "Carry":
        a, b = to_m(ev.get("location")), to_m((ev.get("carry") or {}).get("end_location"))
        if a and b:
            return a, b, True
    return None


def counts(events: Iterable[dict[str, Any]]) -> dict[str, np.ndarray]:
    """Shot / goal / move / transition counts per zone; additive across matches."""
    n = NX * NY
    c = {"shots": np.zeros(n), "goals": np.zeros(n), "moves": np.zeros(n), "trans": np.zeros((n, n))}
    for ev in events:
        if ev.get("period", 1) > 4:
            continue
        if _name(ev.get("type")) == "Shot":
            xy = to_m(ev.get("location"))
            if xy and _name((ev.get("shot") or {}).get("type")) != "Penalty":
                z = zone(*xy)
                c["shots"][z] += 1
                c["goals"][z] += _name((ev.get("shot") or {}).get("outcome")) == "Goal"
            continue
        mv = _moves(ev)
        if mv:
            a, b, ok = mv
            z = zone(*a)
            c["moves"][z] += 1
            if ok:
                c["trans"][z, zone(*b)] += 1
    return c


def solve(c: dict[str, np.ndarray], iterations: int = 30) -> np.ndarray:
    shots, goals, moves, trans = c["shots"], c["goals"], c["moves"], c["trans"]
    total = shots + moves
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(total > 0, shots / total, 0.0)
        m = np.where(total > 0, moves / total, 0.0)
        g = np.where(shots > 0, goals / shots, 0.0)
        T = np.where(moves[:, None] > 0, trans / moves[:, None], 0.0)
    xt = np.zeros(NX * NY)
    for _ in range(iterations):
        xt = s * g + m * (T @ xt)
    return xt.reshape(NX, NY)


def fit(events: Iterable[dict[str, Any]], iterations: int = 30) -> np.ndarray:
    return solve(counts(events), iterations)


def value(grid: np.ndarray, x: float, y: float) -> float:
    z = zone(x, y)
    return float(grid[z // NY, z % NY])


def added(grid: np.ndarray, ev: dict[str, Any]) -> tuple[float, float, float] | None:
    """(xT at start, xT at end, xT added) for a successful pass or carry; None for anything else."""
    mv = _moves(ev)
    if not mv or not mv[2]:
        return None
    a, b, _ = mv
    va, vb = value(grid, *a), value(grid, *b)
    return va, vb, vb - va
