# Fabric notebook source: nb_ml_train
# Attach to Lakehouse: lh_football_intelligence
#
# Trains one chronological epoch: models learn only from men's matches before CUTOFF and are tested on
# TEST_COMPETITIONS (on or after it), so each is shown only as a forecast for later matches.
# Splits and calibration are grouped by match; pre-match Elo uses only earlier results.
# MODE = "retrospective" cross-fits TEST_COMPETITIONS in K_FOLDS; each fold trains on every other match,
# including later ones, and never enters the strict epoch index.

# %% [parameters]
TRAIN_FROM = "2003-07-01"
CUTOFF = "2022-11-20"                # train on matches strictly before this date
TEST_COMPETITIONS = "43_106"         # comma list of <competition_id>_<season_id> played on/after CUTOFF
PRIORS = "elo_diff"                  # pre-match features kept for the window models: none | elo_diff | all
COMPARE_BASELINE = "true"            # also log window models trained without priors
N_BOOT = 5
WINDOW_STEP_S = 60
WORKERS = 16
MODEL_VERSION = ""            # empty = UTC timestamp
REGISTER = "true"
MODE = "strict"                      # strict | retrospective
K_FOLDS = 4                          # retrospective only
TRAIN_BEFORE = ""                    # retrospective only: optional upper date bound; empty = all data

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
import datetime as dt  # noqa: I001
import gzip
import json
import math
import pickle
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from footballiq.ingest import statsbomb as sb
from footballiq.ml import features as feat
from footballiq.ml import pipeline as PL
from footballiq.ml import train as T
from footballiq.ml import windows as WN
from footballiq.ml import xt as XT

ROOT = Path("/lakehouse/default/Files")
TRAIN_RAW = ROOT / "bronze" / "statsbomb_train"
TEST_KEYS = [k.strip() for k in TEST_COMPETITIONS.split(",") if k.strip()]
from footballiq.ml import retro as R

RETRO = MODE == R.MODE_RETRO
N_BOOT, K_FOLDS, WINDOW_STEP_S, WORKERS = int(N_BOOT), int(K_FOLDS), int(WINDOW_STEP_S), int(WORKERS)  # overrides may arrive as strings
assert MODE in (R.MODE_STRICT, R.MODE_RETRO), f"unknown MODE {MODE!r}"
VERSION = MODEL_VERSION or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M") + (
    f"-retro-k{K_FOLDS}" if RETRO else "-c" + CUTOFF.replace("-", ""))
OUT = ROOT / "models" / VERSION
OUT.mkdir(parents=True, exist_ok=True)
print("model version", VERSION)


def pmap(fn, items, workers=8):
    """Map over a driver process pool, or serially if the pool cannot start."""
    try:
        with ProcessPoolExecutor(workers) as ex:
            yield from ex.map(fn, items, chunksize=8)
    except (OSError, RuntimeError) as exc:  # e.g. fork not permitted
        print(f"process pool unavailable ({exc!r}); running serially")
        yield from map(fn, items)

# %%
# catalogue: men's matches in [TRAIN_FROM, CUTOFF) for training, plus the test competitions
client = httpx.Client(timeout=60, follow_redirects=True)


def get(url: str, ok_404: bool = False) -> httpx.Response | None:
    """GET with retries (GitHub raw drops connections under parallel load)."""
    for attempt in range(6):
        try:
            r = client.get(url)
            if r.status_code == 404 and ok_404:
                return None
            r.raise_for_status()
            return r
        except httpx.HTTPError:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)


comps = [c for c in get(f"{sb.BASE_URL}/competitions.json").json() if c["competition_gender"] == "male"]


def season_matches(c):
    key = f'{c["competition_id"]}_{c["season_id"]}'
    d = TRAIN_RAW / key
    d.mkdir(parents=True, exist_ok=True)
    path = d / "matches.json"
    if not path.exists():
        path.write_bytes(get(f'{sb.BASE_URL}/matches/{c["competition_id"]}/{c["season_id"]}.json').content)
    return key, json.loads(path.read_text())


with ThreadPoolExecutor(WORKERS) as ex:
    seasons = list(ex.map(season_matches, comps))
TRAIN_RAW.mkdir(parents=True, exist_ok=True)
(TRAIN_RAW / "competitions.json").write_text(json.dumps(comps))
international = {f'{c["competition_id"]}_{c["season_id"]}': bool(c["competition_international"]) for c in comps}
if RETRO:  # no cutoff; targets are cross-fitted
    train_items = [(key, m["match_id"]) for key, ms in seasons for m in ms
                   if TRAIN_FROM <= m["match_date"] and (not TRAIN_BEFORE or m["match_date"] < TRAIN_BEFORE) and key not in TEST_KEYS]
    test_items = [(key, m["match_id"]) for key, ms in seasons for m in ms if key in TEST_KEYS]
    print(f"retrospective cross-fit, {K_FOLDS} folds: {len(test_items)} target matches ({', '.join(TEST_KEYS)}) + "
          f"{len(train_items)} other matches (all dates, incl. after the targets)")
else:
    train_items = [(key, m["match_id"]) for key, ms in seasons for m in ms
                   if TRAIN_FROM <= m["match_date"] < CUTOFF and key not in TEST_KEYS]
    test_items = [(key, m["match_id"]) for key, ms in seasons for m in ms if key in TEST_KEYS]
    early = [mid for key, ms in seasons for m in ms if key in TEST_KEYS and m["match_date"] < CUTOFF for mid in [m["match_id"]]]
    assert not early, f"{len(early)} test matches are dated before the cutoff - pick a later CUTOFF"
    print(f"epoch cutoff {CUTOFF}: training matches {len(train_items)} from {len({k for k, _ in train_items})} competition-seasons; "
          f"test matches {len(test_items)} ({', '.join(TEST_KEYS)})")


def fetch(item):
    key, mid = item
    for kind in ("events", "lineups"):
        path = TRAIN_RAW / key / f"{mid}_{kind}.json.gz"
        if path.exists():
            continue
        r = get(f"{sb.BASE_URL}/{kind}/{mid}.json")
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(r.content))
        tmp.rename(path)


t0 = time.time()
with ThreadPoolExecutor(WORKERS) as ex:
    list(ex.map(fetch, train_items + test_items))
print(f"raw events cached in Files/bronze/statsbomb_train ({time.time() - t0:.0f}s)")

refs = [PL.MatchRef(split, key, mid, str(TRAIN_RAW / key / f"{mid}_events.json.gz"),
                    str(TRAIN_RAW / key / f"{mid}_lineups.json.gz"), str(TRAIN_RAW / key / "matches.json"))
        for split, items in (("train", train_items), ("test", test_items)) for key, mid in items]

# %%
# pre-match strength: Elo and form from results strictly before each match date
from footballiq.ml import strength as ST  # noqa: E402

RESULTS = ROOT / "bronze" / "results"
(RESULTS / "openfootball").mkdir(parents=True, exist_ok=True)
if not (RESULTS / "international_results.csv").exists():
    (RESULTS / "international_results.csv").write_bytes(
        get("https://raw.githubusercontent.com/martj42/international_results/master/results.csv").content)


def fetch_of(item):
    season, league = item
    path = RESULTS / "openfootball" / f"{season}_{league}.json"
    if path.exists():
        return 1
    r = get(f"https://raw.githubusercontent.com/openfootball/football.json/master/{season}/{league}.json", ok_404=True)
    if r is None:
        return 0
    path.write_bytes(r.content)
    return 1


with ThreadPoolExecutor(WORKERS) as ex:
    n_of = sum(ex.map(fetch_of, [(f"{y}-{str(y + 1)[2:]}", lg) for y in range(2010, 2025) for lg in ("en.1", "es.1", "de.1", "it.1", "fr.1")]))
ratings = ST.build(RESULTS, [(international[key], m) for key, ms in seasons for m in ms])
print(f"ratings: {len(ratings['nations'].hist)} national teams, {len(ratings['clubs'].hist)} clubs ({n_of} OpenFootball seasons)")
priors = {r.match_id: PL.priors_for(r, ratings["nations" if international[r.competition] else "clubs"]) for r in refs}
rated = sum(all(v["rated_games_min"] >= 10 for v in p.values()) for p in priors.values())
print(f"matches with both teams rated (>= 10 prior games): {rated}/{len(priors)}")
strength_rows = ST.history_rows(ratings["nations"]) + ST.history_rows(ratings["clubs"])

# %%
# pass 1: shot and pass features, xT counts
t0 = time.time()
shots, passes, xt_counts = [], [], None
for ref, s, p, c in pmap(PL.extract_actions, refs):
    for r in s + p:
        r["split"] = ref.split
    shots += s
    passes += p
    if c is not None:
        xt_counts = c if xt_counts is None else {k: xt_counts[k] + c[k] for k in c}
shots, passes = pd.DataFrame(shots), pd.DataFrame(passes)
xt_grid = XT.solve(xt_counts)
print(f"shots {len(shots):,}  passes {len(passes):,}  ({time.time() - t0:.0f}s)")

# %%
def split(df):
    return df[df["split"] == "train"].drop(columns="split"), df[df["split"] == "test"].drop(columns="split")


evaluation, calibration, models, registry = [], [], {}, []
SPLIT = "retro_oof_" + "+".join(TEST_KEYS) if RETRO else "test_" + "+".join(TEST_KEYS)
CUTOFF_LABEL = R.MODE_RETRO if RETRO else CUTOFF


def record(name, kind, y, p, extra=None):
    m, rel = T.evaluate(y, p)
    evaluation.extend({"model_name": name, "model_version": VERSION, "split": SPLIT, "cutoff": CUTOFF_LABEL, "metric": k, "value": float(v)}
                      for k, v in m.items())
    calibration.extend({"model_name": name, "model_version": VERSION, **r} for r in rel)
    print(name, {k: round(v, 4) for k, v in m.items()})
    return m


if not RETRO:
    t0 = time.time()
    tr, te = split(shots)
    models["xg"] = T.fit_prob_model("xg", tr, "lgbm", n_boot=N_BOOT)
    xg_test = models["xg"].predict(te)
    metrics = {"xg": record("xg", "lgbm", te["label"].to_numpy(), xg_test)}
    metrics["xg_statsbomb"] = record("xg_statsbomb", "provider", te["label"].to_numpy(), te["provider_xg"].fillna(0).to_numpy())
    xg_oof = T.oof_predictions(tr, "lgbm")
    xg_map = {**dict(zip(tr["event_id"], xg_oof)), **dict(zip(te["event_id"], xg_test))}
    counts = {"xg": (len(tr), tr["match_id"].nunique())}
    print(f"xG trained ({time.time() - t0:.0f}s)")

    t0 = time.time()
    tr, te = split(passes)
    models["xpass"] = T.fit_prob_model("xpass", tr, "lgbm", n_boot=0)
    metrics["xpass"] = record("xpass", "lgbm", te["label"].to_numpy(), models["xpass"].predict(te))
    counts["xpass"] = (len(tr), tr["match_id"].nunique())
    del passes, tr, te
    print(f"xPass trained ({time.time() - t0:.0f}s)")

else:  # retrospective: window features use out-of-fold xG over all shots
    xg_map = dict(zip(shots["event_id"], T.oof_predictions(shots.drop(columns="split"), "lgbm")))
    print(f"out-of-fold xG for {len(xg_map):,} shots")

# %%
# pass 2: window examples; training matches use out-of-fold xG
t0 = time.time()
by_match = {}
for eid, mid in zip(shots["event_id"], shots["match_id"]):
    by_match.setdefault(mid, {})[eid] = xg_map[eid]
rows = []
for ref, rs in pmap(PL.extract_windows, [(r, by_match.get(str(r.match_id), {}), WINDOW_STEP_S, priors[r.match_id]) for r in refs]):
    for r in rs:
        r["split"] = ref.split
    rows += rs
win = pd.DataFrame(rows)
del rows
print(f"window examples {len(win):,} ({time.time() - t0:.0f}s)")

# %%
# Priors are constant within a match, so a tree model can use them to memorise training matches:
# keep only PRIORS, and make elo_diff monotone (a stronger team never gets a lower goal rate).
horizon = {"goal_10m": 600, "corner_2m": 120, "penalty_5m": 300}
keep = {"none": [], "elo_diff": ["elo_diff"], "all": WN.PRIOR_FEATURES}[PRIORS]
mono = {"elo_diff": 1} if "elo_diff" in keep else None


def win_probability(te, mu):
    """3-way outcome at the end of the phase (regulation for periods 1-2, extra time for 3-4)."""
    te = te.assign(mu=mu)
    ll, br = [], []
    for (mid, t), g in te.groupby(["match_id", "t_ms"]):
        if len(g) != 2:
            continue
        h, a = g[g["is_home"]].iloc[0], g[~g["is_home"]].iloc[0]
        p = np.array(WN.outcome_probs(h["score_for"], h["score_against"], h["mu"], a["mu"]))
        fh, fa = h["score_for"] + h["goals_rest"], a["score_for"] + a["goals_rest"]
        o = np.eye(3)[0 if fh > fa else 1 if fh == fa else 2]
        ll.append(-math.log(max(float(p @ o), 1e-9)))
        br.append(float(((p - o) ** 2).sum()))
    return {"n": float(len(ll)), "log_loss": float(np.mean(ll)), "log_loss_uniform": math.log(3), "brier_multiclass": float(np.mean(br))}


def record_wp(name, wp):
    evaluation.extend({"model_name": name, "model_version": VERSION, "split": SPLIT, "cutoff": CUTOFF, "metric": k, "value": v}
                      for k, v in wp.items())
    print(name, {k: round(v, 4) for k, v in wp.items()})
    return wp


if not RETRO:
    tr_w, te_w = split(win.drop(columns=[c for c in WN.PRIOR_FEATURES if c not in keep]))
    base_tr, base_te = split(win.drop(columns=WN.PRIOR_FEATURES))
    for target, kind in (("goal_10m", "lgbm"), ("corner_2m", "lgbm"), ("penalty_5m", "logit")):
        t0 = time.time()
        models[target] = T.fit_prob_model(target, tr_w.assign(label=tr_w[target]), kind, n_boot=N_BOOT, monotone=mono)
        metrics[target] = record(target, kind, te_w[target].to_numpy(), models[target].predict(te_w.assign(label=te_w[target])))
        counts[target] = (len(tr_w), tr_w["match_id"].nunique())
        if keep and str(COMPARE_BASELINE).lower() == "true":
            b = T.fit_prob_model(target, base_tr.assign(label=base_tr[target]), kind, n_boot=0)
            metrics[f"{target}@no_priors"] = record(f"{target}@no_priors", kind, base_te[target].to_numpy(),
                                                    b.predict(base_te.assign(label=base_te[target])))
        print(f"{target} trained ({time.time() - t0:.0f}s)")

    cols, goal_rate = T.fit_goal_rate(tr_w, monotone=mono)
    models["goal_rate"] = {"features": cols, "model": goal_rate}
    counts["goal_rate"] = (len(tr_w), tr_w["match_id"].nunique())
    metrics["goal_rate"] = record_wp("win_probability", win_probability(te_w, goal_rate.predict(te_w[cols])))
    if keep and str(COMPARE_BASELINE).lower() == "true":
        bcols, bgr = T.fit_goal_rate(base_tr)
        metrics["goal_rate@no_priors"] = record_wp("win_probability@no_priors", win_probability(base_te, bgr.predict(base_te[bcols])))

# %%
# persist artefacts, model card, MLflow runs and registry tables
if not RETRO:
    import lightgbm
    import sklearn

    bundle = {"version": VERSION, "xt_grid": xt_grid, "feature_version": feat.FEATURE_VERSION, **models}
    (OUT / "models.pkl").write_bytes(pickle.dumps(bundle))
    card = {
        "version": VERSION, "trained_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "train_window": [TRAIN_FROM, CUTOFF], "cutoff": CUTOFF, "train_matches": len(train_items),
        "test_competitions": TEST_KEYS, "test_matches": len(test_items), "priors": PRIORS, "priors_kept": keep,
        "strength_sources": ["martj42/international_results (CC0)", "openfootball/football.json", "StatsBomb open data results"],
        "feature_version": feat.FEATURE_VERSION, "window_step_s": WINDOW_STEP_S, "bootstrap_members": N_BOOT,
        "libraries": {"lightgbm": lightgbm.__version__, "scikit-learn": sklearn.__version__, "numpy": np.__version__},
        "models": {k: {"rows": counts[k][0], "matches": counts[k][1], "test_metrics": metrics.get(k)} for k in counts},
        "benchmark": {"xg_statsbomb": metrics["xg_statsbomb"]},
    }
    (OUT / "model_card.json").write_text(json.dumps(card, indent=2, default=float))
    (ROOT / "models" / "LATEST").write_text(VERSION)
    # nb_ml_score picks, per match, the latest epoch with cutoff <= match date
    index_path = ROOT / "models" / "index.json"
    index = [e for e in (json.loads(index_path.read_text()) if index_path.exists() else []) if e["cutoff"] != CUTOFF]
    index.append({"version": VERSION, "cutoff": CUTOFF, "test_competitions": TEST_KEYS, "priors": PRIORS})
    index_path.write_text(json.dumps(sorted(index, key=lambda e: e["cutoff"]), indent=2))
    print(f"saved Files/models/{VERSION}/models.pkl")

    registered = {}
    if str(REGISTER).lower() == "true":
        try:
            import mlflow
            import mlflow.sklearn
            mlflow.set_experiment("exp_footballiq_models")
            for name in ("xg", "xpass", "goal_10m", "corner_2m", "penalty_5m", "goal_rate"):
                est = models[name]["model"] if name == "goal_rate" else models[name].main
                with mlflow.start_run(run_name=f"{name}-{VERSION}"):
                    mlflow.log_params({"model_version": VERSION, "cutoff": CUTOFF, "priors": PRIORS, "train_matches": counts[name][1],
                                       "train_rows": counts[name][0], "kind": "poisson" if name == "goal_rate" else models[name].kind})
                    mlflow.log_metrics({k: v for k, v in (metrics.get(name) or {}).items() if isinstance(v, float) and math.isfinite(v)})
                    mlflow.log_dict(card, "model_card.json")
                    mlflow.sklearn.log_model(est, "model", registered_model_name=f"fiq_{name}")
                registered[name] = True
            print("MLflow: registered", sorted(registered))
        except Exception as exc:  # artefacts above are the source of truth; registry is a convenience
            print(f"MLflow registration failed: {exc!r}")

    reg_rows = [{
        "model_name": name, "model_version": VERSION,
        "kind": "poisson" if name == "goal_rate" else models[name].kind,
        "horizon_s": float(horizon[name]) if name in horizon else None, "features": json.dumps(models[name]["features"] if name == "goal_rate" else models[name].features),
        "train_rows": counts[name][0], "train_matches": counts[name][1], "train_from": TRAIN_FROM, "train_before": CUTOFF,
        "cutoff": CUTOFF, "test_competitions": ",".join(TEST_KEYS), "priors": PRIORS,
        "test_metrics": json.dumps(metrics.get(name), default=float), "artifact_path": f"Files/models/{VERSION}/models.pkl",
        "mlflow_registered": bool(registered.get(name)), "trained_at_utc": card["trained_at_utc"],
    } for name in counts]
    for df, table in ((pd.DataFrame(reg_rows), "ml_model_registry"), (pd.DataFrame(evaluation), "gold_model_evaluation"),
                      (pd.DataFrame(calibration), "gold_model_calibration")):
        spark.createDataFrame(df).write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(table)  # noqa: F821
        print(f"{table}: +{len(df)} rows")


# %%
# Retrospective cross-fit: each target match is scored only by the fold bundle that never saw it.
# Nothing here enters the strict epoch index or the MLflow registry.
if RETRO:
    import lightgbm
    import sklearn

    folds = R.assign_folds([str(r.match_id) for r in refs if r.split == "test"], K_FOLDS)
    shots_all, passes_all = shots.drop(columns="split"), passes.drop(columns="split")
    win_all = win.drop(columns=[c for c in WN.PRIOR_FEATURES if c not in keep] + ["split"])
    oof = {k: ([], []) for k in ("xg", "xg_statsbomb", "xpass", "goal_10m", "corner_2m", "penalty_5m")}
    oof_wp, fold_counts = [], {}
    for k in range(K_FOLDS):
        t0 = time.time()
        hold = R.held_out(folds, k)
        # shot/pass match_id is the StatsBomb id; window rows hold it in sb_match_id
        out_ = {"s": shots_all["match_id"].astype(str).isin(hold), "p": passes_all["match_id"].astype(str).isin(hold),
                "w": win_all["sb_match_id"].astype(str).isin(hold)}
        m_k, c_k = R.fit_bundle(shots_all[~out_["s"]], passes_all[~out_["p"]], win_all[~out_["w"]], N_BOOT, mono)
        te_s, te_p, te_w = shots_all[out_["s"]], passes_all[out_["p"]], win_all[out_["w"]]
        for name, y, pred in (("xg", te_s["label"], m_k["xg"].predict(te_s)),
                              ("xg_statsbomb", te_s["label"], te_s["provider_xg"].fillna(0).to_numpy()),
                              ("xpass", te_p["label"], m_k["xpass"].predict(te_p))):
            oof[name][0].append(y.to_numpy())
            oof[name][1].append(pred)
        for target in ("goal_10m", "corner_2m", "penalty_5m"):
            oof[target][0].append(te_w[target].to_numpy())
            oof[target][1].append(m_k[target].predict(te_w.assign(label=te_w[target])))
        oof_wp.append(te_w.assign(mu=m_k["goal_rate"]["model"].predict(te_w[m_k["goal_rate"]["features"]])))
        bundle = {"version": VERSION, "mode": R.MODE_RETRO, "fold": k, "held_out": sorted(hold), "xt_grid": xt_grid,
                  "feature_version": feat.FEATURE_VERSION, **m_k}
        (OUT / f"fold{k}.pkl").write_bytes(pickle.dumps(bundle))
        fold_counts[k] = {name: {"rows": c[0], "matches": c[1]} for name, c in c_k.items()}
        print(f"fold {k}: {len(hold)} held-out matches, trained on {c_k['goal_10m'][1]} matches ({time.time() - t0:.0f}s)")

    metrics = {}
    for name, (ys, ps) in oof.items():
        metrics[name] = record(name, "provider" if name == "xg_statsbomb" else "lgbm", np.concatenate(ys), np.concatenate(ps))
    metrics["goal_rate"] = record_wp("win_probability", win_probability(pd.concat(oof_wp), pd.concat(oof_wp)["mu"].to_numpy()))

    trained_at = dt.datetime.now(dt.timezone.utc).isoformat()
    card = {
        "version": VERSION, "mode": R.MODE_RETRO, "note": R.RETRO_NOTE, "trained_at_utc": trained_at,
        "train_window": [TRAIN_FROM, TRAIN_BEFORE or "latest"], "k_folds": K_FOLDS, "target_competitions": TEST_KEYS,
        "target_matches": len(folds), "other_matches": len(train_items), "priors": PRIORS, "priors_kept": keep,
        "feature_version": feat.FEATURE_VERSION, "bootstrap_members": N_BOOT, "folds": fold_counts,
        "libraries": {"lightgbm": lightgbm.__version__, "scikit-learn": sklearn.__version__, "numpy": np.__version__},
        "oof_metrics": metrics,
    }
    (OUT / "model_card.json").write_text(json.dumps(card, indent=2, default=float))
    (ROOT / "models" / "retro.json").write_text(json.dumps(
        {"version": VERSION, "k_folds": K_FOLDS, "competitions": TEST_KEYS, "folds": folds, "note": R.RETRO_NOTE,
         "trained_at_utc": trained_at}, indent=2))
    reg_rows = [{
        "model_name": name, "model_version": VERSION, "kind": "poisson" if name == "goal_rate" else "lgbm",
        "horizon_s": float(horizon[name]) if name in horizon else None, "features": json.dumps([]),
        "train_rows": int(np.mean([fold_counts[k][name]["rows"] for k in fold_counts])),
        "train_matches": int(np.mean([fold_counts[k][name]["matches"] for k in fold_counts])),
        "train_from": TRAIN_FROM, "train_before": TRAIN_BEFORE or None, "cutoff": R.MODE_RETRO,
        "test_competitions": ",".join(TEST_KEYS), "priors": PRIORS, "test_metrics": json.dumps(metrics.get(name), default=float),
        "artifact_path": f"Files/models/{VERSION}/fold*.pkl", "mlflow_registered": False, "trained_at_utc": trained_at,
        "mode": R.MODE_RETRO,
    } for name in ("xg", "xpass", "goal_10m", "corner_2m", "penalty_5m", "goal_rate")]
    for df, table in ((pd.DataFrame(reg_rows), "ml_model_registry"), (pd.DataFrame(evaluation), "gold_model_evaluation"),
                      (pd.DataFrame(calibration), "gold_model_calibration")):
        spark.createDataFrame(df).write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(table)  # noqa: F821
        print(f"{table}: +{len(df)} rows")
    print(f"saved Files/models/{VERSION}/fold0..{K_FOLDS - 1}.pkl and Files/models/retro.json")

# %%
# team strength history, both modes
spark.createDataFrame(pd.DataFrame(strength_rows)).write.format("delta").mode("overwrite") \
    .option("overwriteSchema", "true").saveAsTable("gold_team_strength")  # noqa: F821
print(f"gold_team_strength: {len(strength_rows):,} rows")
