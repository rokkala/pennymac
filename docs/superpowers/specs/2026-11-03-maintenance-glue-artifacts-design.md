# Maintenance · Glue artifacts (in-app viewer)

**Date:** 2026-11-03  
**Status:** Draft for review  
**Scope:** Phase 1 — read-only browse of Glue job scripts, shared entrypoints, and Glue notebooks inside the Loan Boarding Console.

## Intent

Operators and demo walkthroughs can open Glue-related source **inside the app** under **Maintenance**, without leaving for AWS Studio or Git. Production still runs jobs via Glue/Step Functions; this page does not execute or deploy anything.

## Audience and access

- Rail item visible when the persona can use capability `readMaintenance` → roles **`sme`**, **`admin`** (same rule as other platform guts: Dan / Platform Admin).
- Others: nav item hidden (consistent with CAPS hide-unavailable).

## Catalog (allowlist only)

Fixed manifest in the backend (not a free filesystem browser):

| id | title | path (repo-relative) | kind |
|----|--------|----------------------|------|
| `feed-job` | Glue job `lbp-feed` | `aws/glue/feed_job.py` | `python` |
| `feed-spark-job` | Glue job `lbp-feed-spark` | `aws/glue/feed_spark_job.py` | `python` |
| `vendor-pull-job` | Glue job `lbp-vendor-pull` | `aws/glue/vendor_pull_job.py` | `python` |
| `glue-jobs` | Shared entrypoints `lbp.glue_jobs` | `backend/lbp/glue_jobs.py` | `python` |
| `nb-feed-workbench` | Notebook · feed workbench | `aws/glue/notebooks/feed_workbench.ipynb` | `notebook` |
| `nb-rule-lab` | Notebook · rule lab | `aws/glue/notebooks/rule_lab.ipynb` | `notebook` |

Any path outside this list is rejected (404). Paths are resolved from the repo root (or a configured `LBP_REPO_ROOT`); traversal (`..`) is forbidden.

## UI

- New page **Maintenance** in the rail (after Policy & Audit). Eyebrow e.g. “Platform · data plane”.
- Layout: list of artifacts (title + kind chip) → select one → viewer panel.
- **Python:** monospace `<pre>` / existing `.code` styling; show path and short subtitle from file docstring first line when available.
- **Notebook:** render cells in order — markdown as HTML-safe text (plain or light markdown), code cells as `<pre>`; skip/collapse bulky binary outputs (show “output omitted” if present).
- Callout: “Read-only. Production runs Glue jobs started by Step Functions or the API; notebooks are development-only and never board loans.”
- Same visual language as the rest of the console (no new design system).

## API

- `GET /api/maintenance/artifacts` → `{ artifacts: [{ id, title, path, kind }] }`  
  Roles: `sme`, `admin` (via `ROUTE_ROLES` + frontend `canCap`).
- `GET /api/maintenance/artifacts/{id}` → `{ id, title, path, kind, content }`  
  - `python`: `content` is UTF-8 text.  
  - `notebook`: `content` is parsed JSON cells `{ cell_type, source }` only (strip outputs to keep payloads small), or raw notebook JSON with outputs stripped server-side.

Demo / mock API: same shape with inlined content from the allowlist (or short stubs if packaging size is a concern — prefer real file text when the mock can load it).

## Non-goals (Phase 1)

- Editing files, saving back to disk, or committing.
- Running notebooks or starting Glue jobs from this page.
- Terraform / Step Functions ASL / Lambda handlers (can be a later catalog expansion).
- Syntax highlighting library (optional later; monospace is enough).

## Testing

- Backend: allowlist reject unknown id; no `..` path escape; happy path returns feed_job content.
- Frontend: `canCap(readMaintenance)` gates nav; SME sees page, reviewer does not.
- `node`/`pytest` checks as appropriate for the repo’s existing harness.

## Success

An SME can open Maintenance, click `lbp-feed` and a notebook, and read the same source as in `aws/glue/` without leaving the console.
