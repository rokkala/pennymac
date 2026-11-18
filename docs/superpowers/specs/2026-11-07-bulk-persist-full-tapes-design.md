# Bulk persist for full Spark tapes

## Goal

Board very large **full** tapes (10M+) in tens of minutes by replacing per-chunk SQLAlchemy INSERT with **Postgres COPY** for clean adds, while keeping today’s `_persist_chunk` for failures, updates, and closes.

## Scope

- **In:** Glue Spark path after parquet exists (`persist_bulk`).
- **Out:** Changing incremental/snapshot/change-file semantics; rewriting mapInPandas.

## Design

1. Spark map + parquet unchanged (already ~7 min for 10M).
2. Driver streams parquet payloads **in row order**.
3. Consecutive **clean adds** (`PASS`/`WARN`, action add/None, no fails) flush via:
   - one DUP01/DUP02 check per flush (SQL `IN` lists + in-buffer seen set)
   - `COPY` into `sse_loans`
   - slim `loans_staging` rows (empty `record`/`raw`, `boarded=true`)
4. Everything else → existing `_persist_chunk`.
5. Checkpoint advances in order after each flush (same resume contract).
6. SQLite / non-psycopg: COPY falls back to executemany insert (tests stay green).

## Flag

`LBP_BULK_PERSIST` default **on** in `feed_spark_job.py`. Set `0` to force legacy `persist_stream`.

## Success

- Unit/integration: small onboarded file via `persist_bulk` completes balanced.
- AWS: restart 10M batch from existing parquet; finish without multi-hour JDBC crawl.
