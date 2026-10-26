# Fabric notebook source: nb_statsbomb_ingest
# Attach to Lakehouse: lh_football_intelligence
#
# StatsBomb open data for COMPETITIONS: raw JSON to Files/bronze/statsbomb/<match_id>/, normalised into
# silver by the same footballiq package the API uses.

# %% [parameters]
MATCH_IDS = "all"           # "all" = every match of COMPETITIONS (full reload), or comma-separated StatsBomb ids
COMPETITIONS = "43/106,55/282"   # <competition_id>/<season_id>: FIFA World Cup 2022, UEFA Euro 2024
DOWNLOAD_WORKERS = 8
LAKEHOUSE_ROOT = "/lakehouse/default"

# %%
# footballiq is pure Python, so it imports straight from the wheel
import glob
import sys

sys.path.insert(0, sorted(glob.glob("/lakehouse/default/Files/wheels/footballiq-*.whl"))[-1])

# %%
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from footballiq.ingest import statsbomb as sb

bronze = Path(LAKEHOUSE_ROOT) / "Files" / "bronze"
comp_of = {}   # StatsBomb match id -> (competition_id, season_id)
for pair in COMPETITIONS.split(","):
    ci, si = (int(x) for x in pair.strip().split("/"))
    for m in httpx.get(f"{sb.BASE_URL}/matches/{ci}/{si}.json", timeout=60).json():
        comp_of[m["match_id"]] = (ci, si)
if MATCH_IDS.strip().lower() == "all":
    match_ids = sorted(comp_of)
else:
    match_ids = [int(x) for x in MATCH_IDS.split(",") if x.strip()]
print(f"{len(match_ids)} matches from {COMPETITIONS}")


def fetch(mid):
    path = sb.download_match(mid, *comp_of[mid], out_dir=bronze)
    return mid, sb.normalize_match(sb.load_bronze(mid, bronze), mid)


with ThreadPoolExecutor(DOWNLOAD_WORKERS) as ex:
    normalized = dict(ex.map(fetch, match_ids))
print("bronze written for", len(normalized), "matches;",
      sum(len(ev) for _, ev, _ in normalized.values()), "events,",
      sum(len(ff) for _, _, ff in normalized.values()), "360 snapshots")

# %%
from pyspark.sql import functions as F  # noqa: E402


def rows_df(rows):
    """DataFrame from dicts via JSON so all-null columns still get a (string) type."""
    return spark.read.json(spark.sparkContext.parallelize([json.dumps(r) for r in rows], 64))  # noqa: F821


ingest_ts = F.current_timestamp()
match_rows, event_rows, frame_rows, player_rows = [], [], [], []
for match, events, frames in normalized.values():
    row = json.loads(match.model_dump_json())
    for key in ("players", "periods", "result", "home", "away", "source_ids"):
        row[key] = json.dumps(row[key])
    row["statsbomb_match_id"] = match.source_ids["statsbomb"]
    row["provider"] = "statsbomb"
    match_rows.append(row)
    event_rows += [{**json.loads(e.model_dump_json()), "related_events": json.dumps(e.related_events),
                    "source_location": json.dumps(e.source_location)} for e in events]
    frame_rows += [{"match_id": match.canonical_match_id, "event_id": f.event_id, "match_elapsed_ms": f.match_elapsed_ms,
                    "source": f.source, "players": json.dumps([p.model_dump() for p in f.players]),
                    "visible_area": json.dumps(f.visible_area)} for f in frames]
    player_rows += [{**p.model_dump(exclude={"source_ids"}), "statsbomb_id": p.source_ids.get("statsbomb"),
                     "match_id": match.canonical_match_id, "provider": "statsbomb"} for p in match.players]

df_match = rows_df(match_rows).withColumn("ingested_at_utc", ingest_ts)
df_events = rows_df(event_rows).withColumn("ingested_at_utc", ingest_ts)
df_frames = rows_df(frame_rows).withColumn("ingested_at_utc", ingest_ts)
df_players = rows_df(player_rows)

# %%
FULL_RELOAD = MATCH_IDS.strip().lower() == "all"


def upsert(df, table, keys):
    """Full reload replaces only StatsBomb rows; a match subset is merged."""
    exists = spark.catalog.tableExists(table)  # noqa: F821
    if FULL_RELOAD and exists and "provider" in spark.table(table).columns:  # noqa: F821
        (df.write.format("delta").mode("overwrite").option("mergeSchema", "true")
           .option("replaceWhere", "provider = 'statsbomb'").saveAsTable(table))
    elif FULL_RELOAD or not exists:
        df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table)
    else:
        from delta.tables import DeltaTable
        spark.conf.set("spark.databricks.delta.schema.autoMerge.enabled", "true")  # noqa: F821
        cond = " AND ".join(f"t.{k} = s.{k}" for k in keys)
        (DeltaTable.forName(spark, table).alias("t")  # noqa: F821
            .merge(df.alias("s"), cond).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute())
    print(f"{table}: {spark.table(table).count():,} rows")  # noqa: F821


upsert(df_match, "silver_match", ["canonical_match_id"])
upsert(df_events, "silver_match_event", ["match_id", "event_id"])
upsert(df_frames, "silver_freeze_frame", ["match_id", "event_id"])
upsert(df_players, "silver_player", ["match_id", "player_id"])

# %%
# goals per match, excluding the shootout, must equal the published result
goals = {(r.match_id, r.team_id): r.goals for r in spark.sql("""
SELECT match_id, team_id, SUM(CASE WHEN (is_goal OR is_own_goal) AND NOT is_shootout THEN 1 ELSE 0 END) AS goals
FROM silver_match_event WHERE team_id IS NOT NULL GROUP BY match_id, team_id""").collect()}  # noqa: F821
bad = []
for match, _, _ in normalized.values():
    got = (goals.get((match.canonical_match_id, match.home.team_id), 0), goals.get((match.canonical_match_id, match.away.team_id), 0))
    if got != (match.result["home_score"], match.result["away_score"]):
        bad.append((match.canonical_match_id, got, match.result))
print(f"score reconciliation: {len(normalized) - len(bad)}/{len(normalized)} matches OK")
assert not bad, bad
