"""Model outputs from Fabric gold tables, bounded by the replay clock (latest row at or before at_ms).

mode="retrospective" reads the *_retro cross-fit tables, and every response says so.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Any

import numpy as np

from footballiq.fabric_source import FabricLakehouse, sql_str
from footballiq.ml.retro import MODE_RETRO, MODE_STRICT, RETRO_NOTE

TEAM_TARGETS = ("goal_next_10m", "corner_next_2m", "penalty_next_5m", "win_phase", "expected_goals_rest")
LABELS = {
    "goal_next_10m": "Goal in the next 10′", "corner_next_2m": "Corner in the next 2′",
    "penalty_next_5m": "Penalty in the next 5′", "win_phase": "Win (end of phase)", "draw_phase": "Draw (end of phase)",
    "expected_goals_rest": "Expected goals before the end of the phase",
}


def _is_retro(row: dict[str, Any]) -> bool:
    return row.get("mode") == MODE_RETRO or row.get("cutoff") == MODE_RETRO


class PredictionStore:
    def __init__(self, lakehouse: FabricLakehouse, max_cached: int = 6, mode: str = MODE_STRICT):
        if mode not in (MODE_STRICT, MODE_RETRO):
            raise ValueError(f"unknown prediction mode {mode!r}")
        self.lh = lakehouse
        self.mode = mode
        self.suffix = "_retro" if mode == MODE_RETRO else ""
        self.max_cached = max_cached
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._models: dict[str, Any] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ loading
    def _load(self, match_id: str) -> dict[str, Any]:
        with self._lock:
            if match_id in self._cache:
                self._cache.move_to_end(match_id)
                return self._cache[match_id]
        mid = sql_str(match_id)
        preds = self.lh.query(
            "select * from t where match_id = {m} order by replay_t_ms".format(m=mid), {"t": f"gold_prediction_log{self.suffix}"}).to_pylist()
        values = self.lh.query(
            "select event_id, period, match_elapsed_ms, team_id, player_id, player_name, type, xg, xg_lo, xg_hi, xg_statsbomb, "
            f"is_goal, xpass, pass_completed, xt_added, model_version from t where match_id = {mid} order by match_elapsed_ms",
            {"t": f"gold_event_model_values{self.suffix}"}).to_pylist()
        series: dict[tuple[str, str | None], dict[str, Any]] = {}
        for r in preds:
            s = series.setdefault((r["target_name"], r["team_id"]), {"t": [], "rows": []})
            s["t"].append(r["replay_t_ms"])
            s["rows"].append(r)
        for s in series.values():
            s["t"] = np.asarray(s["t"], dtype=np.int64)
        try:  # pre-match strength: prior features of the first grid point
            feats = self.lh.query(f"select team_id, t_ms, features_json from t where match_id = {mid} and t_ms = "
                                  f"(select min(t_ms) from t where match_id = {mid})", {"t": f"gold_prediction_features{self.suffix}"}).to_pylist()
        except Exception:  # noqa: BLE001
            feats = []
        keys = ("elo_for", "elo_against", "elo_diff", "form_ppg_for", "form_gd_for", "rated_games_min")
        prematch = {r["team_id"]: {k: json.loads(r["features_json"]).get(k) for k in keys} for r in feats}
        data = {"series": series, "values": values, "value_t": np.asarray([v["match_elapsed_ms"] for v in values], dtype=np.int64),
                "version": preds[0]["model_version"] if preds else None, "prematch": prematch,
                "cutoff": preds[0].get("model_cutoff") if preds else None}
        with self._lock:
            self._cache[match_id] = data
            while len(self._cache) > self.max_cached:
                self._cache.popitem(last=False)
        return data

    def cached(self, match_id: str) -> bool:
        with self._lock:
            return match_id in self._cache

    def warm(self, match_id: str) -> None:
        """Load a match in the background; failures only mean the stream carries no predictions."""
        def run():
            try:
                self._load(match_id)
            except Exception:  # noqa: BLE001 - optional enrichment of the real-time path
                pass
        threading.Thread(target=run, daemon=True).start()

    def stream_payload(self, match_id: str, at_ms: int) -> dict[str, Any] | None:
        """Compact match.predictions message; None until the match is cached (never blocks the replay loop)."""
        if not self.cached(match_id):
            return None
        d = self.latest(match_id, at_ms)
        if d["feature_cutoff_ms"] is None:
            return None
        rows = [{"team_id": team, "target": target, "p": f["probability"], "lo": f["low"], "hi": f["high"], "value": f["value"]}
                for team, fs in d["teams"].items() for target, f in fs.items()]
        if d["draw_phase"]:
            rows.append({"team_id": None, "target": "draw_phase", "p": d["draw_phase"]["probability"], "lo": None, "hi": None, "value": None})
        return {"model_version": d["model_version"], "feature_cutoff_ms": d["feature_cutoff_ms"], "phase": d["phase"], "rows": rows}

    @staticmethod
    def _at(series: dict[str, Any], at_ms: int) -> dict[str, Any] | None:
        k = int(np.searchsorted(series["t"], at_ms, side="right"))
        return series["rows"][k - 1] if k else None

    # ------------------------------------------------------------------ forecasts
    def latest(self, match_id: str, at_ms: int) -> dict[str, Any]:
        d = self._load(match_id)
        teams: dict[str, dict[str, Any]] = {}
        cutoff, draw, period, phase_s = None, None, None, None
        for (target, team), s in d["series"].items():
            r = self._at(s, at_ms)
            if r is None:
                continue
            cutoff = r["replay_t_ms"] if cutoff is None else max(cutoff, r["replay_t_ms"])
            period = r["period"]
            item = {"label": LABELS.get(target, target), "probability": r["predicted_prob"], "low": r["prob_lo"], "high": r["prob_hi"],
                    "value": r["predicted_value"], "horizon_s": r["horizon_s"],
                    "drivers": [{"feature": f, "contribution": c} for f, c in json.loads(r["explanation_ref"] or "[]")]}
            if team is None:
                draw = item
                phase_s = r["horizon_s"]
            else:
                teams.setdefault(team, {})[target] = item
        return {"match_id": match_id, "at_ms": at_ms, "feature_cutoff_ms": cutoff, "model_version": d["version"],
                "model_cutoff": d.get("cutoff"), "mode": self.mode, "mode_note": RETRO_NOTE if self.mode == MODE_RETRO else None,
                "prematch": d.get("prematch", {}),
                "phase": None if period is None else ("regulation" if period <= 2 else "extra time"),
                "phase_remaining_s": phase_s, "teams": teams, "draw_phase": draw,
                "notes": ["Probabilities use only events at or before the feature cutoff.",
                          "Bands are the 10th-90th percentile of bootstrap models (resampled by match).",
                          "Drivers are LightGBM log-odds contributions; positive raises the forecast."]}

    def series(self, match_id: str, at_ms: int, step_ms: int = 60_000) -> dict[str, Any]:
        """Win/draw probability and cumulative xG (ours vs StatsBomb) up to at_ms - never beyond."""
        d = self._load(match_id)
        out: dict[str, Any] = {"match_id": match_id, "at_ms": at_ms, "win": {}, "draw": [], "xg": {}}
        for (target, team), s in d["series"].items():
            if target not in ("win_phase", "draw_phase"):
                continue
            k = int(np.searchsorted(s["t"], at_ms, side="right"))
            pts, last = [], -step_ms
            for r in s["rows"][:k]:
                if r["replay_t_ms"] - last >= step_ms or r is s["rows"][k - 1]:
                    pts.append({"t_ms": r["replay_t_ms"], "p": r["predicted_prob"]})
                    last = r["replay_t_ms"]
            if target == "draw_phase":
                out["draw"] = pts
            else:
                out["win"][team] = pts
        k = int(np.searchsorted(d["value_t"], at_ms, side="right"))
        for v in d["values"][:k]:
            if v["xg"] is None:
                continue
            s = out["xg"].setdefault(v["team_id"], {"ours": 0.0, "statsbomb": 0.0, "points": []})
            s["ours"] += v["xg"]
            s["statsbomb"] += v["xg_statsbomb"] or 0.0
            s["points"].append({"t_ms": v["match_elapsed_ms"], "ours": round(s["ours"], 3), "statsbomb": round(s["statsbomb"], 3),
                                "goal": bool(v["is_goal"])})
        return out

    def event_values(self, match_id: str, at_ms: int) -> dict[str, Any]:
        d = self._load(match_id)
        k = int(np.searchsorted(d["value_t"], at_ms, side="right"))
        teams: dict[str, dict[str, Any]] = {}
        players: dict[tuple[str, str], dict[str, Any]] = {}
        shots = []
        for v in d["values"][:k]:
            t = teams.setdefault(v["team_id"], {"xg": 0.0, "xg_statsbomb": 0.0, "shots": 0, "goals": 0, "passes": 0,
                                                "passes_completed": 0, "xpass_sum": 0.0, "xt_added": 0.0})
            if v["xg"] is not None:
                t["xg"] += v["xg"]
                t["xg_statsbomb"] += v["xg_statsbomb"] or 0.0
                t["shots"] += 1
                t["goals"] += bool(v["is_goal"])
                shots.append({k2: v[k2] for k2 in ("event_id", "match_elapsed_ms", "team_id", "player_name", "xg", "xg_lo", "xg_hi",
                                                    "xg_statsbomb", "is_goal")})
            if v["xpass"] is not None:
                t["passes"] += 1
                t["passes_completed"] += bool(v["pass_completed"])
                t["xpass_sum"] += v["xpass"]
            if v["xt_added"] is not None:
                t["xt_added"] += v["xt_added"]
                if v["player_id"]:
                    p = players.setdefault((v["team_id"], v["player_id"]), {"team_id": v["team_id"], "player_id": v["player_id"],
                                                                            "name": v["player_name"], "xt_added": 0.0, "actions": 0})
                    p["xt_added"] += v["xt_added"]
                    p["actions"] += 1
        for t in teams.values():
            t["pass_completion_pct"] = round(100 * t["passes_completed"] / t["passes"], 1) if t["passes"] else None
            t["xpass_pct"] = round(100 * t["xpass_sum"] / t["passes"], 1) if t["passes"] else None
            t["completion_above_expected_pct"] = (round(t["pass_completion_pct"] - t["xpass_pct"], 1)
                                                  if t["passes"] else None)
            for key in ("xg", "xg_statsbomb", "xt_added", "xpass_sum"):
                t[key] = round(t[key], 3)
        top = sorted(players.values(), key=lambda p: -p["xt_added"])[:8]
        for p in top:
            p["xt_added"] = round(p["xt_added"], 3)
        return {"match_id": match_id, "at_ms": at_ms, "model_version": d["version"], "teams": teams, "shots": shots[-40:],
                "top_xt_players": top}

    def xt_by_event(self, match_id: str, at_ms: int) -> dict[str, float]:
        """Threat added (xT, our model) per event up to at_ms, for player impact."""
        d = self._load(match_id)
        k = int(np.searchsorted(d["value_t"], at_ms, side="right"))
        return {v["event_id"]: v["xt_added"] for v in d["values"][:k] if v["xt_added"] is not None}

    def xpass_by_event(self, match_id: str) -> dict[str, float]:
        """xPass per pass event; callers read each value only at its own event time."""
        return {v["event_id"]: v["xpass"] for v in self._load(match_id)["values"] if v["xpass"] is not None}

    def xg_by_event(self, match_id: str, at_ms: int) -> tuple[dict[str, dict[str, Any]], str | None]:
        """Our xG (+ band) per shot up to at_ms, and the model version that scored it."""
        d = self._load(match_id)
        k = int(np.searchsorted(d["value_t"], at_ms, side="right"))
        return ({v["event_id"]: {"xg": v["xg"], "xg_lo": v["xg_lo"], "xg_hi": v["xg_hi"]} for v in d["values"][:k] if v["xg"] is not None},
                d["version"])

    # ------------------------------------------------------------------ model cards
    def models(self, version: str | None = None) -> dict[str, Any]:
        """Model card for one epoch version (default: the most recently trained)."""
        cache = self._models if isinstance(self._models, dict) and "_by_version" in self._models else {"_by_version": {}}
        self._models = cache
        if version in cache["_by_version"]:
            return cache["_by_version"][version]
        # strict and retrospective cards never mix
        reg_all = [r for r in self.lh.query("select * from t", {"t": "ml_model_registry"}).to_pylist()
                   if _is_retro(r) == (self.mode == MODE_RETRO)]
        versions = sorted({r["model_version"] for r in reg_all})
        # default: newest full bundle (has goal_rate); side experiments stay selectable by version
        bundles = sorted({r["model_version"] for r in reg_all if r["model_name"] == "goal_rate"}) or versions
        version = version if version in versions else (bundles[-1] if bundles else None)
        if version in cache["_by_version"]:
            return cache["_by_version"][version]
        reg = [r for r in reg_all if r["model_version"] == version]
        ev = self.lh.query(f"select * from t where model_version = {sql_str(version or '')}", {"t": "gold_model_evaluation"}).to_pylist()
        cal = self.lh.query(f"select * from t where model_version = {sql_str(version or '')}", {"t": "gold_model_calibration"}).to_pylist()
        metrics: dict[str, dict[str, float]] = {}
        for r in ev:
            metrics.setdefault(r["model_name"], {})[r["metric"]] = r["value"]
        curves: dict[str, list[dict[str, float]]] = {}
        for r in sorted(cal, key=lambda r: r["bin"]):
            curves.setdefault(r["model_name"], []).append({"mean_pred": r["mean_pred"], "obs_rate": r["obs_rate"], "n": r["n"]})
        first = reg[0] if reg else {}
        tests = first.get("test_competitions") or "43_106"
        card = {
            "model_version": version, "versions": versions, "cutoff": first.get("cutoff") or first.get("train_before"),
            "priors": first.get("priors") or "none", "test_competitions": tests.split(","),
            "models": [{"name": r["model_name"], "kind": r["kind"], "horizon_s": r["horizon_s"], "train_rows": r["train_rows"],
                        "train_matches": r["train_matches"], "train_window": [r["train_from"], r["train_before"]],
                        "features": json.loads(r["features"]), "mlflow_registered": r["mlflow_registered"]} for r in reg],
            "mode": self.mode, "mode_note": RETRO_NOTE if self.mode == MODE_RETRO else None,
            "test": (f"out-of-fold over {tests}: each match scored by the fold model that never saw it (folds trained on "
                     "matches before and after it)") if self.mode == MODE_RETRO else
                    f"held-out competitions {tests} (all played after the cutoff, never used in training)",
            "metrics": metrics, "calibration": curves,
        }
        cache["_by_version"][version] = card
        return card
