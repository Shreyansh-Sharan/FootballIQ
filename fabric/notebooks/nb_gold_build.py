# Fabric notebook source: nb_gold_build
# Attach to Lakehouse: lh_football_intelligence
#
# Event-derived gold tables from silver_match_event. gold_match_summary holds final results
# and is never served to replay. Metric definitions must match backend/footballiq/replay/timeline.py.

# %% [parameters]
MATCH_ID = ""   # canonical match id; empty = rebuild all matches

# %%
from pyspark.sql import functions as F

ev = spark.table("silver_match_event")  # noqa: F821
if MATCH_ID:
    ev = ev.where(F.col("match_id") == MATCH_ID)
ev = ev.where(F.col("period") < 5)

is_pass_attempt = (F.col("type") == "Pass") & ~F.coalesce(F.col("subtype"), F.lit("")).isin("Throw-in") \
    & ~F.coalesce(F.col("outcome"), F.lit("")).isin("Unknown", "Injury Clearance")
is_tackle = (F.col("type") == "Duel") & (F.col("subtype") == "Tackle")

def counters():
    return [
        F.sum(F.col("is_goal").cast("int")).alias("goals"),
        F.sum((F.col("type") == "Shot").cast("int")).alias("shots"),
        F.sum(((F.col("type") == "Shot") & F.col("outcome").isin("Goal", "Saved", "Saved To Post")).cast("int")).alias("shots_on_target"),
        F.round(F.sum(F.coalesce(F.col("provider_xg"), F.lit(0.0))), 4).alias("provider_xg"),
        F.sum(is_pass_attempt.cast("int")).alias("passes_attempted"),
        F.sum((is_pass_attempt & (F.col("outcome") == "Complete")).cast("int")).alias("passes_completed"),
        F.sum(((F.col("type") == "Pass") & (F.col("subtype") == "Corner")).cast("int")).alias("corners"),
        F.sum((F.col("type") == "Foul Committed").cast("int")).alias("fouls"),
        F.sum((F.col("card") == "Yellow Card").cast("int")).alias("yellow_cards"),
        F.sum(F.col("card").isin("Red Card", "Second Yellow").cast("int")).alias("red_cards"),
        F.sum(is_tackle.cast("int")).alias("tackles"),
        F.sum((is_tackle & F.col("outcome").isin("Won", "Success In Play", "Success Out")).cast("int")).alias("tackles_won"),
        F.sum((F.col("type") == "Pressure").cast("int")).alias("pressures"),
    ]

# %%
team_5s = (
    ev.where(F.col("team_id").isNotNull())
    .withColumn("bin_start_ms", (F.floor(F.col("match_elapsed_ms") / 5000) * 5000).cast("long"))
    .groupBy("match_id", "team_id", "period", "bin_start_ms")
    .agg(*counters())
    .withColumn("source", F.lit("event-derived"))
    .withColumn("built_at_utc", F.current_timestamp())
)

player_match = (
    ev.where(F.col("player_id").isNotNull())
    .groupBy("match_id", "team_id", "player_id", "player_name")
    .agg(*counters(), F.count("*").alias("actions"))
    .withColumn("pass_accuracy_pct", F.when(F.col("passes_attempted") > 0, F.round(100 * F.col("passes_completed") / F.col("passes_attempted"), 1)))
    .withColumn("built_at_utc", F.current_timestamp())
)

team_match = (
    ev.where(F.col("team_id").isNotNull())
    .groupBy("match_id", "team_id")
    .agg(*counters())
    .withColumn("pass_accuracy_pct", F.when(F.col("passes_attempted") > 0, F.round(100 * F.col("passes_completed") / F.col("passes_attempted"), 1)))
)

opp =team_match.select("match_id", F.col("team_id").alias("opponent_id"), F.col("goals").alias("goals_against"))
summary = (
    team_match.join(opp, "match_id").where(F.col("team_id") != F.col("opponent_id"))
    .join(spark.table("silver_match").select(F.col("canonical_match_id").alias("match_id"), "competition", "season", "kickoff_source"), "match_id")  # noqa: F821
    .withColumn("match_date", F.to_date(F.substring("kickoff_source", 1, 10)))
    .withColumn("result", F.when(F.col("goals") > F.col("goals_against"), "W")
                .when(F.col("goals") < F.col("goals_against"), "L").otherwise("D"))
    .withColumn("built_at_utc", F.current_timestamp())
)

# Pre-match cutoff: a history row is usable only for matches after its as_of_time.
history = summary.select(
    "team_id", "opponent_id", "match_id", "competition", "season", "match_date",
    "goals", "goals_against", "result", "shots", "provider_xg", "pass_accuracy_pct",
    F.col("match_date").cast("timestamp").alias("as_of_time"),
    F.lit("statsbomb").alias("provider"),
)

# %%
def replace_partition(df, table, match_col="match_id"):
    """Overwrite only MATCH_ID's rows when it is set, else the whole table."""
    if spark.catalog.tableExists(table) and MATCH_ID:  # noqa: F821
        (df.write.format("delta").mode("overwrite")
           .option("replaceWhere", f"{match_col} = '{MATCH_ID}'").saveAsTable(table))
    else:
        df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table)

replace_partition(team_5s, "gold_team_metrics_5s")
replace_partition(player_match, "gold_player_match_metrics")
replace_partition(summary, "gold_match_summary")
replace_partition(history, "gold_match_history")

# %%
display(spark.table("gold_match_summary").orderBy("match_id", "team_id"))  # noqa: F821
