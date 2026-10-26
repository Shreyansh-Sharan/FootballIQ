# Fabric notebook source: nb_gold_possession
# Attach to Lakehouse: lh_football_intelligence
#
# Possession from PFF tracking alone, benchmarked per 5 Hz sample against StatsBomb and PFF labels.
# In play: ball present and within 0.5 m of the pitch; a dead ball resets possession.
# Control: nearest player within CONTROL_RADIUS_M, ball below 1.8 m, >= 0.3 m closer than any opponent.
# Possession switches after SWITCH_SAMPLES consecutive samples of the other team's control
# (hysteresis); after a restart the first controller takes it at once.
# Labels: StatsBomb possession_team_id of the latest event (event clock); PFF team of the latest
# on-ball event by frame, with OUT/END/stoppage events marking the ball dead.

# %% [parameters]
GAME_IDS = "all"
CONTROL_RADIUS_M = 1.0     # best PFF agreement in an 8-game sweep
SWITCH_SAMPLES = 2         # 0.4 s at 5 Hz
SWEEP = "false"

# %%
import numpy as np
import pandas as pd
from pyspark.sql import functions as F
from pyspark.sql import types as T

W, H = 105.0, 68.0
R, K = float(CONTROL_RADIUS_M), int(SWITCH_SAMPLES)
gids = None if str(GAME_IDS).strip().lower() == "all" else [int(g) for g in str(GAME_IDS).split(",") if g.strip()]

def by_games(df):
    return df if gids is None else df.where(F.col("pff_game_id").isin(gids))

def window_col(period, elapsed_ms):
    m = elapsed_ms / 60000.0
    return (F.when(period == 1, F.when(m < 15, "0-15").when(m < 30, "15-30").otherwise("30-45"))
             .when(period == 2, F.when(m < 15, "45-60").when(m < 25, "60-70").when(m < 35, "70-80").otherwise("80-90"))
             .when(period == 3, "et1").when(period == 4, "et2"))

ids = by_games(spark.table("silver_pff_match")).select("match_id", "pff_game_id", "home_team_id", "away_team_id")  # noqa: F821

# 5 Hz = every 6th 30 Hz frame; periods 1-4 only
frames = (by_games(spark.table("silver_tracking_frame"))  # noqa: F821
          .where(((F.col("frame_num") % 6) == 0) & (F.col("period") <= 4))
          .select("match_id", "pff_game_id", "period", "frame_num", "match_elapsed_ms", "period_elapsed_ms",
                  F.coalesce("ball_x_smooth_m", "ball_x_m").alias("bx"), F.coalesce("ball_y_smooth_m", "ball_y_m").alias("by"),
                  F.col("ball_z_m").alias("bz"), F.coalesce("ball_present", F.lit(False)).alias("ball_present")))
pos = (by_games(spark.table("silver_player_position")).where((F.col("frame_num") % 6) == 0)  # noqa: F821
       .select("pff_game_id", "frame_num", "side", "jersey_num",
               F.coalesce("x_smooth_m", "x_m").alias("x"), F.coalesce("y_smooth_m", "y_m").alias("y")))

# nearest player per side to the ball
near = (pos.join(frames.select("pff_game_id", "frame_num", "bx", "by"), ["pff_game_id", "frame_num"])
        .where(F.col("bx").isNotNull())
        .withColumn("d", F.sqrt((F.col("x") - F.col("bx")) ** 2 + (F.col("y") - F.col("by")) ** 2))
        .groupBy("pff_game_id", "frame_num", "side").agg(F.min(F.struct("d", "jersey_num")).alias("m")))
near = (near.groupBy("pff_game_id", "frame_num")
        .agg(F.max(F.when(F.col("side") == "home", F.col("m.d"))).alias("d_home"),
             F.max(F.when(F.col("side") == "home", F.col("m.jersey_num"))).alias("j_home"),
             F.max(F.when(F.col("side") == "away", F.col("m.d"))).alias("d_away"),
             F.max(F.when(F.col("side") == "away", F.col("m.jersey_num"))).alias("j_away")))
fr = (frames.join(near, ["pff_game_id", "frame_num"], "left").join(ids.drop("match_id"), "pff_game_id")
      .withColumn("window_id", window_col(F.col("period"), F.col("period_elapsed_ms"))))
fr.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("_stage_possession_frames")
fr = spark.table("_stage_possession_frames")  # noqa: F821
print(f"5 Hz frames: {fr.count():,}")

# %%
# Label timelines are small enough to collect and broadcast.
pff_ids = {r["match_id"]: r["pff_game_id"] for r in ids.collect()}

sb_rows = (spark.table("silver_match_event")  # noqa: F821
           .where((F.col("period") <= 4) & F.col("possession_team_id").isNotNull() & F.col("match_id").isin(list(pff_ids)))
           .select("match_id", "match_elapsed_ms", "source_sequence", "possession_team_id").toPandas()
           .sort_values(["match_id", "match_elapsed_ms", "source_sequence"]))
SB = {pff_ids[m]: (g["match_elapsed_ms"].to_numpy(np.int64), g["possession_team_id"].to_numpy(object))
      for m, g in sb_rows.groupby("match_id")}

PFF_TEAM = ("OTB", "FIRSTKICKOFF", "SECONDKICKOFF", "THIRDKICKOFF", "FOURTHKICKOFF")
PFF_DEAD = ("OUT", "END", "G", "CLK")
pff_rows = (by_games(spark.table("silver_tracking_event"))  # noqa: F821
            .where(F.col("game_event_type").isin(*PFF_TEAM, *PFF_DEAD))
            .where(F.col("game_event_type").isin(*PFF_DEAD) | F.col("team_id").isNotNull())
            .select("pff_game_id", "start_frame", "game_event_type", "team_id").toPandas()
            .sort_values(["pff_game_id", "start_frame"]))
PFF = {int(g_id): (g["start_frame"].to_numpy(np.int64),
                   np.where(g["game_event_type"].isin(PFF_DEAD), None, g["team_id"]).astype(object))
       for g_id, g in pff_rows.groupby("pff_game_id")}
b_sb, b_pff = spark.sparkContext.broadcast(SB), spark.sparkContext.broadcast(PFF)  # noqa: F821
print(f"labels: StatsBomb {len(sb_rows):,} events, PFF {len(pff_rows):,} events")

# %%
def assign(f: pd.DataFrame, radius: float, switch: int):
    """Return (in_play, state, ctrl); state and ctrl are int8 with 0 = none, 1 = home, 2 = away."""
    in_play = (f["ball_present"].to_numpy(bool) & f["bx"].between(-0.5, W + 0.5).to_numpy()
               & f["by"].between(-0.5, H + 0.5).to_numpy())
    dh = f["d_home"].fillna(np.inf).to_numpy(float)
    da = f["d_away"].fillna(np.inf).to_numpy(float)
    low = f["bz"].fillna(0.0).to_numpy(float) < 1.8
    ctrl = np.where(low & (np.minimum(dh, da) < radius) & (np.abs(dh - da) >= 0.3), np.where(dh < da, 1, 2), 0).astype(np.int8)
    period = f["period"].to_numpy()
    state = np.zeros(len(f), np.int8)
    cur, cand, run, prev_p = 0, 0, 0, None
    for i in range(len(f)):
        if period[i] != prev_p:
            cur, cand, run, prev_p = 0, 0, 0, period[i]
        if not in_play[i]:
            cur, cand, run = 0, 0, 0
            continue
        c = ctrl[i]
        if c and c != cur:
            if cur == 0:
                cur, run = c, 0
            else:
                run = run + 1 if c == cand else 1
                cand = c
                if run >= switch:
                    cur, run = c, 0
        elif c == cur:
            run = 0
        state[i] = cur
    return in_play, state, ctrl


def labels(gid: int, f: pd.DataFrame):
    sb_team = np.full(len(f), None, object)
    if gid in b_sb.value:
        t, team = b_sb.value[gid]
        k = np.searchsorted(t, f["match_elapsed_ms"].to_numpy(np.int64), side="right") - 1
        sb_team = np.where(k >= 0, team[np.clip(k, 0, None)], None)
    pff_team = np.full(len(f), None, object)
    pff_known = np.zeros(len(f), bool)
    if gid in b_pff.value:
        fr_, team = b_pff.value[gid]
        k = np.searchsorted(fr_, f["frame_num"].to_numpy(np.int64), side="right") - 1
        pff_known = k >= 0
        pff_team = np.where(pff_known, team[np.clip(k, 0, None)], None)
    return sb_team, pff_team, pff_known


sample_schema = T.StructType([
    T.StructField("match_id", T.StringType()), T.StructField("pff_game_id", T.LongType()),
    T.StructField("period", T.IntegerType()), T.StructField("window_id", T.StringType()),
    T.StructField("frame_num", T.LongType()), T.StructField("match_elapsed_ms", T.LongType()),
    T.StructField("in_play", T.BooleanType()), T.StructField("team_id", T.StringType()),
    T.StructField("controller_team_id", T.StringType()), T.StructField("controller_jersey", T.StringType()),
    T.StructField("ball_dist_m", T.DoubleType()),
    T.StructField("statsbomb_team_id", T.StringType()), T.StructField("pff_team_id", T.StringType()),
    T.StructField("pff_in_play", T.BooleanType()),
])


def samples(f: pd.DataFrame) -> pd.DataFrame:
    f = f.sort_values("frame_num").reset_index(drop=True)
    gid = int(f["pff_game_id"].iloc[0])
    home, away = f["home_team_id"].iloc[0], f["away_team_id"].iloc[0]
    teams = np.array([None, home, away], object)
    in_play, state, ctrl = assign(f, R, K)
    sb_team, pff_team, pff_known = labels(gid, f)
    jersey = np.where(ctrl == 1, f["j_home"], np.where(ctrl == 2, f["j_away"], None))
    return pd.DataFrame({
        "match_id": f["match_id"], "pff_game_id": gid, "period": f["period"].astype(int), "window_id": f["window_id"],
        "frame_num": f["frame_num"], "match_elapsed_ms": f["match_elapsed_ms"], "in_play": in_play,
        "team_id": teams[state], "controller_team_id": teams[ctrl], "controller_jersey": jersey,
        "ball_dist_m": np.round(np.minimum(f["d_home"].fillna(np.inf), f["d_away"].fillna(np.inf)).replace(np.inf, np.nan), 2),
        "statsbomb_team_id": sb_team, "pff_team_id": pff_team, "pff_in_play": pff_known & (pff_team != None),  # noqa: E711
    })


def write(df, table):
    writer = df.write.format("delta").mode("overwrite")
    if gids is not None and spark.catalog.tableExists(table):  # noqa: F821
        writer = writer.option("mergeSchema", "true").option("replaceWhere", f"pff_game_id IN ({','.join(map(str, gids))})")
    else:
        writer = writer.option("overwriteSchema", "true")
    writer.saveAsTable(table)
    print(f"{table}: {spark.table(table).count():,} rows")  # noqa: F821

# %%
# Calibration sweep: writes only gold_possession_calibration.
if str(SWEEP).lower() == "true":
    calib_schema = T.StructType([T.StructField(n, t) for n, t in (
        ("pff_game_id", T.LongType()), ("radius_m", T.DoubleType()), ("switch_samples", T.IntegerType()),
        ("n_statsbomb", T.LongType()), ("agree_statsbomb", T.LongType()), ("n_pff", T.LongType()), ("agree_pff", T.LongType()),
        ("home_ours", T.LongType()), ("assigned", T.LongType()))])

    def sweep(f: pd.DataFrame) -> pd.DataFrame:
        f = f.sort_values("frame_num").reset_index(drop=True)
        gid = int(f["pff_game_id"].iloc[0])
        teams = np.array([None, f["home_team_id"].iloc[0], f["away_team_id"].iloc[0]], object)
        sb_team, pff_team, _ = labels(gid, f)
        rows = []
        for radius in (1.0, 1.5, 2.0, 2.5, 3.0):
            for switch in (1, 2, 3, 5):
                _, state, _ = assign(f, radius, switch)
                ours = teams[state]
                has = state > 0
                m_sb = has & (sb_team != None)  # noqa: E711
                m_pff = has & (pff_team != None)  # noqa: E711
                rows.append((gid, radius, switch, int(m_sb.sum()), int((ours[m_sb] == sb_team[m_sb]).sum()),
                             int(m_pff.sum()), int((ours[m_pff] == pff_team[m_pff]).sum()), int((state == 1).sum()), int(has.sum())))
        return pd.DataFrame(rows, columns=[c.name for c in calib_schema.fields])

    calib = fr.groupBy("pff_game_id").applyInPandas(sweep, schema=calib_schema)
    write(calib, "gold_possession_calibration")
    summary = (spark.table("gold_possession_calibration").where(F.col("pff_game_id").isin(gids) if gids else F.lit(True))  # noqa: F821
               .groupBy("radius_m", "switch_samples")
               .agg(F.round(100 * F.sum("agree_statsbomb") / F.sum("n_statsbomb"), 2).alias("agree_statsbomb_pct"),
                    F.round(100 * F.sum("agree_pff") / F.sum("n_pff"), 2).alias("agree_pff_pct"))
               .orderBy(F.desc("agree_pff_pct")))
    print(summary.toPandas().to_string())

# %%
if str(SWEEP).lower() != "true":
    write(fr.groupBy("pff_game_id").applyInPandas(samples, schema=sample_schema), "gold_possession_sample")

    s = by_games(spark.table("gold_possession_sample")).join(ids.drop("match_id"), "pff_game_id")  # noqa: F821
    ours = F.col("team_id").isNotNull()
    sb_ok = ours & F.col("statsbomb_team_id").isNotNull()
    pff_ok = ours & F.col("pff_team_id").isNotNull()
    home = lambda c: (F.col(c) == F.col("home_team_id")).cast("double")  # noqa: E731

    def bench(df):
        return (df.agg(
            F.count("*").alias("samples"),
            F.sum(F.col("in_play").cast("int")).alias("in_play_samples"),
            F.sum(ours.cast("int")).alias("possession_samples"),
            F.round(100 * F.avg(F.when(ours, home("team_id"))), 1).alias("home_pct_ours"),
            F.round(100 * F.avg(F.when(sb_ok, home("statsbomb_team_id"))), 1).alias("home_pct_statsbomb"),
            F.round(100 * F.avg(F.when(pff_ok, home("pff_team_id"))), 1).alias("home_pct_pff"),
            F.round(100 * F.avg(F.when(sb_ok, (F.col("team_id") == F.col("statsbomb_team_id")).cast("double"))), 1).alias("agree_statsbomb_pct"),
            F.round(100 * F.avg(F.when(pff_ok, (F.col("team_id") == F.col("pff_team_id")).cast("double"))), 1).alias("agree_pff_pct"),
            F.round(100 * F.avg((F.col("in_play") == F.col("pff_in_play")).cast("double")), 1).alias("in_play_agree_pff_pct"),
            F.min("match_elapsed_ms").alias("start_ms"), F.max("match_elapsed_ms").alias("end_ms")))

    keys = ["match_id", "pff_game_id", "home_team_id", "away_team_id"]
    benchmark = (bench(s.groupBy(*keys, "window_id"))
                 .unionByName(bench(s.groupBy(*keys)).withColumn("window_id", F.lit("match")))
                 .withColumn("control_radius_m", F.lit(R)).withColumn("switch_samples", F.lit(K))
                 .withColumn("built_at_utc", F.current_timestamp()))
    write(benchmark, "gold_possession_benchmark")
    print(spark.table("gold_possession_benchmark").where("window_id = 'match'")  # noqa: F821
          .select(F.round(F.avg("agree_statsbomb_pct"), 2).alias("agree_statsbomb_mean"),
                  F.round(F.avg("agree_pff_pct"), 2).alias("agree_pff_mean"),
                  F.round(F.avg(F.abs(F.col("home_pct_ours") - F.col("home_pct_statsbomb"))), 2).alias("share_mae_vs_statsbomb"),
                  F.round(F.avg(F.abs(F.col("home_pct_ours") - F.col("home_pct_pff"))), 2).alias("share_mae_vs_pff"),
                  F.count("*").alias("matches")).toPandas().to_string())
