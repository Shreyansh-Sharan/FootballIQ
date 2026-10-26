# Fabric notebook source: nb_ml_xpass_tracking
# Attach to Lakehouse: lh_football_intelligence
#
# Pass-completion model that sees defender positions, separate from the event-based xPass in nb_ml_train.
# Each PFF World Cup 2022 pass or cross is taken at its nearest tracking frame with its intended target, so
# incomplete passes are described by where they were aimed. An event-only model on the same passes
# measures what tracking adds.

# %% [parameters]
TEST_FROM = "2022-12-03"     # round of 16 onwards is held out
N_BOOT = 3
MODEL_VERSION = ""

# %%
import glob
import sys

sys.path.insert(0, sorted(glob.glob("/lakehouse/default/Files/wheels/footballiq-*.whl"))[-1])
try:
    import mlflow
    mlflow.autolog(disable=True)
except ImportError:
    pass

# %%
import datetime as dt
import json
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.sql import Window
from pyspark.sql import functions as F

from footballiq.ml import train as T
from footballiq.ml import xpass_tracking as XPT

ROOT = Path("/lakehouse/default/Files")
VERSION = MODEL_VERSION or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M")
OUT = ROOT / "models" / "xpass_tracking_v1" / VERSION
OUT.mkdir(parents=True, exist_ok=True)

ids = spark.table("silver_pff_match").select("match_id", "pff_game_id")  # noqa: F821
roster = spark.table("silver_pff_roster").select("pff_game_id", F.col("pff_player_id").cast("long").alias("pid"), "jersey_num")  # noqa: F821
ev = (spark.table("silver_pff_event")  # noqa: F821
      .where(F.col("pe_possessionEventType").isin("PA", "CR"))
      .withColumn("outcome", F.when(F.col("pe_possessionEventType") == "CR", F.col("pe_crossOutcomeType")).otherwise(F.col("pe_passOutcomeType")))
      .where(F.col("outcome").isNotNull() & (F.col("outcome") != "U") & F.col("pe_targetPlayerId").isNotNull())
      .select("pff_game_id", "game_event_id", "possession_event_id", F.col("event_time_s"), F.col("ge_homeTeam").alias("home_team"),
              F.col("pe_passerPlayerId").alias("passer"), F.col("pe_targetPlayerId").alias("target"),
              (F.col("outcome") == "C").cast("int").alias("label"), F.col("pe_ballHeightType").alias("height"),
              F.col("pe_bodyType").alias("body"), F.col("ge_setpieceType").alias("setpiece"),
              (F.col("pe_possessionEventType") == "CR").alias("is_cross"))
      .join(ids, "pff_game_id")
      .join(roster.withColumnRenamed("pid", "passer").withColumnRenamed("jersey_num", "passer_jersey"), ["pff_game_id", "passer"], "left")
      .join(roster.withColumnRenamed("pid", "target").withColumnRenamed("jersey_num", "target_jersey"), ["pff_game_id", "target"], "left"))

# nearest frame within 50 ms; PFF events and tracking share the video clock
fr = spark.table("silver_tracking_frame").select("pff_game_id", "frame_num", "video_time_ms")  # noqa: F821
cand = (ev.withColumn("t_ms", (F.col("event_time_s") * 1000).cast("long"))
        .join(fr, ["pff_game_id"])
        .where(F.abs(F.col("video_time_ms") - F.col("t_ms")) <= 50)
        .withColumn("rk", F.row_number().over(Window.partitionBy("pff_game_id", "possession_event_id")
                                              .orderBy(F.abs(F.col("video_time_ms") - F.col("t_ms")), "frame_num")))
        .where("rk = 1").drop("rk"))
passes = cand.toPandas()
print(f"passes with a tracking frame: {len(passes):,} (of {ev.count():,} PFF passes/crosses with an outcome and target)")

pos = (spark.table("silver_player_position")  # noqa: F821
       .join(cand.select("pff_game_id", "frame_num").distinct(), ["pff_game_id", "frame_num"])
       .select("pff_game_id", "frame_num", "side", "jersey_num", F.coalesce("x_smooth_m", "x_m").alias("x"),
               F.coalesce("y_smooth_m", "y_m").alias("y"), "speed_mps",
               F.when(F.col("visibility") == "VISIBLE", F.lit(True)).when(F.col("visibility") == "ESTIMATED", F.lit(False)).alias("is_observed"))
       .toPandas())
frames = {k: g.to_dict("records") for k, g in pos.groupby(["pff_game_id", "frame_num"])}

# %%
recs = [{"pff_game_id": int(r.pff_game_id), "frame_num": int(r.frame_num), "event_id": f"pff-{r.pff_game_id}-{r.possession_event_id}",
         "team_id": "home" if r.home_team else "away", "side": "home" if r.home_team else "away", "passer_jersey": r.passer_jersey,
         "target_jersey": r.target_jersey, "height": r.height, "body": r.body, "setpiece": r.setpiece, "is_cross": bool(r.is_cross),
         "label": int(r.label), "match_id": r.match_id, "match_date": r.match_id[:10]} for r in passes.itertuples(index=False)]
data = pd.DataFrame(XPT.build_rows(recs, frames))
print(f"feature rows: {len(data):,}; completion rate {data['label'].mean():.3f}")

meta_cols = ["match_id", "match_date", "event_id", "pff_game_id", "team_id", "label"]
event_df = data[meta_cols + XPT.EVENT_FEATURES]
track_df = data[meta_cols + XPT.EVENT_FEATURES + XPT.TRACKING_FEATURES]
is_test = data["match_date"] >= TEST_FROM
print(f"train passes {(~is_test).sum():,} ({data.loc[~is_test, 'match_id'].nunique()} matches) | "
      f"test passes {is_test.sum():,} ({data.loc[is_test, 'match_id'].nunique()} matches, from {TEST_FROM})")

# %%
evaluation, calibration, results = [], [], {}
SPLIT = f"test_wc2022_from_{TEST_FROM}"


def fit_eval(name, df):
    t0 = time.time()
    tr, te = df[~is_test].drop(columns=["match_date"]), df[is_test].drop(columns=["match_date"])
    model = T.fit_prob_model(name, tr, "lgbm", n_boot=N_BOOT)
    p_test = model.predict(te)
    oof = T.oof_predictions(tr, "lgbm")
    for subset, mask in (("all", np.ones(len(te), bool)),
                         ("observed_passer_and_target", (te["passer_observed"] == 1).to_numpy() & (te["target_observed"] == 1).to_numpy()
                          if "passer_observed" in te else np.ones(len(te), bool))):
        if mask.sum() < 50:
            continue
        m, rel = T.evaluate(te["label"].to_numpy()[mask], p_test[mask])
        tag = name if subset == "all" else f"{name}@{subset}"
        evaluation.extend({"model_name": tag, "model_version": VERSION, "split": SPLIT, "cutoff": TEST_FROM, "metric": k, "value": float(v)}
                          for k, v in m.items())
        if subset == "all":
            calibration.extend({"model_name": name, "model_version": VERSION, **r} for r in rel)
        print(tag, {k: round(v, 4) for k, v in m.items()})
    print(f"{name} trained ({time.time() - t0:.0f}s)")
    return model, p_test, oof


m_event, p_event, oof_event = fit_eval("xpass_event_only_pff", event_df)
m_track, p_track, oof_track = fit_eval("xpass_tracking_v1", track_df)

# %%
# per-pass values: held-out for test matches, out-of-fold for training matches
out = data[["match_id", "event_id", "pff_game_id", "label"]].copy()
out["xpass_tracking"] = np.nan
out["xpass_event_only"] = np.nan
out.loc[is_test, "xpass_tracking"], out.loc[is_test, "xpass_event_only"] = p_track, p_event
out.loc[~is_test, "xpass_tracking"], out.loc[~is_test, "xpass_event_only"] = oof_track, oof_event
out["prediction_mode"] = np.where(is_test, "chronological_holdout", "out_of_fold")
out["model_version"] = VERSION
lane = data[["event_id", "lane_within_1_5m", "press_nearest_m", "target_nearest_opp_m", "passer_observed", "target_observed"]]
out = out.merge(lane, on="event_id")

(OUT / "models.pkl").write_bytes(pickle.dumps({"version": VERSION, "xpass_tracking_v1": m_track, "xpass_event_only_pff": m_event,
                                              "event_features": XPT.EVENT_FEATURES, "tracking_features": XPT.TRACKING_FEATURES}))
card = {"version": VERSION, "test_from": TEST_FROM, "train_passes": int((~is_test).sum()), "test_passes": int(is_test.sum()),
        "source": "PFF FC World Cup 2022 broadcast tracking + events", "target": "PFF intended target player (no end-location leakage)"}
(OUT / "model_card.json").write_text(json.dumps(card, indent=2))

for df, table, mode in ((out, "gold_pass_xpass", "overwrite"), (pd.DataFrame(evaluation), "gold_model_evaluation", "append"),
                        (pd.DataFrame(calibration), "gold_model_calibration", "append")):
    w = spark.createDataFrame(df).write.format("delta").mode(mode).option("mergeSchema", "true")  # noqa: F821
    (w.option("overwriteSchema", "true") if mode == "overwrite" else w).saveAsTable(table)
    print(f"{table}: {'+' if mode == 'append' else ''}{len(df):,} rows")
reg = pd.DataFrame([{"model_name": n, "model_version": VERSION, "kind": "lgbm", "horizon_s": float("nan"), "features": json.dumps(f),
                     "train_rows": int((~is_test).sum()), "train_matches": int(data.loc[~is_test, "match_id"].nunique()),
                     "train_from": "2022-11-20", "train_before": TEST_FROM, "cutoff": TEST_FROM, "test_competitions": "43_106 knockouts",
                     "priors": "none", "test_metrics": "{}", "artifact_path": f"Files/models/xpass_tracking_v1/{VERSION}/models.pkl",
                     "mlflow_registered": False, "trained_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
                    for n, f in (("xpass_tracking_v1", XPT.EVENT_FEATURES + XPT.TRACKING_FEATURES), ("xpass_event_only_pff", XPT.EVENT_FEATURES))])
spark.createDataFrame(reg).write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable("ml_model_registry")  # noqa: F821
