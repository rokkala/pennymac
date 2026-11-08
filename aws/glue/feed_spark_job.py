"""Glue Spark job `lbp-feed-spark`: very large full boarding tapes (> LBP_GLUE_THRESHOLD_ROWS).

1. Driver: published configuration, processing lease and schema-drift pre-flight (lbp.glue_jobs.prepare_large).
2. Executors: same mapping/rule code via RDD mapPartitions (no pandas). Write few large Parquet files
   (LBP_PARQUET_FILES, default 8). Set LBP_FORCE_REMAP=1 to rebuild even if parquet exists.
3. Persist: LBP_SPARK_MAP_ONLY=1 stops after parquet. Else with LBP_S3_IMPORT=1 coalesce to ~8 clean
   SSE CSVs under bulk-load/.../clean/sse/ + dirty JSONL; else legacy foreachPartition parts.

Job parameters: --batch_id  --processed_bucket. Glue 5.0, G.1X, auto-scaling.
"""
import json
import os
import sys

for _i, _a in enumerate(sys.argv[:-1]):
    if _a.startswith("--LBP_"):
        os.environ.setdefault(_a[2:], sys.argv[_i + 1])

from awsglue.context import GlueContext  # type: ignore  # noqa: E402
from awsglue.utils import getResolvedOptions  # type: ignore  # noqa: E402
from pyspark.context import SparkContext  # type: ignore  # noqa: E402
from pyspark.sql.types import LongType, StringType, StructField, StructType  # noqa: E402

from lbp import glue_jobs  # noqa: E402
from lbp.ingestion.parser import ParseOptions  # noqa: E402

args = getResolvedOptions(sys.argv, ["batch_id", "processed_bucket"])
sc = SparkContext.getOrCreate()
spark = GlueContext(sc).spark_session
# Speculative tasks would write a second uuid/part dir and duplicate SSE inserts on load.
spark.conf.set("spark.speculation", "false")

batch_id = args["batch_id"]
cfg, b = glue_jobs.prepare_large(batch_id)
if cfg is None:
    print(json.dumps(b))
else:
    opts = ParseOptions(**(cfg.parse_options or {}))
    fields_b = sc.broadcast(cfg.fields)
    rules_b = sc.broadcast(cfg.runtime_set)
    key = f"{cfg.mapping_id}:{cfg.mapping_version}|{cfg.rules_key}"

    base = args["processed_bucket"]
    out_path = f"{base if base.startswith('/') else 's3://' + base}/processed/batch_id={batch_id}/"

    force_remap = os.environ.get("LBP_FORCE_REMAP", "0").lower() in ("1", "true", "yes")
    already = False
    if not force_remap:
        try:
            already = spark.read.parquet(out_path).limit(1).count() > 0
        except Exception:
            already = False

    if not already:
        raw = (spark.read.option("header", True).option("inferSchema", False).option("sep", opts.delimiter or ",")
               .option("quote", '"').csv(b.file_path))
        col_names = list(raw.columns)
        chunk = int(os.environ.get("LBP_MAP_CHUNK", "5000"))
        nfiles = max(1, int(os.environ.get("LBP_PARQUET_FILES", "8")))

        def map_partitions(iterator):
            proc = glue_jobs.partition_processor(fields_b.value, rules_b.value, key)
            buf = []
            for row, idx in iterator:
                d = row.asDict(recursive=False) if hasattr(row, "asDict") else dict(zip(col_names, row))
                buf.append((int(idx), {c: ("" if d.get(c) is None else str(d.get(c))) for c in col_names}))
                if len(buf) < chunk:
                    continue
                buf.sort(key=lambda t: t[0])
                out = proc([r for _, r in buf], 0)
                for o, (idx0, _) in zip(out, buf, strict=True):
                    o["row"] = idx0
                    yield (idx0, json.dumps(o, default=str))
                buf = []
            if buf:
                buf.sort(key=lambda t: t[0])
                out = proc([r for _, r in buf], 0)
                for o, (idx0, _) in zip(out, buf, strict=True):
                    o["row"] = idx0
                    yield (idx0, json.dumps(o, default=str))

        schema = StructType([StructField("row", LongType(), False), StructField("payload", StringType(), False)])
        mapped = raw.rdd.zipWithIndex().mapPartitions(map_partitions)
        (spark.createDataFrame(mapped, schema)
         .coalesce(nfiles)
         .write.mode("overwrite")
         .parquet(out_path))
        print(json.dumps({"event": "parquet_written", "path": out_path, "files": nfiles, "map_chunk": chunk}))

    map_only = os.environ.get("LBP_SPARK_MAP_ONLY", "0").lower() in ("1", "true", "yes")
    if map_only:
        print(glue_jobs.summary(glue_jobs.mark_staged(batch_id)))
    else:
        legacy = os.environ.get("LBP_BULK_PERSIST", "1").lower() in ("0", "false", "no")
        db_free = os.environ.get("LBP_SPARK_DB_FREE", "1").lower() not in ("0", "false", "no")
        s3_import = os.environ.get("LBP_S3_IMPORT", "0").lower() in ("1", "true", "yes")
        if legacy:
            results = (json.loads(r["payload"]) for r in spark.read.parquet(out_path).orderBy("row").toLocalIterator())
            print(glue_jobs.summary(glue_jobs.persist_bulk(batch_id, cfg, results)))
        else:
            lbp_env = {k: v for k, v in os.environ.items() if k.startswith("LBP_")}
            env_b = sc.broadcast(lbp_env)
            ckpt = glue_jobs.begin_bulk(batch_id)
            ckpt_b = sc.broadcast(ckpt)
            cfg_b = sc.broadcast(cfg)
            bid_b = sc.broadcast(batch_id)
            sid_b = sc.broadcast(b.source_id)
            pchunk = int(os.environ.get("LBP_PERSIST_CHUNK", "10000"))
            nfiles = max(1, int(os.environ.get("LBP_PARQUET_FILES", "8")))

            def write_part(iterator):
                from lbp import config
                from lbp.store import db as ldb

                for k, v in env_b.value.items():
                    os.environ.setdefault(k, v)
                config.reset_settings()
                ldb.reset_engine()
                buf = []
                for r in iterator:
                    buf.append(json.loads(r.payload))
                    if len(buf) >= pchunk:
                        glue_jobs.persist_partition(
                            bid_b.value, cfg_b.value, buf, checkpoint=ckpt_b.value, source_id=sid_b.value)
                        buf = []
                if buf:
                    glue_jobs.persist_partition(
                        bid_b.value, cfg_b.value, buf, checkpoint=ckpt_b.value, source_id=sid_b.value)

            def write_coalesced(index, iterator):
                """Thin serialize: clean → CSV, dirty → part dir. Mid-partition S3 sync."""
                import csv
                from pathlib import Path

                from lbp import config
                from lbp.config import get_settings
                from lbp.store import db as ldb

                for k, v in env_b.value.items():
                    os.environ.setdefault(k, v)
                config.reset_settings()
                ldb.reset_engine()

                part_name = f"part-{index:05d}"
                sse_dir = Path(get_settings().data_dir) / "bulk-load" / bid_b.value / "clean" / "sse"
                sse_dir.mkdir(parents=True, exist_ok=True)
                csv_name = f"{part_name}.csv"
                path = sse_dir / csv_name
                cols = None
                writer = None
                fh = None
                n_clean = 0
                n_flush = 0
                buf = []
                dirty = glue_jobs.open_dirty_part_writer(bid_b.value, part_name)
                sync_every = max(1, int(os.environ.get("LBP_S3_SYNC_EVERY", "5")))

                def upload_csv():
                    if fh is None or not path.exists():
                        return
                    if not fh.closed:
                        fh.flush()
                    s = get_settings()
                    if s.env == "aws" and s.processed_bucket:
                        import boto3
                        boto3.client("s3", region_name=s.aws_region).upload_file(
                            str(path), s.processed_bucket, f"bulk-load/{bid_b.value}/clean/sse/{csv_name}")

                def flush():
                    nonlocal cols, writer, fh, n_clean, n_flush, buf
                    if not buf:
                        return
                    sink = []
                    glue_jobs.serialize_mapped_rows(
                        bid_b.value, sid_b.value, buf, cfg=cfg_b.value,
                        checkpoint=ckpt_b.value, clean_sink=sink, dirty_writer=dirty)
                    n_in = len(buf)
                    buf = []
                    n_flush += 1
                    if sink:
                        if writer is None:
                            cols = sorted({k for r in sink for k in r})
                            fh = path.open("w", newline="")
                            writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
                            writer.writeheader()
                        for r in sink:
                            writer.writerow({c: glue_jobs._csv_cell(r.get(c)) for c in cols})
                        n_clean += len(sink)
                    if n_flush % sync_every == 0:
                        upload_csv()
                        dirty.sync_s3()
                        print(json.dumps({"event": "coalesced_progress", "part": part_name,
                                          "flushes": n_flush, "chunk": n_in, "clean_rows": n_clean,
                                          "dirty_st": dirty.n_st, "dirty_ex": dirty.n_ex}), flush=True)

                for r in iterator:
                    row = json.loads(r.payload)
                    if row.get("row", -1) < ckpt_b.value:
                        continue
                    buf.append(row)
                    if len(buf) >= pchunk:
                        flush()
                flush()
                dirty.close()
                if fh is not None:
                    fh.close()
                    upload_csv()
                if n_clean or dirty.n_st or dirty.n_ex or dirty.n_lo:
                    print(json.dumps({"event": "coalesced_part", "part": part_name, "clean_rows": n_clean,
                                      "dirty_st": dirty.n_st, "dirty_ex": dirty.n_ex, "dirty_lo": dirty.n_lo,
                                      "flushes": n_flush}), flush=True)
                return iter(())

            # File count follows parquet splits (~dozens OK for aws_s3). Do not coalesce —
            # that hid S3 progress behind giant tasks.
            pdf = spark.read.parquet(out_path)
            if db_free and s3_import:
                npart = pdf.rdd.getNumPartitions()
                print(json.dumps({"event": "persist_start", "partitions": npart, "target_files": nfiles,
                                  "mode": "serialize_mapped"}))
                pdf.rdd.mapPartitionsWithIndex(write_coalesced).count()
                print(json.dumps({"event": "clean_sse_csv", "partitions": npart, "path": f"bulk-load/{batch_id}/clean/sse/"}))
            else:
                pdf.foreachPartition(write_part)
            if db_free:
                print(glue_jobs.summary(glue_jobs.mark_staged(batch_id)))
            else:
                print(glue_jobs.summary(glue_jobs.finalize_bulk(batch_id, cfg)))
