# Spark / load job split (full tapes)

## Goal

Completely separate **compute** from **Postgres load** for large full tapes so:

1. Spark never opens a DB connection during persist.
2. Load can retry from S3 without rematerializing 10M rows.
3. Wall-clock phases are observable (Spark time vs load time).

Honest constraint: end-to-end boarding time is still dominated by writing ~5M boarded + ~15M exception rows into RDS (`db.t4g.medium`). This split improves retry and Spark duration; it does **not** by itself make RDS faster.

## Scope

**In**

- Glue Spark path for full tapes above `LBP_GLUE_THRESHOLD_ROWS`.
- New Glue load job + Step Functions wiring after Spark.
- Materialize clean + dirty to S3; load via streaming `COPY`.
- Move **DUP02** (already boarded in another batch) into the load job.

**Out**

- Small-tape `lbp-feed` (standard engine) behavior.
- Incremental / snapshot / change-file semantics.
- RDS upsizing, Redshift Spectrum, or fewer exception rows (separate work).
- Changing mapInPandas / processed parquet schema.

## Current state (baseline)

Today one Spark job:

1. Map → processed parquet (reusable).
2. Executors `COPY` clean adds into Postgres **and** write dirty JSONL to S3.
3. Driver streams dirty parts into Postgres, then reconcile.

Problems: Spark wall clock includes RDS; force reopen left `sse_loans` orphans; driver OOM when loading all dirty parts at once (fixed by per-part stream, still same job).

## Design

### Job 1 — `lbp-*-feed-spark` (compute only)

1. `prepare_large` (lease, config, preflight) — may touch DB for batch metadata only.
2. Map + write/reuse `s3://…/processed/batch_id={id}/` parquet (unchanged).
3. `foreachPartition`: for each chunk, classify clean vs dirty **without** querying `sse_loans`:
   - **DUP01** (in-file duplicate) stays in Spark (in-memory).
   - **DUP02** is **not** applied in Spark.
4. Write parts under `s3://…/bulk-load/{batch_id}/`:
   - Clean: **Parquet** (or CSV suitable for `COPY`) — staging + sse payload columns.
   - Dirty: **JSONL** — staging + exceptions (+ loans stubs if needed), same shape as today’s dirty parts.
5. Mark batch `staged` (or equivalent: Spark done, not completed). Exit **0**. No `COPY`, no exception OLTP.

### Job 2 — `lbp-*-feed-load` (DB only)

Prefer Glue **Python shell** (or small ETL with 1–2 workers) — not a Spark cluster. Same `lbp` wheel.

1. Require batch status `staged` (or force reopen with checkpoint 0).
2. Orphan wipe for this `batch_id` (checkpoint ≤ 0 path: delete all `sse_loans` / exceptions / staging for the batch).
3. Stream parts one at a time:
   - Load clean: `COPY` staging + `sse_loans`, applying **DUP02** against existing loans with `lbp_batch_id != batch_id` (divert those rows to exception path / dirty handling).
   - Load dirty: existing per-part `load_dirty_files` stream (`COPY` staging → resolve `staging_id` → `COPY` exceptions).
4. Reconcile; mark `completed` or `failed`.

Load is independently retryable: re-run Job 2 against existing `bulk-load/{batch_id}/` without Job 1.

### Orchestration

Update `boarding.asl.json` Spark branch:

```
GlueSpark (.sync) → GlueLoad (.sync) → Finalize → Outcome
```

- Spark failure → `MarkFailed` (do **not** fall through to `GlueStandard` for large tapes once this path is on — rematerialize Spark or operator restart). Optional later: Catch Spark → retry Spark only.
- Load failure → Step Functions retry Load (bounded); S3 parts remain.
- Manual: `mark_failed` + force checkpoint 0 clears DB; re-run Load if S3 intact, else Spark then Load.

Terraform: new `aws_glue_job.feed_load`, script `feed_load_job.py`, IAM + SFN template args, Lambda env `LBP_GLUE_LOAD_JOB` if needed for ops.

### Flags

- `LBP_SPARK_DB_FREE=1` (default **on** for Spark persist): Spark writes files only.
- Set `0` to keep today’s executor `COPY` clean path (rollback).
- Load job always DB; no flag required beyond batch status.

### Data layout

```
s3://{processed}/bulk-load/{batch_id}/
  clean/p-{uuid}/   # parquet or csv: staging + sse columns
  dirty/p-{uuid}/   # staging.jsonl, exceptions.jsonl[, loans.jsonl]
```

`begin_bulk` / load must clear both prefixes on full reopen.

## Success

- Unit: Spark persist path with DB free writes clean+dirty parts; load job boards a small fixture balanced with DUP02 diverted.
- AWS: Spark SUCCEEDED with near-zero RDS write volume during Job 1; Load alone completes `bat_5fe35379ee76` from existing S3 after a forced DB wipe; Load re-run after induced failure does not re-run Spark.
- Metrics: report Spark `ExecutionTime` and Load `ExecutionTime` separately (SFN result paths).

## Non-goals / honesty

- Expect Load wall clock on current RDS to remain on the order of hours for 10M / ~15M exceptions until RDS or exception volume changes.
- Spectrum / external tables deferred.
