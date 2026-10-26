"""Passing motifs: 3/4/5-cycles of open passing lanes between team-mates, scored in context.

Coordinates are in the team's attacking frame; WEIGHTS are untuned design-doc starting values.
"""

from __future__ import annotations

import itertools

import numpy as np

LINK_M, LANE_M, VIABLE = 20.0, 2.5, 0.5
WEIGHTS = {"feasibility": 0.35, "progression": 0.25, "pressure_relief": 0.20, "persistence": 0.20}


def _seg_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = b - a
    t = np.clip(((p - a) @ d) / max(float(d @ d), 1e-9), 0, 1)
    return np.linalg.norm(p - (a + t[:, None] * d), axis=1)


def edges(team: np.ndarray, opp: np.ndarray) -> dict[tuple[int, int], float]:
    """Open edges (i, j) -> rule-based feasibility in [0, 1]."""
    out = {}
    for i, j in itertools.combinations(range(len(team)), 2):
        length = float(np.linalg.norm(team[i] - team[j]))
        if length >= LINK_M:
            continue
        clear = float(_seg_dist(opp, team[i], team[j]).min()) if len(opp) else 10.0
        if clear < LANE_M:
            continue
        out[(i, j)] = float(np.clip((clear - LANE_M) / 5.0, 0, 1) * 0.6 + (1 - length / LINK_M) * 0.4)
    return out


def cycles(adj: dict[int, set[int]], n: int, k: int) -> list[tuple[int, ...]]:
    """Simple k-cycles as sorted node tuples (each cycle once)."""
    found = set()
    for start in range(n):
        stack = [(start, (start,))]
        while stack:
            node, path = stack.pop()
            if len(path) == k:
                if start in adj[node]:
                    found.add(tuple(sorted(path)))
                continue
            for nb in adj[node]:
                if nb > start and nb not in path:
                    stack.append((nb, path + (nb,)))
    return sorted(found)


def sample(team, opp, ball, ids=None, previous: set | None = None) -> dict:
    """Score one team's motifs at one instant; `previous` is the prior sample's `seen` set."""
    team, opp = np.asarray(team, float).reshape(-1, 2), np.asarray(opp, float).reshape(-1, 2)
    ids = list(ids) if ids is not None else list(range(len(team)))
    e = edges(team, opp)
    adj = {i: set() for i in range(len(team))}
    for i, j in e:
        adj[i].add(j)
        adj[j].add(i)
    free = np.clip((np.linalg.norm(team[:, None, :] - opp[None, :, :], axis=2).min(axis=1) - 2) / 8, 0, 1) if len(opp) else np.ones(len(team))
    bx = float(ball[0]) if ball is not None and not np.isnan(ball[0]) else float(team[:, 0].mean())
    out = {"motifs": [], "seen": set()}
    for k in (3, 4, 5):
        for cyc in cycles(adj, len(team), k):
            ring = list(cyc)
            pairs = [tuple(sorted(p)) for p in itertools.combinations(ring, 2) if tuple(sorted(p)) in e]
            feas = float(np.mean([e[p] for p in pairs])) if pairs else 0.0
            prog = float(np.clip((team[ring, 0].max() - bx) / 25.0, 0, 1))
            relief = float(free[ring].mean())
            key = (k, frozenset(ids[i] for i in ring))
            pers = 1.0 if previous and key in previous else 0.0
            score = (WEIGHTS["feasibility"] * feas + WEIGHTS["progression"] * prog + WEIGHTS["pressure_relief"] * relief
                     + WEIGHTS["persistence"] * pers)
            out["motifs"].append({"k": k, "players": sorted(ids[i] for i in ring), "score": round(score, 3), "feasibility": round(feas, 3),
                                  "progression": round(prog, 3), "pressure_relief": round(relief, 3), "persistence": pers})
            out["seen"].add(key)
    for k, name in ((3, "triangles"), (4, "quads"), (5, "pentagons")):
        scores = [m["score"] for m in out["motifs"] if m["k"] == k]
        out[f"{name}"] = len(scores)
        out[f"viable_{name}"] = sum(1 for s in scores if s >= VIABLE)
        out[f"best_{name[:-1]}_score"] = max(scores) if scores else 0.0
    return out
