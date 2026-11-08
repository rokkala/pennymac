# Bulk Persist Full Tapes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `persist_bulk` so Spark full tapes COPY clean adds into `sse_loans` instead of OLTP micro-batch inserts.

**Architecture:** Stream ordered Spark results; flush clean-add runs with COPY + slim staging; route non-clean rows through `_persist_chunk`; same checkpoint/reconcile completion as today.

**Tech Stack:** Python, SQLAlchemy, psycopg COPY, existing Glue Spark job.

**Spec:** `docs/superpowers/specs/2026-11-07-bulk-persist-full-tapes-design.md`

## Global Constraints

- No new dependencies.
- SQLite tests must pass (COPY fallback).
- Checkpoint resume remains idempotent (orphan cleanup at start).

## Review Focus

- DUP02 loans must not be COPY’d into `sse_loans`.
- Interleaved FAIL rows still board via `_persist_chunk`.
- Reconcile `balanced` after slim staging.
- `LBP_BULK_PERSIST=0` keeps legacy path.

## Task 1: COPY helper + persist_bulk

- [ ] Write failing test `test_persist_bulk_boards_clean_adds` in `backend/tests/test_glue_jobs.py`
- [ ] Add `copy_insert_loans` in `loader.py`
- [ ] Add `persist_bulk` in `glue_jobs.py`
- [ ] Wire `feed_spark_job.py` to call `persist_bulk` when enabled
- [ ] Run targeted pytest; upload wheel + script; restart 10M Glue from parquet
