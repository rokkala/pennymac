# Bulk file load for dirty Spark rows

## Goal

Stop Spark executors from OLTP-inserting held staging + exceptions. Glue writes COPY-ready files; one load step COPYs into Postgres. Clean-add `COPY` unchanged.

## Files

| File | Role |
|---|---|
| `backend/lbp/pipeline/loader.py` | `copy_insert_exceptions`; shared COPY helpers |
| `backend/lbp/glue_jobs.py` | Materialize dirty → files; `load_dirty_files`; wire `persist_partition` / `finalize` |
| `aws/glue/feed_spark_job.py` | After `foreachPartition`, call `load_dirty_files` before `finalize_bulk` |
| `backend/tests/test_bulk_file_load.py` | TDD for materialize + load balanced |

## Flow

1. `persist_partition`: clean → existing `_copy_clean_adds`. Dirty adds → triage in memory → write `staging.jsonl` + `exceptions.jsonl` (+ `loans.jsonl` for T1-fixed boards) under `{data_dir|s3}/bulk-load/{batch_id}/p-{uuid}/`. Update/close rows still use `_persist_chunk`.
2. Driver: `load_dirty_files(batch_id)` reads all part dirs → `copy_insert_staging` → resolve `staging_id` via `(batch_id, row_number)` → `copy_insert_exceptions` → `copy_insert_loans`.
3. `finalize_bulk` as today.

## Flag

`LBP_BULK_FILE_LOAD` default **on**. Set `0` to keep dirty path on `_persist_chunk`.

## Tasks

1. RED/GREEN: `copy_insert_exceptions` round-trip (SQLite fallback + shape).
2. RED/GREEN: materialize dirty partition to local dir; `load_dirty_files` balances a small batch with fails.
3. Wire Spark job; keep `test_persist_partition_then_finalize` green (file load on by default).
