"""Control vs chaos and game rhythm: one point per 30 s over a rolling 5-minute event window.

Ingredients are scaled between World Cup 2022 p10 and p90 (RANGES), so 50 is a typical window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from footballiq.pitch import PITCH_LENGTH_M
from footballiq.replay.timeline import MatchTimeline

STEP_MS = 30_000
WINDOW_MS = 300_000
RESTART_PASSES = {"Free Kick", "Throw-in", "Goal Kick", "Corner", "Kick Off"}
RESTART_SHOTS = {"Penalty", "Free Kick"}
OPEN_PLAY = {"Regular Play", "From Counter"}
DUEL_TYPES = {"Duel", "50/50", "Dribble", "Foul Committed"}
LONG_PASS_M = 32.0
FINAL_THIRD_M = PITCH_LENGTH_M * 2 / 3
TRANSITION_MS = 15_000
MAX_DEAD_MS = 180_000
SETTLED_PASSES = 4

# p10 / p90 of 5-minute windows, World Cup 2022 (scripts/calibrate_flow.py)
RANGES: dict[str, tuple[float, float]] = {
    "turnovers": (0.2, 1.0), "duels": (0.6, 2.0), "transitions": (0.0, 0.4),
    "long_share": (0.05, 0.20), "avg_seq": (3.4, 10.0), "pass_acc": (0.58, 0.925),
}
# pattern thresholds, World Cup calibrated; scale() checks them in order, first match wins
RULES: dict[str, float] = {
    "stop_start_bip": 0.47, "end_to_end_transitions": 0.6, "end_to_end_long": 0.15, "end_to_end_turnovers": 0.8,
    "siege_tilt": 0.85, "siege_min_passes": 10, "settled_seq": 7.5, "settled_turnovers": 0.6, "high_tempo": 17.5,
}
WEIGHTS = {"turnovers": 0.30, "duels": 0.20, "transitions": 0.20, "long_share": 0.15, "avg_seq": 0.15}


def norm(v: float, key: str) -> float:
    lo, hi = RANGES[key]
    return float(min(1.0, max(0.0, (v - lo) / (hi - lo))))


@dataclass
class _Seq:
    """One possession sequence, evaluable causally at any time t."""
    team: int
    t0: int
    starts: np.ndarray      # event start times, ascending
    ends: np.ndarray        # running max of start + duration
    pass_t: np.ndarray      # possession team's pass times
    turnover: bool          # open-play start after the other team's possession
    fast_t: int | None      # reached the final third or shot within 15 s

    def held_until(self, t: int) -> int | None:
        k = int(np.searchsorted(self.starts, t, side="right"))
        return None if k == 0 else min(t, int(self.ends[k - 1]))

    def passes_by(self, t: int) -> int:
        return int(np.searchsorted(self.pass_t, t, side="right"))


class FlowIndex:
    """Per-match event arrays; any window is a few binary searches over events started at or before t."""

    def __init__(self, tl: MatchTimeline):
        home, away = tl.team_ids
        side = {home: 0, away: 1}
        evs = [e for e in tl.events if e.period <= 4 and not e.is_shootout]
        self.duration_ms = max((p.start_match_ms + p.duration_ms for p in tl.match.periods if p.period <= 4), default=0)

        def height(e, x):   # metres from the team's own goal (home attacks left to right)
            return x if side.get(e.team_id) == 0 else PITCH_LENGTH_M - x

        passes = []
        for e in evs:
            if e.type != "Pass" or e.subtype == "Throw-in" or e.outcome in ("Unknown", "Injury Clearance") or e.team_id not in side:
                continue
            ok = e.outcome == "Complete"
            length = (np.hypot(e.end_x_m - e.x_m, e.end_y_m - e.y_m)
                      if None not in (e.x_m, e.y_m, e.end_x_m, e.end_y_m) else 0.0)
            f3 = ok and e.end_x_m is not None and height(e, e.end_x_m) >= FINAL_THIRD_M
            passes.append((e.match_elapsed_ms, side[e.team_id], ok, length >= LONG_PASS_M, f3))
        p = np.array(passes, dtype=np.float64).reshape(-1, 5)
        self.pass_t = p[:, 0].astype(np.int64)
        self.pass_team, self.pass_ok, self.pass_long, self.pass_f3 = (p[:, k] for k in range(1, 5))

        self.duel_t = np.array([e.match_elapsed_ms for e in evs if e.type in DUEL_TYPES], dtype=np.int64)

        groups: dict[int, list] = {}
        for e in evs:
            if e.possession is None or e.possession_team_id not in side:
                continue
            groups.setdefault(e.possession, []).append(e)
        self.seqs: list[_Seq] = []
        prev_team = None
        for pid in sorted(groups):
            group = groups[pid]
            team = side[group[0].possession_team_id]
            t0 = group[0].match_elapsed_ms
            turnover = prev_team is not None and team != prev_team and group[0].play_pattern in OPEN_PLAY
            fast_t = None
            if turnover:
                for e in group:
                    if e.match_elapsed_ms - t0 > TRANSITION_MS:
                        break
                    if side.get(e.team_id) == team and (e.type == "Shot" or (e.x_m is not None and height(e, e.x_m) >= FINAL_THIRD_M)):
                        fast_t = e.match_elapsed_ms
                        break
            starts = np.array([e.match_elapsed_ms for e in group], dtype=np.int64)
            ends = np.maximum.accumulate(starts + np.array([e.duration_ms or 0 for e in group], dtype=np.int64))
            pass_t = np.array([e.match_elapsed_ms for e in group if e.type == "Pass" and side.get(e.team_id) == team], dtype=np.int64)
            self.seqs.append(_Seq(team, t0, starts, ends, pass_t, turnover, fast_t))
            prev_team = team
        self.seq_t0 = np.array([s.t0 for s in self.seqs], dtype=np.int64)
        self.turnover_t = np.array([s.t0 for s in self.seqs if s.turnover], dtype=np.int64)
        self.transition_t = np.sort(np.array([s.fast_t for s in self.seqs if s.fast_t is not None], dtype=np.int64))

        # dead ball: end of the event before a restart until the restart
        dead = []
        for prev, e in zip(evs, evs[1:]):
            restart = (e.type == "Pass" and e.subtype in RESTART_PASSES) or (e.type == "Shot" and e.subtype in RESTART_SHOTS)
            if restart and prev.period == e.period:
                start = prev.match_elapsed_ms + (prev.duration_ms or 0)
                if e.match_elapsed_ms > start:
                    dead.append((max(start, e.match_elapsed_ms - MAX_DEAD_MS), e.match_elapsed_ms))
        self.dead = np.array(dead, dtype=np.int64).reshape(-1, 2)

    # ------------------------------------------------------------------ windows
    def _count(self, arr: np.ndarray, t0: int, t1: int) -> int:
        return int(np.searchsorted(arr, t1, side="right") - np.searchsorted(arr, t0, side="right"))

    def raw(self, t: int, window_ms: int = WINDOW_MS) -> dict[str, Any]:
        """Unscaled ingredients for the window (t - window_ms, t], from events at or before t only."""
        t0 = max(0, t - window_ms)
        span = max(1, t - t0)
        a, b = np.searchsorted(self.pass_t, t0, side="right"), np.searchsorted(self.pass_t, t, side="right")
        team, ok, long_, f3 = self.pass_team[a:b], self.pass_ok[a:b], self.pass_long[a:b], self.pass_f3[a:b]
        n_pass = b - a
        dead = 0
        if len(self.dead):
            done = self.dead[:, 1] <= t                      # a stoppage is only known once play restarts
            lo, hi = np.maximum(self.dead[done, 0], t0), np.minimum(self.dead[done, 1], t)
            dead = int(np.clip(hi - lo, 0, None).sum())
        play_ms = max(span - dead, 1)
        minutes = span / 60_000
        stops = self._count(self.dead[:, 1], t0, t) if len(self.dead) else 0

        poss = [0.0, 0.0]
        n_seq, settled, seq_passes = [0, 0], [0, 0], []
        first = max(0, int(np.searchsorted(self.seq_t0, t0 - 10 * WINDOW_MS, side="left")))
        last = int(np.searchsorted(self.seq_t0, t, side="right"))
        for s in self.seqs[first:last]:
            end = s.held_until(t)
            if end is not None and end > t0:
                poss[s.team] += max(0, end - max(s.t0, t0))
            if s.t0 > t0:
                n = s.passes_by(t)
                n_seq[s.team] += 1
                settled[s.team] += n >= SETTLED_PASSES
                seq_passes.append(n)
        avg_seq = float(np.mean(seq_passes)) if seq_passes else None

        acc = [float(ok[team == k].mean()) if (team == k).any() else None for k in (0, 1)]
        f3n = [int(f3[team == k].sum()) for k in (0, 1)]
        return {
            "t": t, "span_ms": span, "minutes": minutes, "play_ms": play_ms, "bip": play_ms / span, "stops": stops,
            "passes": int(n_pass), "tempo": n_pass / (play_ms / 60_000),
            "turnovers": self._count(self.turnover_t, t0, t) / minutes,
            "duels": self._count(self.duel_t, t0, t) / minutes,
            "transitions": self._count(self.transition_t, t0, t) / minutes,
            "long_share": float(long_.mean()) if n_pass else 0.0,
            "avg_seq": avg_seq, "poss_ms": poss, "n_seq": n_seq, "settled": settled, "pass_acc": acc, "final_third": f3n,
        }


def scale(r: dict[str, Any]) -> dict[str, Any]:
    """Raw window -> API flow object (chaos, control, pattern, ...)."""
    avg_seq = r["avg_seq"] if r["avg_seq"] is not None else (RANGES["avg_seq"][0] + RANGES["avg_seq"][1]) / 2
    comp = {"turnovers": r["turnovers"], "duels": r["duels"], "transitions": r["transitions"],
            "long_share": r["long_share"], "avg_seq": avg_seq}
    chaos = 100 * (WEIGHTS["turnovers"] * norm(comp["turnovers"], "turnovers") + WEIGHTS["duels"] * norm(comp["duels"], "duels")
                   + WEIGHTS["transitions"] * norm(comp["transitions"], "transitions")
                   + WEIGHTS["long_share"] * norm(comp["long_share"], "long_share")
                   + WEIGHTS["avg_seq"] * (1 - norm(avg_seq, "avg_seq")))
    poss_tot = sum(r["poss_ms"]) or 1.0
    poss_share = [r["poss_ms"][k] / poss_tot for k in (0, 1)]
    f3_tot = sum(r["final_third"])
    control = []
    for k in (0, 1):
        acc = r["pass_acc"][k]
        settled = r["settled"][k] / r["n_seq"][k] if r["n_seq"][k] else 0.0
        f3 = (r["final_third"][k] + 0.5) / (f3_tot + 1)
        control.append(round(100 * (0.35 * poss_share[k] + 0.25 * (norm(acc, "pass_acc") if acc is not None else 0.5)
                                    + 0.25 * settled + 0.15 * f3)))
    tilt = (r["final_third"][0] + 0.5) / (f3_tot + 1)
    R = RULES
    # a siege needs final-third volume, not just tilt
    siege = (0 if tilt >= R["siege_tilt"] and r["final_third"][0] >= R["siege_min_passes"]
             else 1 if tilt <= 1 - R["siege_tilt"] and r["final_third"][1] >= R["siege_min_passes"] else None)
    if r["bip"] < R["stop_start_bip"]:
        pattern = "stop_start"
    elif comp["transitions"] >= R["end_to_end_transitions"] or (comp["long_share"] > R["end_to_end_long"] and comp["turnovers"] > R["end_to_end_turnovers"]):
        pattern = "end_to_end"
    elif siege is not None:
        pattern = "siege"
    elif avg_seq >= R["settled_seq"] and comp["turnovers"] <= R["settled_turnovers"]:
        pattern = "settled"
    elif r["tempo"] >= R["high_tempo"]:
        pattern = "high_tempo"
    else:
        pattern = "balanced"
    return {
        "chaos": round(chaos), "control": control,
        "comp": {k: round(v, 3) for k, v in comp.items()},
        "tempo": round(r["tempo"], 1), "bip": round(r["bip"], 3), "stops": r["stops"], "tilt": round(tilt, 3),
        "pattern": pattern, "poss_share": [round(v, 3) for v in poss_share],
        "pass_acc": [round(v, 3) if v is not None else None for v in r["pass_acc"]],
        "siege_team": siege,
    }


def flow_series(idx: FlowIndex, step_ms: int = STEP_MS) -> list[tuple[int, dict[str, Any]]]:
    """(t_ms, flow) for every step up to the end of extra time."""
    return [(t, scale(idx.raw(t))) for t in range(step_ms, idx.duration_ms + 1, step_ms)]
