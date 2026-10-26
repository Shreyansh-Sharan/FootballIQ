"""Training and evaluation helpers shared by the Fabric notebooks (nb_ml_train, nb_ml_score) and tests.

Splits are grouped by match; calibration is out-of-fold, and bootstrap members give an uncertainty band.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

from footballiq.ml import features as feat


# --------------------------------------------------------------------------- datasets

def action_rows(match_id: str, raw_events: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    shots, passes = [], []
    for ev in raw_events:
        if feat.is_model_shot(ev):
            shots.append({"match_id": match_id, "event_id": ev["id"], "label": feat.shot_label(ev),
                          "provider_xg": (ev.get("shot") or {}).get("statsbomb_xg"), **feat.shot_features(ev)})
        elif feat.is_model_pass(ev):
            passes.append({"match_id": match_id, "event_id": ev["id"], "label": feat.pass_label(ev), **feat.pass_features(ev)})
    return shots, passes


def feature_columns(rows_or_df, exclude: Iterable[str] = ()) -> list[str]:
    meta = {"match_id", "sb_match_id", "event_id", "label", "provider_xg", "competition", "t_ms", "team_id", "opponent_id", "is_home",
            "goal_10m", "corner_2m", "penalty_5m", "goals_rest", *exclude}
    cols = rows_or_df.columns if hasattr(rows_or_df, "columns") else rows_or_df[0].keys()
    return [c for c in cols if c not in meta]


# --------------------------------------------------------------------------- models

LGBM_PARAMS = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=40, subsample=0.8,
                   subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1)


def _mono(cols: list[str], monotone: dict[str, int] | None) -> dict:
    """LightGBM monotone constraints by column position, e.g. {"elo_diff": 1}."""
    return {"monotone_constraints": [monotone.get(c, 0) for c in cols]} if monotone else {}


def _base(kind: str, seed: int = 0, extra: dict | None = None):
    if kind == "lgbm":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(random_state=seed, **LGBM_PARAMS, **(extra or {}))
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.3, max_iter=2000))


def _calibrated(kind: str, X, y, groups, seed: int = 0, folds: int = 5, extra: dict | None = None):
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import GroupKFold
    method = "isotonic" if kind == "lgbm" and y.sum() >= 200 else "sigmoid"
    folds = max(2, min(folds, len(np.unique(groups))))
    splits = list(GroupKFold(n_splits=folds).split(X, y, groups))
    return CalibratedClassifierCV(estimator=_base(kind, seed, extra), method=method, cv=splits).fit(X, y)


@dataclass
class ProbModel:
    """Calibrated classifier + bootstrap members (by match) for an uncertainty band."""
    name: str
    kind: str
    features: list[str]
    main: Any
    members: list[Any] = field(default_factory=list)

    def predict(self, X) -> np.ndarray:
        return self.main.predict_proba(X[self.features])[:, 1]

    def band(self, X, lo: float = 10, hi: float = 90) -> tuple[np.ndarray, np.ndarray]:
        if not self.members:
            p = self.predict(X)
            return p, p
        P = np.vstack([m.predict_proba(X[self.features])[:, 1] for m in self.members])
        return np.percentile(P, lo, axis=0), np.percentile(P, hi, axis=0)

    def drivers(self, X, top: int = 3) -> list[list[tuple[str, float]]]:
        """Top contributions (log-odds, uncalibrated base model) per row; empty for non-tree models."""
        cal = self.main.calibrated_classifiers_[0]
        est = getattr(cal, "estimator", None) or getattr(cal, "base_estimator", None)
        if not hasattr(est, "booster_"):
            return [[] for _ in range(len(X))]
        contrib = est.booster_.predict(X[self.features].to_numpy(dtype=float), pred_contrib=True)[:, :-1]
        out = []
        for row in contrib:
            idx = np.argsort(-np.abs(row))[:top]
            out.append([(self.features[i], round(float(row[i]), 3)) for i in idx])
        return out


def fit_prob_model(name: str, df, kind: str = "lgbm", n_boot: int = 8, seed: int = 0,
                   monotone: dict[str, int] | None = None) -> ProbModel:
    cols = feature_columns(df)
    X, y, g = df[cols], df["label"].to_numpy(), df["match_id"].to_numpy()
    extra = _mono(cols, monotone) if kind == "lgbm" else None
    main = _calibrated(kind, X, y, g, seed, extra=extra)
    rng = np.random.default_rng(seed)
    matches = np.unique(g)
    members = []
    for b in range(n_boot):
        pick = rng.choice(matches, size=len(matches), replace=True)
        idx = np.concatenate([np.flatnonzero(g == m) for m in pick])
        # copies keep their match id, so GroupKFold keeps them in one fold
        members.append(_calibrated(kind, X.iloc[idx], y[idx], g[idx], seed + b + 1, extra=extra))
    return ProbModel(name, kind, cols, main, members)


def oof_predictions(df, kind: str = "lgbm", folds: int = 5, seed: int = 0) -> np.ndarray:
    """Grouped out-of-fold calibrated predictions (used as honest xG inputs for the window models)."""
    from sklearn.model_selection import GroupKFold
    cols = feature_columns(df)
    X, y, g = df[cols], df["label"].to_numpy(), df["match_id"].to_numpy()
    out = np.zeros(len(df))
    for tr, te in GroupKFold(n_splits=folds).split(X, y, g):
        m = _calibrated(kind, X.iloc[tr], y[tr], g[tr], seed, folds=4)
        out[te] = m.predict_proba(X.iloc[te])[:, 1]
    return out


def fit_goal_rate(df, seed: int = 0, monotone: dict[str, int] | None = None):
    """Poisson regression (LightGBM) for goals a team scores before the end of the current phase."""
    from lightgbm import LGBMRegressor
    cols = feature_columns(df)
    params = {**LGBM_PARAMS, "n_estimators": 300, **_mono(cols, monotone)}
    return cols, LGBMRegressor(objective="poisson", random_state=seed, **params).fit(df[cols], df["goals_rest"])


# --------------------------------------------------------------------------- evaluation

def evaluate(y: np.ndarray, p: np.ndarray, bins: int = 10) -> tuple[dict[str, float], list[dict[str, float]]]:
    from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = 0.0, 1.0
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, bins - 1)
    rel, ece = [], 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            rel.append({"bin": b, "mean_pred": float(p[m].mean()), "obs_rate": float(y[m].mean()), "n": int(m.sum())})
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
    two = len(np.unique(y)) > 1
    base = float(y.mean())
    base_ll = -(base * math.log(max(base, 1e-9)) + (1 - base) * math.log(max(1 - base, 1e-9))) if 0 < base < 1 else float("nan")
    metrics = {
        "n": float(len(y)), "positives": float(y.sum()), "base_rate": base,
        "log_loss": float(log_loss(y, p, labels=[0, 1])), "log_loss_base_rate": base_ll,
        "brier": float(brier_score_loss(y, p)), "brier_base_rate": base * (1 - base),
        "auc": float(roc_auc_score(y, p)) if two else float("nan"),
        "pr_auc": float(average_precision_score(y, p)) if two else float("nan"),
        "ece": float(ece), "mean_pred": float(p.mean()),
    }
    return metrics, rel
