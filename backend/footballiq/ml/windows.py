"""Match-state features and labels for the time-window forecasts, one row per (team, sample time t).

Features use events up to t and nominal period lengths; labels look at (t, t + horizon], cut at period end.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

from footballiq.schema import Match, MatchEvent

L, W = 105.0, 68.0
BOX_X, BOX_Y0, BOX_Y1 = L - 16.5, W / 2 - 20.16, W / 2 + 20.16
NOMINAL_MIN = {1: 45.0, 2: 45.0, 3: 15.0, 4: 15.0}
HORIZONS_S = {"goal_10m": 600, "corner_2m": 120, "penalty_5m": 300}
CAP_S = 1800.0
RED = ("Red Card", "Second Yellow")
OK = (None, "Complete", "Success")

FEATURES = [
    "period", "minute_in_period", "nominal_remaining_min", "phase_remaining_min", "is_knockout",
    "score_for", "score_against", "score_diff", "red_for", "red_against",
    "shots_for_10", "shots_against_10", "xg_for_10", "xg_against_10", "xg_for_total", "xg_against_total",
    "box_entries_for_5", "box_entries_against_5", "f3_entries_for_5", "f3_entries_against_5",
    "corners_for_10", "corners_against_10", "corners_for_total",
    "pass_share_5", "pass_share_10", "dribbles_box_for_10", "fouls_won_f3_for_10", "fouls_won_f3_against_10",
    "secs_since_shot_for", "secs_since_corner_for", "secs_since_goal_any",
]
# pre-match strength: constant within a match, NaN when unrated
PRIOR_FEATURES = ["elo_for", "elo_against", "elo_diff", "form_ppg_for", "form_ppg_against", "form_gd_for",
                  "form_gd_against", "rated_games_min"]


@dataclass
class _Team:
    shots: np.ndarray
    shot_xg: np.ndarray
    goals: np.ndarray
    corners: np.ndarray
    penalties: np.ndarray
    box_entries: np.ndarray
    f3_entries: np.ndarray
    passes: np.ndarray
    dribbles_box: np.ndarray
    fouls_won_f3: np.ndarray
    reds: np.ndarray


def _attack(e: MatchEvent, home_id: str, x: float | None, y: float | None):
    if x is None or y is None:
        return None
    return (x, y) if e.team_id == home_id else (L - x, W - y)


def _in_box(p) -> bool:
    return p is not None and p[0] >= BOX_X and BOX_Y0 <= p[1] <= BOX_Y1


def _team_arrays(events: list[MatchEvent], team_id: str, home_id: str, xg: dict[str, float]) -> _Team:
    acc: dict[str, list] = {k: [] for k in _Team.__dataclass_fields__}
    for e in events:
        if e.period > 4 or e.team_id != team_id:
            continue
        t = e.match_elapsed_ms
        if e.type == "Shot":
            acc["shots"].append(t)
            acc["shot_xg"].append(xg.get(e.event_id, e.provider_xg or 0.0))
            if e.subtype == "Penalty":
                acc["penalties"].append(t)
        if e.is_goal or e.is_own_goal:  # "Own Goal For" is attributed to the benefiting team
            acc["goals"].append(t)
        start = _attack(e, home_id, e.x_m, e.y_m)
        end = _attack(e, home_id, e.end_x_m, e.end_y_m)
        if e.type == "Pass":
            acc["passes"].append(t)
            if e.subtype == "Corner":
                acc["corners"].append(t)
        if e.type in ("Pass", "Carry") and e.outcome in OK and start and end:
            if _in_box(end) and not _in_box(start):
                acc["box_entries"].append(t)
            if end[0] >= 2 * L / 3 > start[0]:
                acc["f3_entries"].append(t)
        if e.type == "Dribble" and _in_box(start):
            acc["dribbles_box"].append(t)
        if e.type == "Foul Won" and start and start[0] >= 2 * L / 3:
            acc["fouls_won_f3"].append(t)
        if e.card in RED:
            acc["reds"].append(t)
    return _Team(**{k: np.asarray(v, dtype=float) for k, v in acc.items()})


def _count(a: np.ndarray, lo: float, hi: float) -> int:
    """events with lo < t <= hi"""
    return int(np.searchsorted(a, hi, side="right") - np.searchsorted(a, lo, side="right"))


def _since(a: np.ndarray, t: float) -> float:
    k = np.searchsorted(a, t, side="right")
    return CAP_S if k == 0 else min(CAP_S, (t - a[k - 1]) / 1000.0)


def sample_times(match: Match, step_s: float) -> list[tuple[int, float]]:
    out = []
    for p in match.periods:
        if p.period > 4:
            continue
        t = float(p.start_match_ms)
        while t < p.start_match_ms + p.duration_ms:
            out.append((p.period, t))
            t += step_s * 1000
    return out


def examples(match: Match, events: list[MatchEvent], xg: dict[str, float] | None = None, step_s: float = 30.0,
             times: Iterable[tuple[int, float]] | None = None, is_knockout: bool | None = None,
             priors: dict[str, dict[str, float]] | None = None) -> list[dict[str, Any]]:
    """`priors` maps team_id -> PRIOR_FEATURES (from results before the match date)."""
    xg = xg or {}
    nan_prior = {k: float("nan") for k in PRIOR_FEATURES}
    home, away = match.home.team_id, match.away.team_id
    arr = {tid: _team_arrays(events, tid, home, xg) for tid in (home, away)}
    starts = {p.period: (p.start_match_ms, p.start_match_ms + p.duration_ms) for p in match.periods}
    knock = float(is_knockout if is_knockout is not None else (match.stage or "Group Stage") != "Group Stage")
    phase_end = {1: starts.get(2, starts[1])[1], 2: starts.get(2, starts[1])[1],
                 3: starts.get(4, starts.get(3, (0, 0)))[1], 4: starts.get(4, starts.get(3, (0, 0)))[1]}
    rows = []
    for period, t in (times if times is not None else sample_times(match, step_s)):
        p0, p1 = starts[period]
        elapsed_min = (t - p0) / 60000.0
        nominal_rem = max(0.0, NOMINAL_MIN[period] - elapsed_min)
        phase_rem = nominal_rem + (NOMINAL_MIN[period + 1] if period in (1, 3) else 0.0)
        goal_times = np.sort(np.concatenate([arr[home].goals, arr[away].goals]))
        for tid, oid in ((home, away), (away, home)):
            a, o = arr[tid], arr[oid]
            w5, w10 = t - 300_000, t - 600_000
            sf, sa = _count(a.goals, -1, t), _count(o.goals, -1, t)
            pf5, pa5 = _count(a.passes, w5, t), _count(o.passes, w5, t)
            pf10, pa10 = _count(a.passes, w10, t), _count(o.passes, w10, t)
            k_t, k_o = np.searchsorted(a.shots, t, side="right"), np.searchsorted(o.shots, t, side="right")
            k10_t, k10_o = np.searchsorted(a.shots, w10, side="right"), np.searchsorted(o.shots, w10, side="right")
            f = {
                "period": float(period), "minute_in_period": elapsed_min, "nominal_remaining_min": nominal_rem,
                "phase_remaining_min": phase_rem, "is_knockout": knock,
                "score_for": float(sf), "score_against": float(sa), "score_diff": float(sf - sa),
                "red_for": float(_count(a.reds, -1, t)), "red_against": float(_count(o.reds, -1, t)),
                "shots_for_10": float(k_t - k10_t), "shots_against_10": float(k_o - k10_o),
                "xg_for_10": float(a.shot_xg[k10_t:k_t].sum()), "xg_against_10": float(o.shot_xg[k10_o:k_o].sum()),
                "xg_for_total": float(a.shot_xg[:k_t].sum()), "xg_against_total": float(o.shot_xg[:k_o].sum()),
                "box_entries_for_5": float(_count(a.box_entries, w5, t)), "box_entries_against_5": float(_count(o.box_entries, w5, t)),
                "f3_entries_for_5": float(_count(a.f3_entries, w5, t)), "f3_entries_against_5": float(_count(o.f3_entries, w5, t)),
                "corners_for_10": float(_count(a.corners, w10, t)), "corners_against_10": float(_count(o.corners, w10, t)),
                "corners_for_total": float(_count(a.corners, -1, t)),
                "pass_share_5": pf5 / (pf5 + pa5) if pf5 + pa5 else 0.5,
                "pass_share_10": pf10 / (pf10 + pa10) if pf10 + pa10 else 0.5,
                "dribbles_box_for_10": float(_count(a.dribbles_box, w10, t)),
                "fouls_won_f3_for_10": float(_count(a.fouls_won_f3, w10, t)),
                "fouls_won_f3_against_10": float(_count(o.fouls_won_f3, w10, t)),
                "secs_since_shot_for": _since(a.shots, t), "secs_since_corner_for": _since(a.corners, t),
                "secs_since_goal_any": _since(goal_times, t),
            }
            labels = {
                "goal_10m": int(_count(a.goals, t, min(t + 600_000, p1)) > 0),
                "corner_2m": int(_count(a.corners, t, min(t + 120_000, p1)) > 0),
                "penalty_5m": int(_count(a.penalties, t, min(t + 300_000, p1)) > 0),
                "goals_rest": _count(a.goals, t, phase_end[period]),
            }
            prior = {**nan_prior, **((priors or {}).get(tid) or {})}
            rows.append({"match_id": match.canonical_match_id, "t_ms": int(t), "team_id": tid, "opponent_id": oid,
                         "is_home": tid == home, **f, **prior, **labels})
    return rows


def outcome_probs(score_for: float, score_against: float, mu_for: float, mu_against: float, max_goals: int = 10):
    """P(win, draw, loss) at the end of the phase from current score + independent Poisson goal counts."""
    from math import exp, factorial

    pf = np.array([exp(-mu_for) * mu_for ** k / factorial(k) for k in range(max_goals + 1)])
    pa = np.array([exp(-mu_against) * mu_against ** k / factorial(k) for k in range(max_goals + 1)])
    joint = np.outer(pf, pa)
    diff = (score_for - score_against) + np.subtract.outer(np.arange(max_goals + 1), np.arange(max_goals + 1))
    total = joint.sum()
    return float(joint[diff > 0].sum() / total), float(joint[diff == 0].sum() / total), float(joint[diff < 0].sum() / total)
