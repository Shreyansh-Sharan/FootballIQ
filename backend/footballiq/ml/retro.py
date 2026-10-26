"""Retrospective cross-fit: K-fold models that may use later matches but never the match they score.

Rows carry mode = "retrospective" so they are never presented as forecasts; only strict mode is.
"""

from __future__ import annotations

import hashlib
from typing import Any

from footballiq.ml import train as T

MODE_STRICT, MODE_RETRO = "strict", "retrospective"
RETRO_NOTE = ("Retrospective cross-fit: trained on matches from before AND after this one (but never this match). "
              "An analysis aid, not a forecast that was available at kick-off.")


def assign_folds(match_ids, k: int) -> dict[str, int]:
    """Deterministic, balanced fold per match: sort by a hash of the id, then deal round-robin."""
    if k < 2:
        raise ValueError("retrospective cross-fit needs at least 2 folds")
    ids = sorted({str(m) for m in match_ids}, key=lambda m: hashlib.sha1(m.encode()).hexdigest())
    return {m: i % k for i, m in enumerate(ids)}


def held_out(folds: dict[str, int], fold: int) -> set[str]:
    return {m for m, f in folds.items() if f == fold}


def fit_bundle(shots, passes, windows, n_boot: int, monotone: dict[str, int] | None = None) -> tuple[dict[str, Any], dict[str, tuple[int, int]]]:
    """Strict-epoch model bundle from frames excluding the fold; ``windows`` must already drop unused priors.

    Returns (models, {name: (rows, matches)})."""
    models: dict[str, Any] = {}
    counts: dict[str, tuple[int, int]] = {}
    models["xg"] = T.fit_prob_model("xg", shots, "lgbm", n_boot=n_boot)
    counts["xg"] = (len(shots), shots["match_id"].nunique())
    models["xpass"] = T.fit_prob_model("xpass", passes, "lgbm", n_boot=0)
    counts["xpass"] = (len(passes), passes["match_id"].nunique())
    for target, kind in (("goal_10m", "lgbm"), ("corner_2m", "lgbm"), ("penalty_5m", "logit")):
        models[target] = T.fit_prob_model(target, windows.assign(label=windows[target]), kind, n_boot=n_boot, monotone=monotone)
        counts[target] = (len(windows), windows["match_id"].nunique())
    cols, goal_rate = T.fit_goal_rate(windows, monotone=monotone)
    models["goal_rate"] = {"features": cols, "model": goal_rate}
    counts["goal_rate"] = (len(windows), windows["match_id"].nunique())
    return models, counts
