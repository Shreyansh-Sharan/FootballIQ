# Fabric notebook source: nb_gold_tracking
# Attach to Lakehouse: lh_football_intelligence
#
# Physical and shape gold from PFF tracking. Distance counts only steps with dt <= 0.2 s and
# implied speed <= 12.5 m/s, so tracking gaps never read as sprints. No fatigue or medical claims.

# %% [parameters]
GAME_IDS = "all"   # "all" or comma-separated PFF game ids

# %%
from pyspark.sql import Window
from pyspark.sql import functions as F

pos = spark.table("silver_player_position")  # noqa: F821
frames = spark.table("silver_tracking_frame")  # noqa: F821
if GAME_IDS.strip().lower() != "all":
    gids = [int(g) for g in GAME_IDS.split(",") if g.strip()]
    pos = pos.where(F.col("pff_game_id").isin(gids))
    frames = frames.where(F.col("pff_game_id").isin(gids))
else:
    gids = [r[0] for r in pos.select("pff_game_id").distinct().collect()]

MAX_DT_MS = 200
MAX_SPEED = 12.5
HSR = 5.5      # high-speed running threshold, m/s
SPRINT = 7.0   # sprint threshold, m/s

# %%
w = Window.partitionBy("pff_game_id", "period", "team_id", "jersey_num").orderBy("frame_num")
steps = (pos
         .withColumn("x", F.coalesce("x_smooth_m", "x_m")).withColumn("y", F.coalesce("y_smooth_m", "y_m"))
         .withColumn("dt_ms", F.col("match_elapsed_ms") - F.lag("match_elapsed_ms").over(w))
         .withColumn("dd", F.sqrt((F.col("x") - F.lag("x").over(w)) ** 2 + (F.col("y") - F.lag("y").over(w)) ** 2))
         .withColumn("valid_step", (F.col("dt_ms") > 0) & (F.col("dt_ms") <= MAX_DT_MS)
                     & (F.col("dd") / (F.col("dt_ms") / 1000) <= MAX_SPEED))
         .withColumn("step_m", F.when(F.col("valid_step"), F.col("dd")).otherwise(F.lit(0.0)))
         .withColumn("speed_capped", F.when(F.col("speed_mps") <= MAX_SPEED, F.col("speed_mps")))
         .withColumn("second", (F.col("match_elapsed_ms") / 1000).cast("long")))

# (team, shirt number) -> player, per match
roster = (spark.table("silver_pff_roster")  # noqa: F821
          .select("match_id", "team_id", "jersey_num", "player_id", "pff_player_id", "player_name",
                  "position_group", "started"))


def with_names(df):
    return (df.join(roster, ["match_id", "team_id", "jersey_num"], "left")
              .withColumn("player_id", F.coalesce("player_id", F.concat_ws("_", "team_id", F.lit("no"), "jersey_num"))))

# %%
player_1s = with_names(
    steps.groupBy("match_id", "pff_game_id", "period", "team_id", "side", "jersey_num", "second")
    .agg(F.round(F.avg("x"), 2).alias("x_m"), F.round(F.avg("y"), 2).alias("y_m"),
         F.round(F.avg("speed_capped"), 3).alias("avg_speed_mps"), F.round(F.max("speed_capped"), 3).alias("max_speed_mps"),
         F.round(F.sum("step_m"), 3).alias("distance_m"),
         F.count("*").alias("frames"), F.sum(F.col("observed").cast("int")).alias("observed_frames"))
    .withColumn("observed_pct", F.round(100 * F.col("observed_frames") / F.col("frames"), 1))
).withColumn("built_at_utc", F.current_timestamp())

physical = with_names(
    steps.groupBy("match_id", "pff_game_id", "team_id", "side", "jersey_num")
    .agg(F.round(F.sum("step_m"), 1).alias("distance_m"),
         F.round(F.sum(F.when(F.col("speed_capped") >= HSR, F.col("step_m")).otherwise(0)), 1).alias("hsr_distance_m"),
         F.round(F.sum(F.when(F.col("speed_capped") >= SPRINT, F.col("step_m")).otherwise(0)), 1).alias("sprint_distance_m"),
         F.round(F.expr("percentile_approx(speed_capped, 0.995)"), 2).alias("top_speed_mps"),
         F.round((F.max("match_elapsed_ms") - F.min("match_elapsed_ms")) / 60000, 1).alias("tracked_span_min"),
         F.count("*").alias("frames"), F.sum(F.col("observed").cast("int")).alias("observed_frames"))
    .withColumn("observed_pct", F.round(100 * F.col("observed_frames") / F.col("frames"), 1))
    .withColumn("thresholds", F.lit(f"hsr>={HSR} m/s, sprint>={SPRINT} m/s, step dt<={MAX_DT_MS} ms, v<={MAX_SPEED} m/s"))
).withColumn("built_at_utc", F.current_timestamp())

# Team shape excludes the goalkeeper, taken as the player whose mean x is furthest from halfway.
gk = (pos.groupBy("pff_game_id", "period", "team_id", "jersey_num").agg(F.avg("x_m").alias("mx"), F.count("*").alias("n"))
      .where("n > 1000")
      .withColumn("rk", F.row_number().over(Window.partitionBy("pff_game_id", "period", "team_id")
                                            .orderBy(F.abs(F.col("mx") - 52.5).desc())))
      .where("rk = 1").select("pff_game_id", "period", "team_id", F.col("jersey_num").alias("gk_jersey")))
outfield = (steps.join(gk, ["pff_game_id", "period", "team_id"], "left")
            .where((F.col("gk_jersey").isNull()) | (F.col("jersey_num") != F.col("gk_jersey"))))
per_frame = (outfield.groupBy("match_id", "pff_game_id", "period", "team_id", "frame_num", "match_elapsed_ms")
             .agg(F.avg("x").alias("cx"), F.avg("y").alias("cy"),
                  (F.max("y") - F.min("y")).alias("width"), (F.max("x") - F.min("x")).alias("depth"),
                  F.count("*").alias("n_players"), F.sum(F.col("observed").cast("int")).alias("n_observed")))
shape_5s = (per_frame.withColumn("bin_start_ms", (F.floor(F.col("match_elapsed_ms") / 5000) * 5000).cast("long"))
            .groupBy("match_id", "pff_game_id", "period", "team_id", "bin_start_ms")
            .agg(F.round(F.avg("cx"), 2).alias("centroid_x_m"), F.round(F.avg("cy"), 2).alias("centroid_y_m"),
                 F.round(F.avg("width"), 2).alias("width_m"), F.round(F.avg("depth"), 2).alias("depth_m"),
                 F.round(F.avg(F.col("width") * F.col("depth")), 1).alias("block_area_m2"),
                 F.round(F.avg("n_players"), 1).alias("avg_outfield_players"),
                 F.round(100 * F.sum("n_observed") / F.sum("n_players"), 1).alias("observed_pct"))
            .withColumn("built_at_utc", F.current_timestamp()))

coverage = (frames.withColumn("minute", (F.col("match_elapsed_ms") / 60000).cast("int"))
            .groupBy("match_id", "pff_game_id", "period", "minute")
            .agg(F.count("*").alias("frames"),
                 F.round(100 * F.avg(F.col("ball_present").cast("int")), 1).alias("ball_present_pct"),
                 F.round(100 * F.avg(F.col("ball_observed").cast("int")), 1).alias("ball_observed_pct"),
                 F.round(F.avg(F.col("home_players_n") + F.col("away_players_n")), 1).alias("avg_players_per_frame"))
            .join(pos.withColumn("minute", (F.col("match_elapsed_ms") / 60000).cast("int"))
                  .groupBy("pff_game_id", "period", "minute")
                  .agg(F.round(100 * F.avg(F.col("observed").cast("int")), 1).alias("player_observed_pct")),
                  ["pff_game_id", "period", "minute"], "left")
            .withColumn("built_at_utc", F.current_timestamp()))

# %%
gid_list = ",".join(str(g) for g in gids)

def write(df, table, partition=None):
    writer = df.write.format("delta").mode("overwrite")
    if spark.catalog.tableExists(table):  # noqa: F821
        writer = writer.option("mergeSchema", "true").option("replaceWhere", f"pff_game_id IN ({gid_list})")
    else:
        writer = writer.option("overwriteSchema", "true")
        if partition:
            writer = writer.partitionBy(*partition)
    writer.saveAsTable(table)
    print(f"{table}: {spark.table(table).where(F.col('pff_game_id').isin(gids)).count():,} rows")  # noqa: F821

write(player_1s, "gold_player_metrics_1s", ["pff_game_id"])
write(physical, "gold_player_physical_match")
write(shape_5s, "gold_team_shape_5s")
write(coverage, "gold_tracking_coverage_1m")

# %%
display(spark.table("gold_player_physical_match").orderBy(F.desc("distance_m")).limit(30))  # noqa: F821
