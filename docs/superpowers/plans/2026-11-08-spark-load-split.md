# Spark / Load Job Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split large-tape boarding into a DB-free Spark job (S3 materialize) and a separate Glue load job (streaming COPY + DUP02), chained in Step Functions.

**Architecture:** Spark `persist_partition` under `LBP_SPARK_DB_FREE=1` writes clean/dirty parts under `bulk-load/{batch_id}/` and marks the batch `staged`. New `feed_load_job` wipes orphans, loads clean (with DUP02), loads dirty, reconciles. SFN: `GlueSpark → GlueLoad → Finalize`.

**Tech Stack:** Python 3.11, Glue 5.0, existing `lbp` wheel, psycopg COPY, Step Functions ASL, Terraform.

**Spec:** `docs/superpowers/specs/2026-11-08-spark-load-split-design.md`

## Global Constraints

- Spark persist must not open Postgres when `LBP_SPARK_DB_FREE` is on (default on).
- Clean parts: JSONL under `clean/p-*` (`staging.jsonl` + `sse.jsonl`) — reuse existing COPY helpers; Parquet deferred.
- Dirty parts: JSONL under `dirty/p-*` (move today’s flat `p-*` layout).
- DUP02 runs only in the load job.
- Small-tape `lbp-feed` unchanged.
- Do not commit unless the user asks.

## Review Focus

- Load started while batch is still `running` (Spark not finished) → reject; expect only `staged` (or force reopen).
- Clean loan already in `sse_loans` from another batch → DUP02 divert to exceptions, not UniqueViolation.
- Force reopen with empty staging but leftover `sse_loans` → checkpoint≤0 wipe clears them before load.
- Spark DB-free path with update/close rows → written to `oltp/` for load `_persist_chunk`, not silent drop.
- SFN Spark failure must not fall through to `GlueStandard` for this path.

## Files

| File | Role |
|---|---|
| `backend/lbp/glue_jobs.py` | `_spark_db_free_on`, write clean/dirty/oltp parts, `mark_staged`, `load_clean_files`, `run_load_bulk` |
| `backend/lbp/store/db.py` | Document `staged` status |
| `aws/glue/feed_spark_job.py` | DB-free: no `finalize_bulk`; `mark_staged` after materialize |
| `aws/glue/feed_load_job.py` | New: call `run_load_bulk` |
| `aws/stepfunctions/boarding.asl.json` | GlueSpark → GlueLoad → Finalize |
| `aws/terraform/orchestration.tf` (+ iam/compute as needed) | `feed_load` job, SFN template var |
| `backend/tests/test_spark_load_split.py` | TDD for DB-free + load + DUP02 |

---

### Task 1: DB-free persist writes clean + dirty parts (no Postgres COPY)

**Files:**
- Modify: `backend/lbp/glue_jobs.py`
- Test: `backend/tests/test_spark_load_split.py`

**Interfaces:**
- Consumes: existing `_clean_add`, `_flag_dup`, `_write_dirty_part`, `_materialize_dirty_adds`
- Produces: `_spark_db_free_on() -> bool`; `_write_clean_part(batch_id, staging, sse_rows)`; `persist_partition` under DB-free skips `_copy_clean_adds` / executor COPY; layout `bulk-load/{id}/clean|dirty|oltp/p-*`

- [ ] **Step 1: Write the failing test**

```python
def test_persist_partition_db_free_writes_clean_and_dirty_without_sse(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    # process fixture rows; begin_bulk; persist_partition
    # assert sse_loans count for batch == 0
    # assert clean/ and dirty/ part dirs exist under data_dir/bulk-load/{bid}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_spark_load_split.py::test_persist_partition_db_free_writes_clean_and_dirty_without_sse -v`  
Expected: FAIL (no DB-free path / no clean parts)

- [ ] **Step 3: Implement DB-free branch in `persist_partition`**

- `_spark_db_free_on()`: env `LBP_SPARK_DB_FREE` default `"1"`.
- When on: DUP01 only in `_split_clean_dirty` (skip `sse_loans` query — pass `existing=set()` or split helper).
- Clean → `_write_clean_part` (JSONL); dirty adds → existing dirty writer under `dirty/`; T1 loans → dirty/clean files not COPY; update/close → `oltp/p-*/rows.jsonl`.
- `source_id` from broadcast cfg or one-time arg — prefer reading from `cfg` / batch row **before** partition loop on driver; executors receive `source_id` via broadcast (change `persist_partition(..., source_id=)` or stash on cfg). Minimal: keep one `connect()` for `source_id`+heartbeat only if unavoidable; prefer signature `persist_partition(batch_id, cfg, rows, checkpoint=0, source_id=None)` and require `source_id` when DB-free.
- Move `_write_dirty_part` paths to `dirty/p-*`; update `_list_dirty_part_names` / S3 prefix accordingly.
- When DB-free off: today’s behavior.

- [ ] **Step 4: Run test to verify it passes**

Run: same pytest command — Expected: PASS

- [ ] **Step 5: Commit** (only if user asked)

---

### Task 2: `mark_staged` + Spark job stops before load

**Files:**
- Modify: `backend/lbp/glue_jobs.py`, `backend/lbp/store/db.py` (status comment), `aws/glue/feed_spark_job.py`
- Test: `backend/tests/test_spark_load_split.py`

**Interfaces:**
- Produces: `mark_staged(batch_id: str) -> dict` sets `status="staged"`, clears `worker_id`, heartbeats; does not reconcile

- [ ] **Step 1: Write the failing test**

```python
def test_mark_staged_sets_status(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    # create batch, mark_staged(bid)
    assert _batch(bid).status == "staged"
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `mark_staged`; change `feed_spark_job.py`**

When `_spark_db_free_on()`: after `foreachPartition`, call `mark_staged(batch_id)` and print summary — **do not** call `finalize_bulk`.  
When off: keep `finalize_bulk` as today.

- [ ] **Step 4: Run — expect PASS**

---

### Task 3: `load_clean_files` + DUP02 divert + `run_load_bulk`

**Files:**
- Modify: `backend/lbp/glue_jobs.py`
- Test: `backend/tests/test_spark_load_split.py`

**Interfaces:**
- Consumes: `copy_insert_staging`, `copy_insert_loans`, `copy_insert_exceptions`, `load_dirty_files`, `_orphan_cleanup`, `_flag_dup` / exception materialization helpers
- Produces: `load_clean_files(batch_id: str) -> dict`; `run_load_bulk(batch_id: str, cfg) -> dict` (wipe → load clean → load dirty → oltp parts → reconcile/complete like `finalize_bulk`)

- [ ] **Step 1: Write the failing tests**

```python
def test_run_load_bulk_balances_db_free_batch(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    # persist_partition all rows; mark_staged; run_load_bulk
    assert _batch(bid).status == "completed" and _batch(bid).reconciliation["balanced"]

def test_load_clean_dup02_does_not_unique_violate(onboarded, monkeypatch):
    # insert sse_loans row for loan L from other batch; clean part contains L
    # load_clean_files / run_load_bulk → L not re-inserted; exception or diverted dirty exists
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

- `load_clean_files`: list `clean/p-*` (local+S3), per part read JSONL, query existing loans `lbp_batch_id != batch_id`, COPY non-dupes, divert DUP02 into exception rows (reuse dirty exception shape) then `copy_insert_exceptions` + staging as held.
- `run_load_bulk`: require status in `staged`|`failed` (force); `_orphan_cleanup(batch_id, 0)`; clear bulk-load local; `load_clean_files`; `load_dirty_files` (dirty prefix); process `oltp/` via `_persist_chunk`; then same reconcile/complete as `finalize_bulk`.
- `finalize_bulk`: if DB-free was used and called accidentally, either no-op dirty-only or delegate — prefer Spark never calls it; keep `finalize_bulk` for rollback path (`LBP_SPARK_DB_FREE=0`).

- [ ] **Step 4: Run — expect PASS**

---

### Task 4: Glue load script + Terraform + SFN

**Files:**
- Create: `aws/glue/feed_load_job.py`
- Modify: `aws/terraform/orchestration.tf`, `aws/terraform/iam.tf` (job ARN in policies), `aws/stepfunctions/boarding.asl.json`, `aws/terraform/compute.tf` / `main.tf` templatefile args as needed
- Test: syntax/`jq` on ASL; `terraform validate` if credentials allow

**Interfaces:**
- Produces: Glue job `${name}-feed-load`; ASL state `GlueLoad` after `GlueSpark`; Spark Catch → `MarkFailed` (remove fallthrough to `GlueStandard`)

- [ ] **Step 1: Add `feed_load_job.py`**

Mirror `feed_spark_job.py` env bootstrap; `getResolvedOptions(..., ["batch_id"])`; `prepare`/load cfg; `print(summary(run_load_bulk(batch_id, cfg)))`.

- [ ] **Step 2: Terraform `aws_glue_job.feed_load`**

Python shell or glueetl with 2 G.1X workers, VPC connection, same wheel args, timeout ≥ 480. Register script in `glue_scripts`. Pass `load_job` into SFN `templatefile`.

- [ ] **Step 3: Update `boarding.asl.json`**

`GlueSpark` Next → `GlueLoad` (.sync, `JobName: ${load_job}`, `--batch_id`).  
`GlueLoad` Next → `Finalize`.  
Spark `Catch` TaskFailed → `MarkFailed` (not `GlueStandard`).  
Load Catch → `MarkFailed`; Retry throttling like other Glue states.

- [ ] **Step 4: Validate**

`python3 -m json.tool aws/stepfunctions/boarding.asl.json`; terraform validate if possible.

---

### Task 5: Wire flags + graphify + AWS smoke notes

**Files:**
- Modify: `aws/glue/feed_spark_job.py` default args / terraform `default_arguments` for `--LBP_SPARK_DB_FREE=1`
- Run: `graphify update .`

- [ ] **Step 1: Ensure terraform/job args pass `LBP_SPARK_DB_FREE`**

- [ ] **Step 2: Run full unit slice**

`cd backend && .venv/bin/python -m pytest tests/test_spark_load_split.py tests/test_bulk_file_load.py tests/test_glue_jobs.py -q -k "not spark_job"`

- [ ] **Step 3: graphify update**

- [ ] **Step 4: Document manual AWS verify** (in plan checkbox notes, not a new md unless asked): upload wheel + scripts; apply TF; force reopen `bat_5fe35379ee76`; run Spark then Load separately; confirm Spark has no sse UniqueViolation and Load can retry alone.

---

## Self-review (done inline)

- Spec Job 1/2, DUP02-on-load, SFN chain, flags, layout, orphan wipe → Tasks 1–4.
- Clean format: JSONL chosen for COPY reuse (spec allowed CSV/Parquet alternative).
- Review Focus items mapped to Task 3 tests + Task 4 ASL Catch.
