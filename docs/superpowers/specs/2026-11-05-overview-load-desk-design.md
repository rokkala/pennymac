# Overview as boarding load desk

**Date:** 2026-11-05  
**Status:** approved (chat) — implementing on `feature/app-ux-phase-a`  
**Classification:** architectural (Overview IA)  
**Extends:** `2026-11-05-app-ux-full-rebuild-design.md` § Overview

## Intent

Overview is the **boarding load monitoring desk**: what’s due, late, running, or stuck — then open the same batch monitor modal used on Import Monitor. Executive charts demote to a collapsed “Portfolio signal.”

## Locked decisions

| Decision | Choice |
|---|---|
| Where monitoring lives | **Overview itself** (not a separate Load Monitor page) |
| Batch detail | Reuse existing `BatchModal` from Imports |
| Delivery without a batch yet | Compact **Delivery watch** modal (due / grace / status / link to Vendor Deliveries; pull/waive only if capability allows) |
| Charts | Collapse under **Portfolio signal** (closed by default) |
| Backend | No new APIs; use `/api/batches` + `/api/deliveries` (+ existing exception/ntf for queue cards) |

## Layout

1. PageHeader — “Boarding desk” / load-focused subcopy; primary CTA by role (upload / exceptions / deliveries).
2. Load health strip — Running · Late · Missed · Stuck (blocked/waiting/ooo/paused) · Open exceptions. `role="status"` for counts.
3. **Needs attention** — unified severity-sorted rows (deliveries + batches). Click → BatchModal or Delivery watch.
4. Your queues — existing workToday cards + late/running when counts > 0.
5. Portfolio signal — `<details>` with prior Overview charts.

## Non-goals

- Rewriting Import Monitor or Vendor Deliveries tables.
- New aggregate API.
- Second progress UI.

## Success

Ops (or any Run role) opens Overview and can open live batch progress / scheduled delivery context without hunting Import Monitor first.
