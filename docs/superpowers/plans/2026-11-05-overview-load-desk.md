# Overview load desk Implementation Plan

> **For agentic workers:** Native execution on `feature/app-ux-phase-a`. Steps use checkbox syntax.

**Goal:** Make Overview the boarding load monitoring desk per `docs/superpowers/specs/2026-11-05-overview-load-desk-design.md`.

**Tech:** React SPA, existing `BatchModal`, `/api/batches` + `/api/deliveries`, pure helpers + node:test.

## File map

| File | Responsibility |
|---|---|
| `frontend/src/loadDesk.js` | Pure: health counts + attention rows from batches/deliveries |
| `frontend/src/loadDesk.test.js` | Unit tests for sort/severity |
| `frontend/src/workToday.js` | Add late/running queue cards |
| `frontend/src/pages/Overview.jsx` | Desk UI + modals |
| `frontend/src/pages/Imports.jsx` | Keep exporting `BatchModal` (no behavior change) |

## Tasks

- [x] T1: `buildLoadHealth` + `buildAttentionRows` + tests
- [x] T2: Overview desk layout, DeliveryWatch modal, BatchModal wire-up, collapse charts
- [x] T3: workToday late/running cards + tests; push branch (no PR)
