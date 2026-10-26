# Fabric notebook source: nb_skillcorner_ingest
# Attach to Lakehouse: lh_football_intelligence
#
# SkillCorner open data (github.com/SkillCorner/opendata, credit SkillCorner): A-League Men 2024/25 with
# 10 fps broadcast tracking and dynamic events. is_detected maps to is_observed / is_extrapolated;
# replay events come from player_possession dynamic events.

# %% [parameters]
MATCH_IDS = "all"          # "all" = every match in matches.json that has data, or a comma list of ids
LAKEHOUSE_ROOT = "/lakehouse/default"

# %%
import glob
import sys

sys.path.insert(0, sorted(glob.glob("/lakehouse/default/Files/wheels/footballiq-*.whl"))[-1])

# %%
import io
import json
import time
from pathlib import Path

import httpx
import pandas as pd

from footballiq.ingest import skillcorner as SC
from footballiq.ingest import spark_io as IO

bronze = Path(LAKEHOUSE_ROOT) / "Files" / "bronze" / "skillcorner"
bronze.mkdir(parents=True, exist_ok=True)
client = httpx.Client(timeout=600, follow_redirects=True)


def get(url, path):
    if path.exists():
        return True
    for attempt in range(5):
        try:
            r = client.get(url)
            if r.status_code == 404:
                return False
            r.raise_for_status()
            if r.content.startswith(b"version https://git-lfs"):
                raise RuntimeError(f"{url} returned a Git LFS pointer, not the file")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
            return True
        except httpx.HTTPError:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


catalog = client.get(f"{SC.RAW}/matches.json").json()
ids = [m["id"] for m in catalog] if MATCH_IDS.strip().lower() == "all" else [int(x) for x in MATCH_IDS.split(",") if x.strip()]
available = []
for mid in ids:
    u = SC.urls(mid)
    if all(get(u[k], bronze / str(mid) / u[k].rsplit("/", 1)[1]) for k in ("match", "events", "tracking")):
        available.append(mid)
print(f"{len(available)} of {len(ids)} listed matches have match, events and tracking files")

# %%
summary = []
for mid in available:
    t0 = time.time()
    d = bronze / str(mid)
    meta = json.loads((d / f"{mid}_match.json").read_text())
    events_df = pd.read_csv(io.BytesIO((d / f"{mid}_dynamic_events.csv").read_bytes()), low_memory=False)
    match, events = SC.normalize(meta, events_df)
    ok, goals = IO.reconciles(match, events)
    IO.write_match(spark, match, events, SC.PROVIDER, "skillcorner")  # noqa: F821
    with open(d / f"{mid}_tracking_extrapolated.jsonl") as fh:
        fdf, pdf = IO.typed_frames(*SC.tracking_columns(fh, meta, match))
    IO.write_std(spark, fdf, "silver_tracking_frame_std", SC.PROVIDER, match.canonical_match_id)  # noqa: F821
    IO.write_std(spark, pdf, "silver_player_position_std", SC.PROVIDER, match.canonical_match_id)  # noqa: F821
    summary.append(IO.summary_row(match, fdf, pdf, SC.PROVIDER, 10.0, ok))
    print(f"{mid} {match.canonical_match_id}: {len(events)} events, {len(fdf):,} frames, observed "
          f"{summary[-1]['player_observed_pct']:.0f}% players / {summary[-1]['ball_observed_pct']:.0f}% ball, "
          f"score {'OK' if ok else 'MISMATCH ' + str(goals)} ({time.time() - t0:.0f}s)")

IO.write_summary(spark, summary, SC.PROVIDER)  # noqa: F821
print(pd.DataFrame(summary)[["match_id", "frames", "player_observed_pct", "ball_observed_pct", "score_reconciles"]].to_string())
bad = [s["match_id"] for s in summary if not s["score_reconciles"]]
if bad:
    print("score does not reconcile from dynamic events (own goals carry no timestamp in this feed):", bad)
