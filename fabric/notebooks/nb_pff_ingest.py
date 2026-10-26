# Fabric notebook source: nb_pff_ingest
# Attach to Lakehouse: lh_football_intelligence
#
# PFF FC World Cup 2022, all 64 matches, from the Drive files in Files/config/pff_wc2022_manifest.json.
# Canonical frame as in StatsBomb silver: 105 x 68 m, origin top-left, home attacks left to right in every
# period; PFF raw has its origin at the centre spot. Direction per period comes from each goalkeeper's
# mean x, with disagreements against PFF metadata flagged. match_id equals the StatsBomb silver id.

# %% [parameters]
GAME_IDS = "all"            # "all" or comma-separated PFF game ids, e.g. "10517"
INCLUDE_TRACKING = True
DOWNLOAD_WORKERS = 8
FORCE_DOWNLOAD = False

# %%
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from pyspark.sql import Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

LH = "/lakehouse/default"
manifest = json.load(open(f"{LH}/Files/config/pff_wc2022_manifest.json"))
games = manifest["games"]
game_ids = sorted(games, key=int) if GAME_IDS.strip().lower() == "all" else [g.strip() for g in GAME_IDS.split(",") if g.strip()]
gid_sql = ",".join(game_ids)
print(f"{len(game_ids)} games")

# %%
BRONZE =f"{LH}/Files/bronze/pff"
url_t = manifest["download_url_template"]
jobs = []
for gid in game_ids:
    for kind, ext in (("metadata", "json"), ("rosters", "json"), ("events", "json"), ("tracking", "jsonl.bz2")):
        if kind == "tracking" and not INCLUDE_TRACKING:
            continue
        jobs.append((kind, f"{BRONZE}/{kind}/{gid}.{ext}", games[gid][kind]))
for name in ("players.csv", "competitions.csv"):
    jobs.append(("root", f"{BRONZE}/{name}", manifest["files"][name]))


def fetch(job):
    kind, path, file_id = job
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if FORCE_DOWNLOAD or not os.path.exists(path) or os.path.getsize(path) == 0:
        for attempt in range(4):
            try:
                with requests.get(url_t.format(file_id=file_id), stream=True, timeout=900) as r:
                    r.raise_for_status()
                    with open(path + ".part", "wb") as fh:
                        for chunk in r.iter_content(chunk_size=8 << 20):
                            fh.write(chunk)
                os.replace(path + ".part", path)
                break
            except Exception:
                if attempt == 3:
                    raise
    with open(path, "rb") as fh:
        head = fh.read(64)
    if head.lstrip().startswith(b"<"):
        raise ValueError(f"{path}: got HTML instead of data (Drive quota or permission page)")
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8 << 20), b""):
            h.update(chunk)
    return {"kind": kind, "file": path.replace(f"{LH}/", ""), "drive_file_id": file_id,
            "bytes": os.path.getsize(path), "sha256": h.hexdigest()}


with ThreadPoolExecutor(DOWNLOAD_WORKERS) as ex:
    bronze_log = list(ex.map(fetch, jobs))
with open(f"{BRONZE}/_manifest.json", "w") as fh:
    json.dump({"downloaded_at_utc": datetime.now(timezone.utc).isoformat(), "files": bronze_log}, fh, indent=1)
print(f"bronze: {len(bronze_log)} files, {sum(f['bytes'] for f in bronze_log) / 1e9:.2f} GB")


def slug(c):
    return F.regexp_replace(F.regexp_replace(F.lower(F.trim(c)), "[^a-z0-9]+", "-"), "^-+|-+$", "")


def write(df, table, partition=None, key="pff_game_id"):
    """Replace only this run's games; a full run or first write overwrites the table."""
    writer = df.write.format("delta").mode("overwrite")
    if spark.catalog.tableExists(table) and GAME_IDS.strip().lower() != "all":  # noqa: F821
        writer = writer.option("mergeSchema", "true").option("replaceWhere", f"{key} IN ({gid_sql})")
    else:
        writer = writer.option("overwriteSchema", "true")
        if partition:
            writer = writer.partitionBy(*partition)
    writer.saveAsTable(table)
    print(f"{table}: {spark.table(table).count():,} rows")  # noqa: F821

# %%
# silver: match metadata, rosters, players
meta_raw = spark.read.option("multiLine", True).json([f"Files/bronze/pff/metadata/{g}.json" for g in game_ids])  # noqa: F821
match = (meta_raw
         .select(F.col("id").cast("long").alias("pff_game_id"),
                 F.to_timestamp("date").alias("kickoff_utc"), F.to_date(F.col("date")).alias("match_date"),
                 F.col("competition.name").alias("competition"), F.col("season"), F.col("week").cast("int").alias("week"),
                 F.col("homeTeam.name").alias("home_team_name"), F.col("homeTeam.shortName").alias("home_team_short"),
                 F.col("homeTeam.id").alias("home_pff_team_id"),
                 F.col("awayTeam.name").alias("away_team_name"), F.col("awayTeam.shortName").alias("away_team_short"),
                 F.col("awayTeam.id").alias("away_pff_team_id"),
                 F.col("homeTeamKit.primaryColor").alias("home_kit_color"),
                 F.col("awayTeamKit.primaryColor").alias("away_kit_color"),
                 F.col("stadium.name").alias("stadium"),
                 F.col("stadium.pitches")[0]["length"].cast("double").alias("pitch_length_m"),
                 F.col("stadium.pitches")[0]["width"].cast("double").alias("pitch_width_m"),
                 F.col("fps").cast("double").alias("fps"),
                 F.col("homeTeamStartLeft").alias("meta_home_start_left"),
                 F.col("homeTeamStartLeftExtraTime").alias("meta_home_start_left_et"),
                 F.col("videoUrl").alias("video_url"))
         .withColumn("home_team_id", slug(F.col("home_team_name")))
         .withColumn("away_team_id", slug(F.col("away_team_name")))
         .withColumn("match_id", F.concat_ws("_", F.date_format("match_date", "yyyy-MM-dd"), "home_team_id", "away_team_id"))
         .withColumn("ingested_at_utc", F.current_timestamp()))
ids = match.select("pff_game_id", "match_id", "home_team_id", "away_team_id", "home_pff_team_id", "away_pff_team_id").cache()

roster_raw = (spark.read.option("multiLine", True).json([f"Files/bronze/pff/rosters/{g}.json" for g in game_ids])  # noqa: F821
              .withColumn("pff_game_id", F.regexp_extract(F.input_file_name(), r"/(\d+)\.json", 1).cast("long")))
roster = (roster_raw.join(ids, "pff_game_id")
          .select("match_id", "pff_game_id",
                  F.col("player.id").alias("pff_player_id"), F.col("player.nickname").alias("player_name"),
                  F.col("shirtNumber").cast("string").alias("jersey_num"),
                  F.col("positionGroupType").alias("position_group"), F.col("started").cast("boolean").alias("started"),
                  F.col("team.id").alias("pff_team_id"), F.col("team.name").alias("team_name"))
          .withColumn("team_id", slug(F.col("team_name")))
          .withColumn("player_id", F.concat_ws("_", F.col("team_id"), slug(F.col("player_name")))))

players = (spark.read.option("header", True).csv("Files/bronze/pff/players.csv")  # noqa: F821
           .select(F.col("id").alias("pff_player_id"), F.col("nickname").alias("player_name"),
                   F.col("firstName").alias("first_name"), F.col("lastName").alias("last_name"),
                   F.to_date("dob").alias("dob"), F.col("height").cast("double").alias("height_cm"),
                   F.col("positionGroupType").alias("position_group")))

write(match, "silver_pff_match")
write(roster, "silver_pff_roster")
players.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("silver_pff_player")
print(f"silver_pff_player: {players.count():,} rows")

# %%
# tracking: frames, positions, events
player_t = T.StructType([
    T.StructField("jerseyNum", T.StringType()), T.StructField("confidence", T.StringType()),
    T.StructField("visibility", T.StringType()), T.StructField("x", T.DoubleType()),
    T.StructField("y", T.DoubleType()), T.StructField("speed", T.DoubleType()),
])
ball_t = T.StructType([
    T.StructField("visibility", T.StringType()), T.StructField("x", T.DoubleType()),
    T.StructField("y", T.DoubleType()), T.StructField("z", T.DoubleType()),
])
frame_schema = T.StructType([
    T.StructField("version", T.StringType()), T.StructField("gameRefId", T.DoubleType()),
    T.StructField("videoTimeMs", T.DoubleType()), T.StructField("frameNum", T.LongType()),
    T.StructField("period", T.IntegerType()), T.StructField("periodElapsedTime", T.DoubleType()),
    T.StructField("periodGameClockTime", T.DoubleType()),
    T.StructField("homePlayers", T.ArrayType(player_t)), T.StructField("homePlayersSmoothed", T.ArrayType(player_t)),
    T.StructField("awayPlayers", T.ArrayType(player_t)), T.StructField("awayPlayersSmoothed", T.ArrayType(player_t)),
    T.StructField("balls", T.ArrayType(ball_t)), T.StructField("ballsSmoothed", ball_t),
    T.StructField("game_event_id", T.DoubleType()), T.StructField("possession_event_id", T.DoubleType()),
    T.StructField("game_event", T.StructType([
        T.StructField("game_event_type", T.StringType()), T.StructField("formatted_game_clock", T.StringType()),
        T.StructField("player_id", T.StringType()), T.StructField("player_name", T.StringType()),
        T.StructField("shirt_number", T.StringType()), T.StructField("team_id", T.StringType()),
        T.StructField("team_name", T.StringType()), T.StructField("home_team", T.IntegerType()),
        T.StructField("home_ball", T.BooleanType()), T.StructField("start_frame", T.LongType()),
        T.StructField("end_frame", T.LongType()),
    ])),
    T.StructField("possession_event", T.StructType([T.StructField("possession_event_type", T.StringType())])),
])

if INCLUDE_TRACKING:
    raw = (spark.read.schema(frame_schema)  # noqa: F821
           .json([f"Files/bronze/pff/tracking/{g}.jsonl.bz2" for g in game_ids])
           # gameRefId is set only on a file's first frame, so take the game id from the file name
           .withColumn("pff_game_id", F.regexp_extract(F.input_file_name(), r"/(\d+)\.jsonl\.bz2", 1).cast("long"))
           .where(F.col("period").isNotNull()))
    raw.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("_stage_pff_frames")
    raw_all = spark.table("_stage_pff_frames")  # noqa: F821  (decompress bz2 once, reuse for every output)
    # PFF repeats a frame once per event in it: keep one row per frame, with all its event ids in arrays.
    frame_events = (raw_all.groupBy("pff_game_id", "frameNum")
                    .agg(F.array_sort(F.collect_set(F.col("game_event_id").cast("long"))).alias("game_event_ids"),
                         F.array_sort(F.collect_set(F.col("possession_event_id").cast("long"))).alias("possession_event_ids"),
                         F.count("*").alias("source_rows")))
    raw = (raw_all.withColumn("_rk", F.row_number().over(
               Window.partitionBy("pff_game_id", "frameNum").orderBy(F.col("game_event_id").asc_nulls_last())))
           .where("_rk = 1").drop("_rk").join(frame_events, ["pff_game_id", "frameNum"]))

    def explode_side(raw_col, smooth_col, side):
        base = (raw.select("pff_game_id", "frameNum", "period", "periodElapsedTime", F.explode(raw_col).alias("p"))
                .select("pff_game_id", "frameNum", "period", "periodElapsedTime",
                        F.col("p.jerseyNum").alias("jersey_num"), F.col("p.x").alias("x_raw"), F.col("p.y").alias("y_raw"),
                        F.col("p.speed").alias("speed_mps"), F.col("p.visibility").alias("visibility"),
                        F.col("p.confidence").alias("confidence"), F.lit(side).alias("side")))
        sm = (raw.select("pff_game_id", "frameNum", F.explode(smooth_col).alias("s"))
              .select("pff_game_id", "frameNum", F.col("s.jerseyNum").alias("jersey_num"),
                      F.col("s.x").alias("x_smooth_raw"), F.col("s.y").alias("y_smooth_raw"))
              .dropDuplicates(["pff_game_id", "frameNum", "jersey_num"]))  # smoothed arrays occasionally repeat a jersey
        return base.join(sm, ["pff_game_id", "frameNum", "jersey_num"], "left")

    pl = explode_side("homePlayers", "homePlayersSmoothed", "home").unionByName(
        explode_side("awayPlayers", "awayPlayersSmoothed", "away"))

    # direction per period from the goalkeeper (largest |mean x| with enough frames)
    per_player = (pl.groupBy("pff_game_id", "period", "side", "jersey_num")
                  .agg(F.avg("x_raw").alias("mean_x"), F.count("*").alias("n")).where("n > 1000"))
    gk = (per_player.withColumn("rk", F.row_number().over(
              Window.partitionBy("pff_game_id", "period", "side").orderBy(F.abs("mean_x").desc())))
          .where("rk = 1"))
    home_dir = (gk.where("side = 'home'").select("pff_game_id", "period", F.col("jersey_num").alias("home_gk_jersey"),
                                                 F.round("mean_x", 2).alias("home_gk_mean_x"),
                                                 (F.col("mean_x") < 0).alias("home_attacks_positive_x")))

    bounds = raw.groupBy("pff_game_id", "period").agg(
        F.min("frameNum").alias("start_frame"), F.max("frameNum").alias("end_frame"),
        F.count("*").alias("frames"), (F.max("periodElapsedTime") * 1000).cast("long").alias("pff_duration_ms"))
    wcum = Window.partitionBy("pff_game_id").orderBy("period").rowsBetween(Window.unboundedPreceding, -1)
    periods = (bounds.join(home_dir, ["pff_game_id", "period"], "left").join(ids, "pff_game_id")
               .withColumn("pff_start_match_ms", F.coalesce(F.sum("pff_duration_ms").over(wcum), F.lit(0)).cast("long")))
    if spark.catalog.tableExists("silver_match"):  # noqa: F821
        sb = (spark.table("silver_match")  # noqa: F821
              .select(F.col("canonical_match_id").alias("match_id"),
                      F.explode(F.from_json("periods", "array<struct<period:int,start_match_ms:long>>")).alias("p"))
              .select("match_id", F.col("p.period").alias("period"), F.col("p.start_match_ms").alias("sb_start_match_ms")))
        periods = periods.join(sb, ["match_id", "period"], "left")
    else:
        periods = periods.withColumn("sb_start_match_ms", F.lit(None).cast("long"))
    meta_dir = match.select("pff_game_id", "meta_home_start_left", "meta_home_start_left_et")
    periods = (periods.join(meta_dir, "pff_game_id", "left")
               .withColumn("start_match_ms", F.coalesce("sb_start_match_ms", "pff_start_match_ms"))
               .withColumn("clock_source", F.when(F.col("sb_start_match_ms").isNotNull(), "statsbomb_periods")
                           .otherwise("pff_periods"))
               # metadata gives home's starting side; halves alternate within regulation and extra time
               .withColumn("meta_home_attacks_positive_x",
                           F.when(F.col("period").isin(1, 3), F.when(F.col("period") == 1, F.col("meta_home_start_left"))
                                  .otherwise(F.col("meta_home_start_left_et")))
                           .when(F.col("period") == 2, ~F.col("meta_home_start_left"))
                           .when(F.col("period") == 4, ~F.col("meta_home_start_left_et")))
               .withColumn("direction_agrees_with_metadata",
                           F.col("meta_home_attacks_positive_x") == F.col("home_attacks_positive_x")))
    silver_periods = periods.select(
        "match_id", "pff_game_id", "period", "start_frame", "end_frame", "frames", "pff_duration_ms", "start_match_ms",
        "clock_source", "home_gk_jersey", "home_gk_mean_x", "home_attacks_positive_x",
        "meta_home_attacks_positive_x", "direction_agrees_with_metadata")
    write(silver_periods, "silver_tracking_period")
    pmap = spark.table("silver_tracking_period").where(f"pff_game_id IN ({gid_sql})") \
        .select("pff_game_id", "period", "start_match_ms", "home_attacks_positive_x")  # noqa: F821

    hp = F.col("home_attacks_positive_x")

    def cx(c):
        return F.round(F.when(hp, F.col(c) + 52.5).otherwise(52.5 - F.col(c)), 3)

    def cy(c):
        return F.round(F.when(hp, 34.0 - F.col(c)).otherwise(34.0 + F.col(c)), 3)

    frames = (raw.join(pmap, ["pff_game_id", "period"]).join(ids.select("pff_game_id", "match_id"), "pff_game_id")
              .withColumn("ball", F.col("balls")[0])
              .select("match_id", "pff_game_id", "period", F.col("frameNum").alias("frame_num"),
                      F.col("videoTimeMs").cast("long").alias("video_time_ms"),
                      (F.col("periodElapsedTime") * 1000).cast("long").alias("period_elapsed_ms"),
                      (F.col("start_match_ms") + F.col("periodElapsedTime") * 1000).cast("long").alias("match_elapsed_ms"),
                      cx("ball.x").alias("ball_x_m"), cy("ball.y").alias("ball_y_m"), F.round("ball.z", 3).alias("ball_z_m"),
                      F.col("ball.visibility").alias("ball_visibility"),
                      F.coalesce(F.col("ball.visibility") == "VISIBLE", F.lit(False)).alias("ball_observed"),
                      F.col("ball").isNotNull().alias("ball_present"),
                      cx("ballsSmoothed.x").alias("ball_x_smooth_m"), cy("ballsSmoothed.y").alias("ball_y_smooth_m"),
                      F.col("game_event_id").cast("long").alias("game_event_id"),
                      F.col("possession_event_id").cast("long").alias("possession_event_id"),
                      "game_event_ids", "possession_event_ids", F.col("source_rows").alias("source_rows"),
                      F.col("game_event.game_event_type").alias("game_event_type"),
                      F.col("possession_event.possession_event_type").alias("possession_event_type"),
                      F.size("homePlayers").alias("home_players_n"), F.size("awayPlayers").alias("away_players_n")))
    write(frames, "silver_tracking_frame", ["pff_game_id"])

    positions = (pl.join(pmap, ["pff_game_id", "period"]).join(ids, "pff_game_id")
                 .select("match_id", "pff_game_id", "period", F.col("frameNum").alias("frame_num"),
                         (F.col("start_match_ms") + F.col("periodElapsedTime") * 1000).cast("long").alias("match_elapsed_ms"),
                         F.when(F.col("side") == "home", F.col("home_team_id")).otherwise(F.col("away_team_id")).alias("team_id"),
                         "side", "jersey_num", cx("x_raw").alias("x_m"), cy("y_raw").alias("y_m"),
                         cx("x_smooth_raw").alias("x_smooth_m"), cy("y_smooth_raw").alias("y_smooth_m"),
                         F.round("speed_mps", 3).alias("speed_mps"), "visibility", "confidence",
                         (F.col("visibility") == "VISIBLE").alias("observed")))
    write(positions, "silver_player_position", ["pff_game_id"])

    tev = (raw_all.where(F.col("game_event").isNotNull()).select("pff_game_id", "game_event.*").join(ids, "pff_game_id")
           .select("match_id", "pff_game_id", "game_event_type", "formatted_game_clock",
                   F.col("player_id").alias("pff_player_id"), "player_name", F.col("shirt_number").alias("jersey_num"),
                   "team_name", F.when(F.col("home_team") == 1, F.col("home_team_id"))
                   .when(F.col("home_team") == 0, F.col("away_team_id")).alias("team_id"),
                   "home_ball", "start_frame", "end_frame")
           .dropDuplicates(["pff_game_id", "start_frame", "game_event_type", "pff_player_id"]))
    write(tev, "silver_tracking_event")

# %%
# silver PFF events: one row per game event, possession details flattened
ev_raw = (spark.read.option("multiLine", True).json([f"Files/bronze/pff/events/{g}.json" for g in game_ids])  # noqa: F821
          .withColumn("pff_game_id", F.col("gameId").cast("long")))
ge_cols = [F.col(f"gameEvents.{c}").alias(f"ge_{c}") for c in ev_raw.select("gameEvents.*").columns]
pe_cols = [F.col(f"possessionEvents.{c}").alias(f"pe_{c}") for c in ev_raw.select("possessionEvents.*").columns]
foul_cols = [F.col(f"fouls.{c}").alias(f"foul_{c}") for c in ev_raw.select("fouls.*").columns]
it_cols = [F.col(f"initialTouch.{c}").alias(f"touch_{c}") for c in ev_raw.select("initialTouch.*").columns]
events = (ev_raw.join(ids, "pff_game_id")
          .select("match_id", "pff_game_id", "home_team_id", "away_team_id",
                  F.col("gameEventId").cast("long").alias("game_event_id"),
                  F.col("possessionEventId").cast("long").alias("possession_event_id"),
                  F.col("sequence").cast("double").alias("sequence"),
                  F.col("startTime").cast("double").alias("start_time_s"), F.col("endTime").cast("double").alias("end_time_s"),
                  F.col("eventTime").cast("double").alias("event_time_s"), F.col("duration").cast("double").alias("duration_s"),
                  F.col("stadiumMetadata.teamAttackingDirection").alias("team_attacking_direction"),
                  F.col("ball")[0]["x"].alias("ball_x_raw"), F.col("ball")[0]["y"].alias("ball_y_raw"),
                  F.col("ball")[0]["z"].alias("ball_z_raw"),
                  F.to_json("homePlayers").alias("home_players_json"), F.to_json("awayPlayers").alias("away_players_json"),
                  F.to_json("grades").alias("grades_json"),
                  *ge_cols, *pe_cols, *foul_cols, *it_cols)
          .withColumn("team_id", F.when(F.col("ge_homeTeam") == True, F.col("home_team_id"))  # noqa: E712
                      .when(F.col("ge_homeTeam") == False, F.col("away_team_id")))  # noqa: E712
          .drop("home_team_id", "away_team_id")
          .withColumn("ingested_at_utc", F.current_timestamp()))
if INCLUDE_TRACKING:
    # place each event on the canonical clock via the first tracking frame that carries its game_event_id
    ev_clock = (spark.table("silver_tracking_frame").where(f"pff_game_id IN ({gid_sql})")  # noqa: F821
                .select("pff_game_id", "frame_num", "match_elapsed_ms", F.explode("game_event_ids").alias("game_event_id"))
                .groupBy("pff_game_id", "game_event_id").agg(F.min("frame_num").alias("frame_num"),
                                                              F.min("match_elapsed_ms").alias("match_elapsed_ms")))
    events = events.join(ev_clock, ["pff_game_id", "game_event_id"], "left")
write(events, "silver_pff_event", ["pff_game_id"])

# %%
if INCLUDE_TRACKING:
    spark.sql("DROP TABLE IF EXISTS _stage_pff_frames")  # noqa: F821
    display(spark.table("silver_tracking_period").orderBy("pff_game_id", "period"))  # noqa: F821
