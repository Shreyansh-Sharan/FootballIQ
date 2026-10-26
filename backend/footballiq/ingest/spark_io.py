"""Spark helpers for the provider ingest notebooks.

Canonical tables are merged by key so providers never overwrite each other; explicit schemas keep all-NULL columns typed.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from footballiq import spatial as SP
from footballiq.schema import Match, MatchEvent


def _types():
    from pyspark.sql import types as T
    s, l, d, b = T.StringType(), T.LongType(), T.DoubleType(), T.BooleanType()
    frame = [("source_provider", s), ("tracking_method", s), ("match_id", s), ("period", l), ("frame_num", l),
             ("match_elapsed_ms", l), ("ball_x_m", d), ("ball_y_m", d), ("ball_z_m", d), ("ball_is_observed", b),
             ("ball_is_extrapolated", b), ("ball_alive", b), ("players_on_pitch", l), ("players_observed", l), ("coverage_score", d)]
    pos = [("source_provider", s), ("tracking_method", s), ("match_id", s), ("period", l), ("frame_num", l),
           ("match_elapsed_ms", l), ("team_id", s), ("side", s), ("jersey_num", s), ("player_id", s), ("x_m", d), ("y_m", d),
           ("speed_mps", d), ("is_observed", b), ("is_extrapolated", b), ("confidence", s)]
    assert [c for c, _ in frame] == SP.FRAME_COLUMNS and [c for c, _ in pos] == SP.POSITION_COLUMNS
    return {"silver_tracking_frame_std": T.StructType([T.StructField(c, t) for c, t in frame]),
            "silver_player_position_std": T.StructType([T.StructField(c, t) for c, t in pos])}


def typed_frames(fr: dict[str, Any], po: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Object columns from the provider parsers -> typed pandas frames (strings stay Python objects)."""
    fdf, pdf = pd.DataFrame(fr), pd.DataFrame(po)
    for c in ("ball_x_m", "ball_y_m", "ball_z_m", "coverage_score"):
        fdf[c] = pd.to_numeric(fdf[c], errors="coerce")
    for c in ("period", "frame_num", "match_elapsed_ms", "players_on_pitch", "players_observed"):
        fdf[c] = fdf[c].astype("int64")
    for c in ("ball_is_observed", "ball_is_extrapolated", "ball_alive"):
        fdf[c] = fdf[c].astype("boolean")
    for c in ("x_m", "y_m", "speed_mps"):
        pdf[c] = pd.to_numeric(pdf[c], errors="coerce")
    for c in ("period", "frame_num", "match_elapsed_ms"):
        pdf[c] = pdf[c].astype("int64")
    for c in ("is_observed", "is_extrapolated"):
        pdf[c] = pdf[c].astype("boolean")
    return fdf, pdf


def rows_df(spark, rows: list[dict]):
    return spark.read.json(spark.sparkContext.parallelize([json.dumps(r) for r in rows], 16))


def merge(spark, df, table: str, keys: list[str]) -> None:
    if not spark.catalog.tableExists(table):
        df.write.format("delta").saveAsTable(table)
        return
    from delta.tables import DeltaTable
    spark.conf.set("spark.databricks.delta.schema.autoMerge.enabled", "true")
    cond = " AND ".join(f"t.{k} = s.{k}" for k in keys)
    DeltaTable.forName(spark, table).alias("t").merge(df.alias("s"), cond).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()


def write_match(spark, match: Match, events: list[MatchEvent], provider: str, source_key: str) -> None:
    """Merge the canonical match, events and players into the silver tables."""
    from pyspark.sql import functions as F
    row = json.loads(match.model_dump_json())
    for key in ("players", "periods", "result", "home", "away", "source_ids"):
        row[key] = json.dumps(row[key])
    row.update({"statsbomb_match_id": None, "provider": provider})
    ts = F.current_timestamp()
    merge(spark, rows_df(spark, [row]).withColumn("ingested_at_utc", ts), "silver_match", ["canonical_match_id"])
    ev = [{**json.loads(e.model_dump_json()), "related_events": json.dumps(e.related_events),
           "source_location": json.dumps(e.source_location)} for e in events]
    if ev:
        merge(spark, rows_df(spark, ev).withColumn("ingested_at_utc", ts), "silver_match_event", ["match_id", "event_id"])
    merge(spark, rows_df(spark, [{**p.model_dump(exclude={"source_ids"}), "statsbomb_id": None, f"{source_key}_id": p.source_ids.get(source_key),
                                  "match_id": match.canonical_match_id, "provider": provider} for p in match.players]),
          "silver_player", ["match_id", "player_id"])


def write_std(spark, pdf: pd.DataFrame, table: str, provider: str, match_id: str) -> None:
    schema = _types()[table]
    sdf = spark.createDataFrame(pdf[[f.name for f in schema.fields]], schema=schema)
    w = sdf.write.format("delta").mode("overwrite").option("mergeSchema", "true")
    if spark.catalog.tableExists(table):
        w = w.option("replaceWhere", f"source_provider = '{provider}' AND match_id = '{match_id}'")
    else:
        w = w.partitionBy("source_provider", "match_id")
    w.saveAsTable(table)


def write_summary(spark, rows: list[dict], provider: str) -> None:
    sdf = spark.createDataFrame(pd.DataFrame(rows))
    w = sdf.write.format("delta").mode("overwrite").option("mergeSchema", "true")
    if spark.catalog.tableExists("silver_tracking_match_std"):
        w = w.option("replaceWhere", f"source_provider = '{provider}'")
    w.saveAsTable("silver_tracking_match_std")


def summary_row(match: Match, fdf: pd.DataFrame, pdf: pd.DataFrame, provider: str, hz: float, ok: bool) -> dict:
    return {"match_id": match.canonical_match_id, "source_provider": provider, "tracking_method": SP.PROVIDERS[provider][0],
            "frame_rate": float(hz), "frames": int(len(fdf)), "positions": int(len(pdf)), "periods": int(fdf["period"].nunique()),
            "coverage_mean": float(fdf["coverage_score"].mean()) if fdf["coverage_score"].notna().any() else None,
            "player_observed_pct": float(100 * pdf["is_observed"].fillna(False).mean()) if len(pdf) else None,
            "ball_observed_pct": float(100 * fdf["ball_is_observed"].fillna(False).mean()) if len(fdf) else None,
            "competition": match.competition, "score_reconciles": bool(ok)}


def reconciles(match: Match, events: list[MatchEvent]) -> tuple[bool, tuple[int, int]]:
    g = tuple(sum(1 for e in events if (e.is_goal or e.is_own_goal) and e.team_id == t) for t in (match.home.team_id, match.away.team_id))
    return g == (match.result["home_score"], match.result["away_score"]), g
