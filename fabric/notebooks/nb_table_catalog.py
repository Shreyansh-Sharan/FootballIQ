# Fabric notebook source: nb_table_catalog
# Attach to Lakehouse: lh_football_intelligence
#
# Records every Delta table's layer, rows, partitions and column types in Files/catalog/tables.json
# (rendered to fabric/SCHEMA.md by fabric_bootstrap.py catalog) and meta_table_catalog.

# %%
import json
from datetime import datetime, timezone

from pyspark.sql import functions as F

catalog = []
rows = []
for t in sorted(spark.catalog.listTables(), key=lambda t: t.name):  # noqa: F821
    if t.name.startswith("_") or t.name == "meta_table_catalog" or t.tableType == "VIEW":
        continue
    df = spark.table(t.name)  # noqa: F821
    detail = spark.sql(f"DESCRIBE DETAIL {t.name}").collect()[0]  # noqa: F821
    layer = t.name.split("_")[0]
    entry = {
        "table": t.name, "layer": layer, "rows": df.count(),
        "partition_columns": list(detail["partitionColumns"] or []),
        "size_bytes": int(detail["sizeInBytes"] or 0), "num_files": int(detail["numFiles"] or 0),
        "columns": [{"name": f.name, "type": f.dataType.simpleString(), "nullable": f.nullable} for f in df.schema.fields],
    }
    catalog.append(entry)
    rows += [(t.name, layer, i, c["name"], c["type"], c["nullable"], entry["rows"]) for i, c in enumerate(entry["columns"])]
    print(f"{t.name}: {entry['rows']:,} rows, {len(entry['columns'])} columns")

out = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "tables": catalog}
notebookutils.fs.put("Files/catalog/tables.json", json.dumps(out, indent=1), True)  # noqa: F821
(spark.createDataFrame(rows, "table_name string, layer string, ordinal int, column_name string, data_type string, "  # noqa: F821
                       "nullable boolean, table_rows long")
 .withColumn("generated_at_utc", F.current_timestamp())
 .write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("meta_table_catalog"))
