import json

import pyarrow as pa

from footballiq.predictions import PredictionStore


def _pred(t, target, team, p=None, value=None, period=1, horizon=600):
    return {"replay_t_ms": t, "period": period, "target_name": target, "team_id": team, "horizon_s": horizon,
            "predicted_prob": p, "prob_lo": None if p is None else p - 0.02, "prob_hi": None if p is None else p + 0.02,
            "predicted_value": value, "model_version": "v1", "explanation_ref": json.dumps([["xg_for_10", 0.31]]) if p else None}


class FakeLakehouse:
    def __init__(self):
        preds = [_pred(t, "goal_next_10m", "a", 0.1 + t / 1e6) for t in (0, 15_000, 30_000)]
        preds += [_pred(t, "win_phase", "a", 0.5 + t / 1e6) for t in (0, 15_000, 30_000)]
        preds += [_pred(t, "draw_phase", None, 0.3) for t in (0, 15_000, 30_000)]
        values = [
            {"event_id": "s1", "period": 1, "match_elapsed_ms": 10_000, "team_id": "a", "player_id": "p1", "player_name": "One",
             "type": "Shot", "xg": 0.2, "xg_lo": 0.15, "xg_hi": 0.25, "xg_statsbomb": 0.3, "is_goal": True, "xpass": None,
             "pass_completed": None, "xt_added": None, "model_version": "v1"},
            {"event_id": "p1", "period": 1, "match_elapsed_ms": 20_000, "team_id": "a", "player_id": "p1", "player_name": "One",
             "type": "Pass", "xg": None, "xg_lo": None, "xg_hi": None, "xg_statsbomb": None, "is_goal": None, "xpass": 0.8,
             "pass_completed": True, "xt_added": 0.05, "model_version": "v1"},
        ]
        self.t = {
            "gold_prediction_log": pa.Table.from_pylist(preds), "gold_event_model_values": pa.Table.from_pylist(values),
            "ml_model_registry": pa.Table.from_pylist([
                {"model_name": "xg", "model_version": v, "kind": "lgbm", "horizon_s": None, "features": '["x"]', "train_rows": 10,
                 "train_matches": 2, "train_from": "2003-07-01", "train_before": "2022-11-20", "mlflow_registered": True}
                for v in ("v0", "v1")]),
            "gold_model_evaluation": pa.Table.from_pylist([{"model_name": "xg", "model_version": "v1", "metric": "auc", "value": 0.8}]),
            "gold_model_calibration": pa.Table.from_pylist([{"model_name": "xg", "model_version": "v1", "bin": 0, "mean_pred": 0.1,
                                                              "obs_rate": 0.12, "n": 50}]),
        }

    def query(self, sql, tables):
        return self.t[next(iter(tables.values()))]


def test_latest_forecast_is_bounded_and_deterministic():
    ps = PredictionStore(FakeLakehouse())
    a = ps.latest("m", 20_000)
    assert a["feature_cutoff_ms"] == 15_000                      # grid point at or before the clock, never after
    assert a["teams"]["a"]["goal_next_10m"]["probability"] == 0.115
    assert a["teams"]["a"]["goal_next_10m"]["drivers"][0]["feature"] == "xg_for_10"
    assert a["draw_phase"]["probability"] == 0.3
    ps.latest("m", 30_000)
    assert ps.latest("m", 20_000) == a                            # rewind gives the same answer


def test_series_and_values_stop_at_clock():
    ps = PredictionStore(FakeLakehouse())
    s = ps.series("m", 15_000)
    assert [p["t_ms"] for p in s["win"]["a"]] == [0, 15_000]
    assert s["xg"]["a"]["ours"] == 0.2 and s["xg"]["a"]["statsbomb"] == 0.3
    v = ps.event_values("m", 15_000)
    assert v["teams"]["a"]["shots"] == 1 and v["teams"]["a"]["passes"] == 0  # the pass at 20 s is still in the future
    v = ps.event_values("m", 25_000)
    assert v["teams"]["a"]["xpass_pct"] == 80.0 and v["top_xt_players"][0]["xt_added"] == 0.05


def test_model_cards_use_latest_version():
    m = PredictionStore(FakeLakehouse()).models()
    assert m["model_version"] == "v1" and len(m["models"]) == 1 and m["metrics"]["xg"]["auc"] == 0.8


def test_retrospective_mode_reads_its_own_tables_and_is_labelled():
    lh = FakeLakehouse()
    retro_preds = [{**r, "predicted_prob": 0.9, "model_version": "r1-f0"} for r in lh.t["gold_prediction_log"].to_pylist()]
    lh.t["gold_prediction_log_retro"] = pa.Table.from_pylist(retro_preds)
    lh.t["gold_event_model_values_retro"] = lh.t["gold_event_model_values"]
    strict, retro = PredictionStore(lh), PredictionStore(lh, mode="retrospective")
    s, r = strict.latest("m", 20_000), retro.latest("m", 20_000)
    assert s["mode"] == "strict" and s["mode_note"] is None and s["teams"]["a"]["goal_next_10m"]["probability"] == 0.115
    assert r["mode"] == "retrospective" and "after" in r["mode_note"] and r["teams"]["a"]["goal_next_10m"]["probability"] == 0.9


def test_model_cards_never_mix_strict_and_retrospective_versions():
    lh = FakeLakehouse()
    rows = lh.t["ml_model_registry"].to_pylist()
    rows.append({**rows[0], "model_version": "v9-retro-k4", "train_before": None})
    lh.t["ml_model_registry"] = pa.Table.from_pylist([{**r, "cutoff": "retrospective" if "retro" in r["model_version"] else "2022-11-20"}
                                                       for r in rows])
    strict = PredictionStore(lh).models()
    retro = PredictionStore(lh, mode="retrospective").models()
    assert strict["model_version"] == "v1" and "v9-retro-k4" not in strict["versions"]   # newest STRICT, not the retro run
    assert retro["model_version"] == "v9-retro-k4" and retro["versions"] == ["v9-retro-k4"] and retro["mode"] == "retrospective"


def test_default_card_is_the_newest_forecast_bundle_not_a_side_experiment():
    lh = FakeLakehouse()
    rows = lh.t["ml_model_registry"].to_pylist()
    rows = [{**r, "model_name": n} for r in rows for n in ("xg", "goal_rate")]
    rows.append({**rows[0], "model_version": "v2", "model_name": "xpass_tracking_v1"})   # newer, but only an experiment
    lh.t["ml_model_registry"] = pa.Table.from_pylist(rows)
    card = PredictionStore(lh).models()
    assert card["model_version"] == "v1" and "v2" in card["versions"]
    assert PredictionStore(lh).models("v2")["model_version"] == "v2"
