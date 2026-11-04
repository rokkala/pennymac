"""Glue Spark job `lbp-feed-spark`: very large full boarding tapes (> LBP_GLUE_THRESHOLD_ROWS).

1. Driver: published configuration, processing lease and schema-drift pre-flight (lbp.glue_jobs.prepare_large).
2. Executors: the same mapping and rule code as every other path, per partition (mapInPandas). The processed
   zone is written as Parquet (catalogued for Athena / Redshift Spectrum).
3. Driver: persists in ordered micro-batches with atomic checkpoints and bounded JDBC concurrency, then
   reconciles (lbp.glue_jobs.persist_stream). A retried run skips rows already checkpointed.

Job parameters: --batch_id  --processed_bucket. Glue 5.0, G.1X, auto-scaling.
"""
import json
import os
import sys

# Terraform passes the platform settings as --LBP_* job arguments; expose them before lbp reads its settings
for _i, _a in enumerate(sys.argv[:-1]):
    if _a.startswith("--LBP_"):
        os.environ.setdefault(_a[2:], sys.argv[_i + 1])

from awsglue.context import GlueContext  # type: ignore  # noqa: E402
from awsglue.utils import getResolvedOptions  # type: ignore  # noqa: E402
from pyspark.context import SparkContext  # type: ignore  # noqa: E402

from lbp import glue_jobs  # noqa: E402
from lbp.ingestion.parser import ParseOptions  # noqa: E402

args = getResolvedOptions(sys.argv, ["batch_id", "processed_bucket"])
sc = SparkContext.getOrCreate()
spark = GlueContext(sc).spark_session

batch_id = args["batch_id"]
cfg, b = glue_jobs.prepare_large(batch_id)
if cfg is None:
    print(json.dumps(b))
    sys.exit(0)

opts = ParseOptions(**(cfg.parse_options or {}))
fields_b = sc.broadcast(cfg.fields)
rules_b = sc.broadcast(cfg.runtime_set)
key = f"{cfg.mapping_id}:{cfg.mapping_version}|{cfg.rules_key}"

raw = (spark.read.option("header", True).option("inferSchema", False).option("sep", opts.delimiter or ",")
       .option("quote", '"').csv(b.file_path))
# file-order row numbers without a single-partition window: zipWithIndex keeps input order and stays distributed
schema = raw.schema.add("_row", "long")
raw = spark.createDataFrame(raw.rdd.zipWithIndex().map(lambda t: (*t[0], t[1])), schema=schema)


def run_partition(pdf_iter):
    import pandas as pd

    proc = glue_jobs.partition_processor(fields_b.value, rules_b.value, key)
    for pdf in pdf_iter:
        if not len(pdf):
            continue
        pdf = pdf.sort_values("_row")
        rows = pdf.drop(columns=["_row"]).fillna("").astype(str).to_dict("records")
        out = proc(rows, 0)
        for o, r in zip(out, pdf["_row"].tolist(), strict=True):
            o["row"] = int(r)
        yield pd.DataFrame({"row": [o["row"] for o in out], "payload": [json.dumps(o, default=str) for o in out]})


base = args["processed_bucket"]
out_path = f"{base if base.startswith('/') else 's3://' + base}/processed/batch_id={batch_id}/"  # a local dir for tests
raw.mapInPandas(run_partition, schema="row long, payload string").write.mode("overwrite").parquet(out_path)
results = (json.loads(r["payload"]) for r in spark.read.parquet(out_path).orderBy("row").toLocalIterator())
print(glue_jobs.summary(glue_jobs.persist_stream(batch_id, cfg, results)))
