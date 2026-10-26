# Fabric notebook source: nb_gold_tactical
# Attach to Lakehouse: lh_football_intelligence
#
# Tactical gold per match x team x window, with coordinates flipped so each team attacks left to right.
# Links: team-mates < 20 m apart; a lane is blocked by an opponent within 2.5 m of it; motifs are
# 3/4/5-cycles of the open-link graph among in-possession outfielders. Possession comes from
# gold_possession_sample. formation is detected from out-of-possession positions; declared_formation
# is StatsBomb's label in force at the window end.

# %% [parameters]
GAME_IDS = "all"

# %%
import glob
import itertools
import shutil
import sys

WHEEL = sorted(glob.glob("/lakehouse/default/Files/wheels/footballiq-*.whl"))[-1]
sys.path.insert(0, WHEEL)
# Executors import footballiq too, and Spark adds only .zip/.egg/.jar files to their sys.path.
WHEEL_ZIP = "/tmp/footballiq_pkg.zip"
shutil.copyfile(WHEEL, WHEEL_ZIP)
spark.sparkContext.addPyFile(WHEEL_ZIP)  # noqa: F821

import numpy as np
import pandas as pd
from pyspark.sql import functions as F
from pyspark.sql import types as T

W, H = 105.0, 68.0
gids = None if GAME_IDS.strip().lower() == "all" else [int(g) for g in GAME_IDS.split(",") if g.strip()]

def by_games(df):
    return df if gids is None else df.where(F.col("pff_game_id").isin(gids))

# same windows for tracking and events
def window_col(period, elapsed_ms):
    m = elapsed_ms / 60000.0
    return (F.when(period == 1, F.when(m < 15, "0-15").when(m < 30, "15-30").otherwise("30-45"))
             .when(period == 2, F.when(m < 15, "45-60").when(m < 25, "60-70").when(m < 35, "70-80").otherwise("80-90"))
             .when(period == 3, "et1").when(period == 4, "et2"))

ids = spark.table("silver_pff_match").select("match_id", "pff_game_id", "home_team_id", "away_team_id")  # noqa: F821
ids = by_games(ids)
roster = spark.table("silver_pff_roster").select("pff_game_id", "team_id", "jersey_num", "position_group")  # noqa: F821

# window bounds on the canonical clock (for API cutoffs)
frames = by_games(spark.table("silver_tracking_frame"))  # noqa: F821
bounds = (frames.withColumn("window_id", window_col(F.col("period"), F.col("period_elapsed_ms")))
          .groupBy("match_id", "pff_game_id", "window_id")
          .agg(F.min("match_elapsed_ms").alias("start_ms"), F.max("match_elapsed_ms").alias("end_ms")))

# %%
# 1 Hz samples; geometry uses every 4th (0.25 Hz)
pos = by_games(spark.table("silver_player_position"))  # noqa: F821
poss = (by_games(spark.table("gold_possession_sample"))  # noqa: F821
        .select("pff_game_id", "frame_num", F.col("team_id").alias("poss_team")))
samp = (pos.where((F.col("frame_num") % 30) == 0)
        .join(frames.select("pff_game_id", "frame_num", "ball_x_m", "ball_y_m", "period_elapsed_ms"), ["pff_game_id", "frame_num"])
        .join(poss, ["pff_game_id", "frame_num"], "left")
        .join(roster, ["pff_game_id", "team_id", "jersey_num"], "left")
        .withColumn("gk", F.coalesce(F.col("position_group") == "GK", F.lit(False)))
        .withColumn("window_id", window_col(F.col("period"), F.col("period_elapsed_ms")))
        .withColumn("x", F.coalesce("x_smooth_m", "x_m")).withColumn("y", F.coalesce("y_smooth_m", "y_m"))
        .select("match_id", "pff_game_id", "period", "frame_num", "match_elapsed_ms", "window_id", "team_id", "side",
                "jersey_num", "gk", "x", "y", "ball_x_m", "ball_y_m", "poss_team"))
samp.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("_stage_tactical_samples")
samp = spark.table("_stage_tactical_samples")  # noqa: F821

# %%
out_schema = T.StructType([
    T.StructField("match_id", T.StringType()), T.StructField("pff_game_id", T.LongType()),
    T.StructField("window_id", T.StringType()), T.StructField("team_id", T.StringType()),
    T.StructField("frame_num", T.LongType()), T.StructField("in_possession", T.BooleanType()),
    T.StructField("links", T.IntegerType()), T.StructField("open_links", T.IntegerType()),
    T.StructField("triangles", T.IntegerType()), T.StructField("quads", T.IntegerType()),
    T.StructField("pentagons", T.IntegerType()), T.StructField("width_m", T.DoubleType()),
    T.StructField("depth_m", T.DoubleType()),
    T.StructField("viable_triangles", T.IntegerType()), T.StructField("viable_quads", T.IntegerType()),
    T.StructField("viable_pentagons", T.IntegerType()), T.StructField("best_motif_score", T.DoubleType()),
    T.StructField("persistent_motifs", T.IntegerType()),
])


def geometry(pdf: pd.DataFrame) -> pd.DataFrame:
    """Links, open links and motifs per 4 s sample, in each team's attacking frame."""
    from footballiq.ml import motifs as MO
    rows, previous = [], {}
    mid, gid = pdf["match_id"].iloc[0], int(pdf["pff_game_id"].iloc[0])
    for (fnum, win), g in sorted(pdf[pdf["frame_num"] % 120 == 0].groupby(["frame_num", "window_id"]), key=lambda kv: kv[0][0]):
        poss_team = g["poss_team"].iloc[0]
        if poss_team is None or pd.isna(poss_team) or g["team_id"].nunique() < 2:
            previous = {}
            continue  # dead ball or no controller yet: motifs do not persist across it
        for team, t in g.groupby("team_id"):
            out = t[~t["gk"]]
            if len(out) < 5:
                continue
            flip = out["side"].iloc[0] != "home"
            P = out[["x", "y"]].to_numpy()
            if flip:
                P = np.column_stack([W - P[:, 0], H - P[:, 1]])
            width, depth = float(np.ptp(P[:, 1])), float(np.ptp(P[:, 0]))
            if team != poss_team:
                previous.pop(team, None)
                rows.append((mid, gid, win, team, int(fnum), False, 0, 0, 0, 0, 0, width, depth, 0, 0, 0, 0.0, 0))
                continue
            opp = g[(g["team_id"] != team)][["x", "y"]].to_numpy()
            if flip:
                opp = np.column_stack([W - opp[:, 0], H - opp[:, 1]])
            bx, by = g["ball_x_m"].iloc[0], g["ball_y_m"].iloc[0]
            ball = (W - bx, H - by) if flip and bx is not None else (bx, by)
            links = sum(1 for i, j in itertools.combinations(range(len(P)), 2) if np.linalg.norm(P[i] - P[j]) < MO.LINK_M)
            res = MO.sample(P, opp, np.array(ball, dtype=float), ids=out["jersey_num"].tolist(), previous=previous.get(team))
            previous[team] = res["seen"]
            open_links = len(MO.edges(P, opp))
            rows.append((mid, gid, win, team, int(fnum), True, links, open_links, res["triangles"], res["quads"], res["pentagons"],
                         width, depth, res["viable_triangles"], res["viable_quads"], res["viable_pentagons"],
                         max([m["score"] for m in res["motifs"]], default=0.0), sum(1 for m in res["motifs"] if m["persistence"])))
    return pd.DataFrame(rows, columns=[f.name for f in out_schema.fields])


geo = samp.groupBy("pff_game_id").applyInPandas(geometry, schema=out_schema)
geo.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("_stage_tactical_geometry")
geo = spark.table("_stage_tactical_geometry")  # noqa: F821

# %%
def formation(pts):
    """Nearest formation template to the 10 most-present outfielders' mean positions."""
    from footballiq.ml import formation as FM
    pts = sorted(pts or [], key=lambda p: -p["n"])[:10]
    return FM.assign([(p["mx"], p["my"]) for p in pts]).formation if len(pts) == 10 else None

formation_udf = F.udf(formation, T.StringType())

team_frame = (samp.join(ids, ["match_id", "pff_game_id"])
              .withColumn("ax", F.when(F.col("side") == "home", F.col("x")).otherwise(W - F.col("x")))  # team attacks right
              .withColumn("ay", F.when(F.col("side") == "home", F.col("y")).otherwise(H - F.col("y"))))
oop_means = (team_frame.where(~F.col("gk") & F.col("poss_team").isNotNull())
             .where(F.col("team_id") != F.col("poss_team"))
             .groupBy("match_id", "pff_game_id", "window_id", "team_id", "jersey_num")
             .agg(F.avg("ax").alias("mx"), F.avg("ay").alias("my"), F.count("*").alias("n")))
formations = (oop_means.groupBy("match_id", "pff_game_id", "window_id", "team_id")
              .agg(F.collect_list(F.struct("mx", "my", "n")).alias("pts"))
              .withColumn("formation", formation_udf("pts")).drop("pts"))

# heatmap: 1 Hz outfield occupancy on a 21 x 14 grid
heat = (team_frame.where(~F.col("gk"))
        .withColumn("cx", F.least(F.greatest(F.floor(F.col("ax") / 5), F.lit(0)), F.lit(20)).cast("int"))
        .withColumn("cy", F.least(F.greatest(F.floor(F.col("ay") / (H / 14)), F.lit(0)), F.lit(13)).cast("int"))
        .groupBy("match_id", "pff_game_id", "window_id", "team_id", "cx", "cy").agg(F.count("*").alias("samples")))

# %%
# passing network and regains from StatsBomb events
ev = (spark.table("silver_match_event").join(ids, "match_id")  # noqa: F821
      .where(F.col("period") <= 4)
      .withColumn("window_id", window_col(F.col("period"), F.col("period_elapsed_ms")))
      .withColumn("is_home", F.col("team_id") == F.col("home_team_id"))
      .withColumn("ax", F.when(F.col("is_home"), F.col("x_m")).otherwise(W - F.col("x_m")))
      .withColumn("ay", F.when(F.col("is_home"), F.col("y_m")).otherwise(H - F.col("y_m"))))
splayer = spark.table("silver_player").select("match_id", "player_id", F.col("jersey_number").alias("jersey"), F.col("name").alias("player_name_full"))  # noqa: F821

passes = ev.where((F.col("type") == "Pass") & (F.col("outcome") == "Complete") & F.col("recipient_id").isNotNull())
edges = (passes.groupBy("match_id", "pff_game_id", "window_id", "team_id", F.col("player_id").alias("from_id"), F.col("recipient_id").alias("to_id"))
         .agg(F.count("*").alias("passes")))
touch_ev = ev.where(F.col("player_id").isNotNull() & F.col("ax").isNotNull() & F.col("type").isin("Pass", "Ball Receipt*", "Carry", "Shot", "Dribble"))
nodes = (touch_ev.groupBy("match_id", "pff_game_id", "window_id", "team_id", "player_id")
         .agg(F.round(F.avg("ax"), 2).alias("x_m"), F.round(F.avg("ay"), 2).alias("y_m"), F.count("*").alias("touches"))
         .join(splayer, ["match_id", "player_id"], "left"))
network = (edges.join(nodes.select("match_id", "window_id", "team_id", F.col("player_id").alias("from_id"),
                                   F.col("x_m").alias("from_x"), F.col("y_m").alias("from_y")), ["match_id", "window_id", "team_id", "from_id"], "left")
           .join(nodes.select("match_id", "window_id", "team_id", F.col("player_id").alias("to_id"),
                              F.col("x_m").alias("to_x"), F.col("y_m").alias("to_y")), ["match_id", "window_id", "team_id", "to_id"], "left"))

regain_ev = ev.where(F.col("type").isin("Ball Recovery", "Interception") |
                     ((F.col("type") == "Duel") & (F.col("subtype") == "Tackle") & F.col("outcome").isin("Won", "Success In Play", "Success Out")))
regain_ev = regain_ev.where(~F.coalesce(F.col("outcome").isin("Lost", "Lost In Play", "Lost Out"), F.lit(False)) & F.col("ax").isNotNull())
regains = (regain_ev.withColumn("zx", F.least(F.floor(F.col("ax") / 17.5), F.lit(5)).cast("int"))
           .withColumn("zy", F.least(F.floor(F.col("ay") / 17.0), F.lit(3)).cast("int"))
           .groupBy("match_id", "pff_game_id", "window_id", "team_id", "zx", "zy").agg(F.count("*").alias("regains")))

# %%
# possession share per team: ours plus the StatsBomb and PFF benchmarks
pb = by_games(spark.table("gold_possession_benchmark")).where(F.col("window_id") != "match")  # noqa: F821
def team_share(c, home):
    return F.col(c) if home else F.lit(100.0) - F.col(c)
poss_bench = None
for home in (True, False):
    part = pb.select("match_id", "window_id", F.col("home_team_id" if home else "away_team_id").alias("team_id"),
                     team_share("home_pct_ours", home).alias("possession_pct"),
                     team_share("home_pct_statsbomb", home).alias("possession_pct_statsbomb"),
                     team_share("home_pct_pff", home).alias("possession_pct_pff"),
                     F.col("agree_statsbomb_pct").alias("possession_agree_statsbomb_pct"),
                     F.col("agree_pff_pct").alias("possession_agree_pff_pct"))
    poss_bench = part if poss_bench is None else poss_bench.unionByName(part)

# declared formation (Starting XI / Tactical Shift) in force at the window end
shifts = (spark.table("silver_match_event").where(F.col("formation").isNotNull())  # noqa: F821
          .select("match_id", "team_id", F.col("match_elapsed_ms").alias("t"), "source_sequence", "formation"))
declared = (bounds.join(shifts, "match_id").where(F.col("t") <= F.col("end_ms"))
            .groupBy("match_id", "window_id", "team_id")
            .agg(F.max_by("formation", F.struct("t", "source_sequence")).alias("declared_formation")))

# %%
# formation timeline: one out-of-possession assignment per 60 s, smoothed with hysteresis
from footballiq.ml import formation as FM  # noqa: E402

SEG_MS = 60_000
seg = (team_frame.where(~F.col("gk") & F.col("poss_team").isNotNull() & (F.col("team_id") != F.col("poss_team")))
       .withColumn("segment", F.floor(F.col("match_elapsed_ms") / SEG_MS).cast("long"))
       .groupBy("match_id", "pff_game_id", "team_id", "segment", "jersey_num")
       .agg(F.avg("ax").alias("mx"), F.avg("ay").alias("my"), F.count("*").alias("n"))
       .toPandas())
tl_rows, sw_rows = [], []
for (mid, gid, team), g in seg.groupby(["match_id", "pff_game_id", "team_id"]):
    labels, confs, starts = [], [], []
    for sgm, s in g.groupby("segment"):
        top = s.sort_values("n", ascending=False).head(10)
        a = FM.assign(top[["mx", "my"]].to_numpy()) if len(top) == 10 and top["n"].min() >= 5 else FM.Assignment(None, float("nan"), 0.0, ())
        labels.append(a.formation)
        confs.append(a.confidence)
        starts.append(int(sgm) * SEG_MS)
    smoothed = FM.smooth(labels, confs, min_run=2)
    for st, lab, cf, sm in zip(starts, labels, confs, smoothed):
        tl_rows.append({"match_id": mid, "pff_game_id": int(gid), "team_id": team, "start_ms": st, "end_ms": st + SEG_MS,
                        "raw_formation": lab, "confidence": round(float(cf), 3), "formation": sm})
    for t, a, b in FM.switches(starts, smoothed):
        sw_rows.append({"match_id": mid, "pff_game_id": int(gid), "team_id": team, "at_ms": int(t), "from_formation": a, "to_formation": b})
formation_tl = spark.createDataFrame(pd.DataFrame(tl_rows))  # noqa: F821
formation_sw = spark.createDataFrame(  # noqa: F821
    pd.DataFrame(sw_rows, columns=["match_id", "pff_game_id", "team_id", "at_ms", "from_formation", "to_formation"]),
    schema="match_id string, pff_game_id long, team_id string, at_ms long, from_formation string, to_formation string")
print(f"formation timeline: {len(tl_rows):,} segments, {len(sw_rows)} smoothed switches")

# %%
summary =(geo.groupBy("match_id", "pff_game_id", "window_id", "team_id")
           .agg(F.count("*").alias("samples"),
                F.sum(F.col("in_possession").cast("int")).alias("possession_samples"),
                F.sum("links").alias("links"), F.sum("open_links").alias("open_links"),
                F.sum("triangles").alias("triangles"), F.sum("quads").alias("quads"), F.sum("pentagons").alias("pentagons"),
                F.sum("viable_triangles").alias("viable_triangles"), F.sum("viable_quads").alias("viable_quads"),
                F.sum("viable_pentagons").alias("viable_pentagons"), F.sum("persistent_motifs").alias("persistent_motifs"),
                F.avg(F.when(F.col("in_possession"), F.col("best_motif_score"))).alias("best_motif_score_mean"),
                F.avg(F.when(F.col("in_possession"), F.col("width_m"))).alias("width_in_possession_m"),
                F.avg(F.when(F.col("in_possession"), F.col("depth_m"))).alias("depth_in_possession_m"),
                F.avg(F.when(~F.col("in_possession"), F.col("width_m"))).alias("width_out_of_possession_m"),
                F.avg(F.when(~F.col("in_possession"), F.col("depth_m"))).alias("depth_out_of_possession_m"))
           .join(poss_bench, ["match_id", "window_id", "team_id"], "left")
           .withColumn("lane_clearance_pct", F.round(100 * F.col("open_links") / F.nullif(F.col("links"), F.lit(0)), 1))
           .withColumn("links_per_sample", F.round(F.col("links") / F.nullif(F.col("possession_samples"), F.lit(0)), 2))
           .withColumn("triangles_per_sample", F.round(F.col("triangles") / F.nullif(F.col("possession_samples"), F.lit(0)), 2))
           .withColumn("quads_per_sample", F.round(F.col("quads") / F.nullif(F.col("possession_samples"), F.lit(0)), 2))
           .withColumn("pentagons_per_sample", F.round(F.col("pentagons") / F.nullif(F.col("possession_samples"), F.lit(0)), 2))
           .withColumn("viable_triangles_per_sample", F.round(F.col("viable_triangles") / F.nullif(F.col("possession_samples"), F.lit(0)), 2))
           .withColumn("viable_quads_per_sample", F.round(F.col("viable_quads") / F.nullif(F.col("possession_samples"), F.lit(0)), 2))
           .withColumn("viable_pentagons_per_sample", F.round(F.col("viable_pentagons") / F.nullif(F.col("possession_samples"), F.lit(0)), 2))
           .withColumn("best_motif_score_mean", F.round("best_motif_score_mean", 3))
           .join(regains.groupBy("match_id", "window_id", "team_id").agg(F.sum("regains").alias("regains")), ["match_id", "window_id", "team_id"], "left")
           .join(formations.select("match_id", "window_id", "team_id", "formation"), ["match_id", "window_id", "team_id"], "left")
           .join(declared, ["match_id", "window_id", "team_id"], "left")
           .join(bounds.select("match_id", "window_id", "start_ms", "end_ms"), ["match_id", "window_id"], "left")
           .withColumn("regains", F.coalesce("regains", F.lit(0)))
           .withColumn("sample_hz", F.lit(0.25))
           .withColumn("built_at_utc", F.current_timestamp()))

for df, table in ((summary, "gold_tactical_window"), (network, "gold_passing_network"), (heat, "gold_heatmap"), (regains, "gold_regains"),
                  (formation_tl, "gold_formation_timeline"), (formation_sw, "gold_formation_switches")):
    writer = df.write.format("delta").mode("overwrite")
    if gids is not None and spark.catalog.tableExists(table):  # noqa: F821
        writer = writer.option("mergeSchema", "true").option("replaceWhere", f"pff_game_id IN ({','.join(map(str, gids))})")
    else:
        writer = writer.option("overwriteSchema", "true")
    writer.saveAsTable(table)
    print(f"{table}: {spark.table(table).count():,} rows")  # noqa: F821

spark.sql("DROP TABLE IF EXISTS _stage_tactical_samples")  # noqa: F821
spark.sql("DROP TABLE IF EXISTS _stage_tactical_geometry")  # noqa: F821

# %%
display(spark.table("gold_tactical_window").where("match_id = '2022-12-18_argentina_france'").orderBy("team_id", "start_ms"))  # noqa: F821
