# Fabric notebook source: nb_ml_score
# Attach to Lakehouse: lh_football_intelligence
#
# Batch scoring. Each match uses the latest nb_ml_train epoch whose cutoff is on or before its date, so no
# forecast comes from a model that saw later football. Pre-match Elo/form use only earlier results.
# Predictions are precomputed every STEP_S seconds so seeks and rewinds show the same numbers.

# %% [parameters]
STEP_S = 15
EXTRA_COMPETITIONS = ""   # extra <competition_id>_<season_id> keys; must be after an epoch cutoff
MODE = "strict"           # "strict": chronological epochs; "retrospective": out-of-fold bundles -> *_retro tables

# %%
import glob
import sys

sys.path.insert(0, sorted(glob.glob("/lakehouse/default/Files/wheels/footballiq-*.whl"))[-1])

# Fabric's default MLflow autologging would log every internal fit to an experiment at the workspace root.
try:
    import mlflow
    mlflow.autolog(disable=True)
except ImportError:
    pass

# %%
import hashlib
import json
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd

from footballiq.ingest import statsbomb as sb
from footballiq.ml import features as feat
from footballiq.ml import train as T
from footballiq.ml import windows as WN
from footballiq.ml import xt as XT

from footballiq.ml import strength as ST

ROOT = Path("/lakehouse/default/Files")
TRAIN_RAW = ROOT / "bronze" / "statsbomb_train"
index_path = ROOT / "models" / "index.json"
RETRO = MODE == "retrospective"
assert MODE in ("strict", "retrospective"), f"unknown MODE {MODE!r}"
if RETRO:
    RETRO_INDEX = json.loads((ROOT / "models" / "retro.json").read_text())
    FOLD_BUNDLES = {k: pickle.loads((ROOT / "models" / RETRO_INDEX["version"] / f"fold{k}.pkl").read_bytes())
                    for k in range(RETRO_INDEX["k_folds"])}
    EPOCHS, BUNDLES = [], {}
    print(f"retrospective cross-fit {RETRO_INDEX['version']}: {len(RETRO_INDEX['folds'])} matches in {RETRO_INDEX['k_folds']} folds")
else:
    EPOCHS = json.loads(index_path.read_text()) if index_path.exists() else \
        [{"version": (ROOT / "models" / "LATEST").read_text().strip(), "cutoff": "2022-11-20", "test_competitions": ["43_106"]}]
    BUNDLES = {e["version"]: pickle.loads((ROOT / "models" / e["version"] / "models.pkl").read_bytes()) for e in EPOCHS}
    print("epochs:", [(e["cutoff"], e["version"]) for e in EPOCHS])

comps = json.loads((TRAIN_RAW / "competitions.json").read_text()) if (TRAIN_RAW / "competitions.json").exists() else None
seasons = {d.name: json.loads((d / "matches.json").read_text()) for d in TRAIN_RAW.iterdir() if (d / "matches.json").exists()}
INTERNATIONAL = {f'{c["competition_id"]}_{c["season_id"]}': bool(c["competition_international"]) for c in (comps or [])}


def is_international(key):
    return INTERNATIONAL.get(key, int(key.split("_")[0]) in (43, 55, 223, 1267, 1470))


ratings = ST.build(ROOT / "bronze" / "results", [(is_international(k), m) for k, ms in seasons.items() for m in ms])
keys = sorted(RETRO_INDEX["competitions"]) if RETRO else \
    sorted({k for e in EPOCHS for k in e["test_competitions"]} | {k.strip() for k in EXTRA_COMPETITIONS.split(",") if k.strip()})


def epoch_for(date):
    ok = [e for e in EPOCHS if e["cutoff"] <= date]
    return max(ok, key=lambda e: e["cutoff"]) if ok else None


def model_for(meta):
    """(version, bundle, cutoff label) for a match, or None; retrospective uses the fold that held it out."""
    if RETRO:
        k = RETRO_INDEX["folds"].get(str(meta["match_id"]))
        return None if k is None else (f'{RETRO_INDEX["version"]}-f{k}', FOLD_BUNDLES[k], "retrospective")
    e = epoch_for(meta["match_date"])
    return None if e is None else (e["version"], BUNDLES[e["version"]], e["cutoff"])

TARGETS = (("goal_10m", "goal_next_10m", 600), ("corner_2m", "corner_next_2m", 120), ("penalty_5m", "penalty_next_5m", 300))


def pid(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:20]


def r4(v):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), 4)

# %%
event_rows, pred_rows, feat_rows = [], [], []
t0 = time.time()
import gzip  # noqa: E402

todo = [(k, m) for k in keys for m in seasons.get(k, [])]
skipped = []
for key, meta in todo:
    chosen = model_for(meta)
    ev_path, lu_path = TRAIN_RAW / key / f'{meta["match_id"]}_events.json.gz', TRAIN_RAW / key / f'{meta["match_id"]}_lineups.json.gz'
    if chosen is None or not ev_path.exists():
        skipped.append((key, meta["match_id"], "no model for this match" if chosen is None else "raw events missing"))
        continue
    VERSION, B, CUT = chosen
    raw = {"matches": seasons[key], "events": json.loads(gzip.decompress(ev_path.read_bytes())),
           "lineups": json.loads(gzip.decompress(lu_path.read_bytes())), "three_sixty": []}
    match, events, _ = sb.normalize_match(raw, meta["match_id"])
    mid = match.canonical_match_id
    pool = ratings["nations" if is_international(key) else "clubs"]
    h_name, a_name = meta["home_team"]["home_team_name"], meta["away_team"]["away_team_name"]
    priors = {match.home.team_id: ST.prior_features(pool, h_name, a_name, meta["match_date"]),
              match.away.team_id: ST.prior_features(pool, a_name, h_name, meta["match_date"])}
    by_id = {e.event_id: e for e in events}

    # per-event values
    shots, passes = T.action_rows(mid, raw["events"])
    xg = {}
    if shots:
        S = pd.DataFrame(shots)
        p, (lo, hi) = B["xg"].predict(S), B["xg"].band(S)
        xg = {e: (float(a), float(b), float(c)) for e, a, b, c in zip(S["event_id"], p, lo, hi)}
    xp = {}
    if passes:
        P = pd.DataFrame(passes)
        xp = dict(zip(P["event_id"], B["xpass"].predict(P)))
    for ev in raw["events"]:
        e = by_id.get(ev["id"])
        if e is None or e.period > 4:
            continue
        x, xpv, xt = xg.get(ev["id"]), xp.get(ev["id"]), XT.added(B["xt_grid"], ev)
        if x is None and xpv is None and xt is None:
            continue
        event_rows.append({
            "match_id": mid, "event_id": e.event_id, "period": e.period, "match_elapsed_ms": e.match_elapsed_ms,
            "team_id": e.team_id, "player_id": e.player_id, "player_name": e.player_name, "type": e.type,
            "xg": r4(x[0]) if x else None, "xg_lo": r4(x[1]) if x else None, "xg_hi": r4(x[2]) if x else None,
            "xg_statsbomb": r4(e.provider_xg) if x else None, "is_goal": bool(e.is_goal) if x else None,
            "xpass": r4(xpv), "pass_completed": bool(feat.pass_label(ev)) if xpv is not None else None,
            "xt_start": r4(xt[0]) if xt else None, "xt_end": r4(xt[1]) if xt else None, "xt_added": r4(xt[2]) if xt else None,
            "model_version": VERSION, "model_cutoff": CUT, "competition": key,
        })

    # forecasts on the fixed time grid
    W = pd.DataFrame(WN.examples(match, events, {k: v[0] for k, v in xg.items()}, step_s=STEP_S, priors=priors))
    cols = T.feature_columns(W)
    for key, target, horizon in TARGETS:
        m = B[key]
        p, (lo, hi), drv = m.predict(W), m.band(W), m.drivers(W)
        for i, row in enumerate(W.itertuples(index=False)):
            pred_rows.append({
                "prediction_id": pid(mid, row.t_ms, target, row.team_id, VERSION), "match_id": mid,
                "replay_t_ms": int(row.t_ms), "feature_cutoff_ms": int(row.t_ms), "period": int(row.period),
                "target_name": target, "team_id": row.team_id, "horizon_s": horizon,
                "predicted_prob": r4(p[i]), "prob_lo": r4(lo[i]), "prob_hi": r4(hi[i]), "predicted_value": None,
                "model_version": VERSION, "model_cutoff": CUT, "explanation_ref": json.dumps(drv[i]),
            })
    gr = B["goal_rate"]
    W["mu"] = gr["model"].predict(W[gr["features"]])
    for t, g in W.groupby("t_ms"):
        if len(g) != 2:
            continue
        h, a = g[g["is_home"]].iloc[0], g[~g["is_home"]].iloc[0]
        win, draw, loss = WN.outcome_probs(h["score_for"], h["score_against"], h["mu"], a["mu"])
        horizon = int(round(h["phase_remaining_min"] * 60))
        for team, target, prob, value in ((h["team_id"], "win_phase", win, None), (a["team_id"], "win_phase", loss, None),
                                          (None, "draw_phase", draw, None),
                                          (h["team_id"], "expected_goals_rest", None, h["mu"]), (a["team_id"], "expected_goals_rest", None, a["mu"])):
            pred_rows.append({
                "prediction_id": pid(mid, t, target, team, VERSION), "match_id": mid, "replay_t_ms": int(t), "feature_cutoff_ms": int(t),
                "period": int(h["period"]), "target_name": target, "team_id": team, "horizon_s": horizon,
                "predicted_prob": r4(prob), "prob_lo": None, "prob_hi": None, "predicted_value": r4(value),
                "model_version": VERSION, "model_cutoff": CUT, "explanation_ref": None,
            })
    for row in W.to_dict("records"):
        feat_rows.append({"match_id": mid, "t_ms": int(row["t_ms"]), "team_id": row["team_id"], "model_version": VERSION,
                          "features_json": json.dumps({c: r4(row[c]) for c in cols})})
for sk in skipped[:10]:
    print("skipped", sk)
print(f"scored {len({r['match_id'] for r in event_rows})} matches: {len(event_rows):,} events, "
      f"{len(pred_rows):,} predictions ({time.time() - t0:.0f}s)")

# %%
from pyspark.sql import functions as F  # noqa: E402


def write(rows, table):
    df = spark.createDataFrame(pd.DataFrame(rows))  # noqa: F821
    (df.withColumn("scored_at_utc", F.current_timestamp()).write.format("delta").mode("overwrite")
       .option("overwriteSchema", "true").saveAsTable(table))
    print(f"{table}: {spark.table(table).count():,} rows")  # noqa: F821


SUFFIX = "_retro" if RETRO else ""   # retrospective output never overwrites the strict forecast tables
write(event_rows, f"gold_event_model_values{SUFFIX}")
write(pred_rows, f"gold_prediction_log{SUFFIX}")
write(feat_rows, f"gold_prediction_features{SUFFIX}")
