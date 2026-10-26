# Fabric notebook source: nb_idsse_ingest
# Attach to Lakehouse: lh_football_intelligence
#
# IDSSE (DFL) open data: 7 Bundesliga and 2. Bundesliga 2022/23 matches, 25 Hz optical tracking with
# synchronised events (Bassek et al. 2025, CC BY 4.0, huggingface.co/datasets/pysport/idsse-data).
# Events join the shared silver tables; tracking goes to the *_std tables.
# is_observed is True only where DFL reports a coordinate.

# %% [parameters]
MATCH_IDS = "all"          # "all" or comma list of DFL ids (J03WMX, J03WN1, ...)
EVERY_NTH_FRAME = 1        # 1 = full 25 Hz
LAKEHOUSE_ROOT = "/lakehouse/default"

# %%
import glob
import subprocess
import sys

sys.path.insert(0, sorted(glob.glob("/lakehouse/default/Files/wheels/footballiq-*.whl"))[-1])
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "kloppy==3.19.1"])

# %%
import json
import time
from pathlib import Path

import httpx
import pandas as pd

from footballiq.ingest import idsse

bronze = Path(LAKEHOUSE_ROOT) / "Files" / "bronze" / "idsse"
bronze.mkdir(parents=True, exist_ok=True)
ids = list(idsse.MATCHES) if MATCH_IDS.strip().lower() == "all" else [m.strip() for m in MATCH_IDS.split(",") if m.strip()]
client = httpx.Client(timeout=600, follow_redirects=True)
for mid in ids:
    for name in idsse.file_names(mid).values():
        path = bronze / name
        if path.exists():
            continue
        for attempt in range(5):
            try:
                with client.stream("GET", f"{idsse.BASE_URL}/{name}") as r:
                    r.raise_for_status()
                    tmp = path.with_suffix(".tmp")
                    with open(tmp, "wb") as fh:
                        for chunk in r.iter_bytes(1 << 20):
                            fh.write(chunk)
                    tmp.rename(path)
                break
            except httpx.HTTPError:
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
print(f"bronze: {len(ids)} matches in Files/bronze/idsse")

# %%
from kloppy import sportec  # noqa: E402

from footballiq.ingest import spark_io as IO  # noqa: E402

summary = []
for mid in ids:
    t0 = time.time()
    f = {k: str(bronze / v) for k, v in idsse.file_names(mid).items()}
    match, events = idsse.normalize(sportec.load_event(event_data=f["events"], meta_data=f["meta"]), mid)
    ok, goals = IO.reconciles(match, events)
    IO.write_match(spark, match, events, idsse.PROVIDER, "dfl")  # noqa: F821
    tr = sportec.load_tracking(raw_data=f["tracking"], meta_data=f["meta"], only_alive=False)
    fdf, pdf = IO.typed_frames(*idsse.tracking_columns(tr, match, every=int(EVERY_NTH_FRAME)))
    del tr
    IO.write_std(spark, fdf, "silver_tracking_frame_std", idsse.PROVIDER, match.canonical_match_id)  # noqa: F821
    IO.write_std(spark, pdf, "silver_player_position_std", idsse.PROVIDER, match.canonical_match_id)  # noqa: F821
    summary.append(IO.summary_row(match, fdf, pdf, idsse.PROVIDER, 25.0 / int(EVERY_NTH_FRAME), ok))
    print(f"{mid} {match.canonical_match_id}: {len(events)} events, {len(fdf):,} frames, {len(pdf):,} positions, "
          f"score {'OK' if ok else 'MISMATCH ' + str(goals)} ({time.time() - t0:.0f}s)")
    del fdf, pdf

IO.write_summary(spark, summary, idsse.PROVIDER)  # noqa: F821
print(pd.DataFrame(summary)[["match_id", "competition", "frames", "coverage_mean", "ball_observed_pct", "score_reconciles"]].to_string())
assert all(s["score_reconciles"] for s in summary), "a score did not reconcile from events"
