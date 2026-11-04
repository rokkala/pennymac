# Incremental loads, vendor sequencing and the delivery scheduler

## 0. Vendors and feeds

* A **vendor** is the counterparty, for example a correspondent, bulk seller, sub-servicer or internal channel.
* A vendor owns one or more **feeds**. A feed is one file layout with its own mapping versions, delivery profile, schedules and file numbering.
  * Example: Cornerstone Servicing has a *Boarding tapes* feed (full) and an *Intraday change files* feed (incremental).
* The side-bar vendor selector scopes every operational page and API listing (`?vendor_id=`).
* Integrity rules at vendor level:
  * A change file may only change loans that belong to the same vendor. Otherwise it raises **CHG06**, which goes to dual control and applies only for a documented servicing transfer; the loan then moves to the new vendor.
  * A snapshot is compared with the vendor's whole active portfolio across all its feeds.
  * A suspended vendor's files are recorded but not processed.

## 1. What each vendor sends

Every feed has a **delivery profile** (Sources → *Delivery & schedule*). A change to the profile only takes effect once a second SME approves it.

| Load type | Meaning | What the platform does |
|---|---|---|
| `full` | A complete boarding tape (the default) | Same as before: new loans, with DUP02 re-board protection |
| `incremental` | Change rows: add / update / close | Plans each row against the loan's live SSE record (see §2) |
| `snapshot` | The vendor's whole current portfolio | Compares the file with SSE to find adds, updates, unchanged rows and missing loans (see §3) |

An incremental row says what it is in one of three ways:

* **Action code column**, for example `N` = add, `C` = update, `P`/`T` = close.
* **File-name pattern**, for example `_NEW_` / `_CHG_` / `_PIF_`.
* **Nothing**: the row updates the loan if it is in SSE, otherwise adds it.

An Ops user can override the load type for a single upload.

## 2. Applying a change safely

1. **Merge, then validate.** The vendor's delta is laid over the live SSE record, and the merged record goes through the full rule set and the SSE schema checks.
   * A blank cell means "no change", or "clear" if the profile says so. `clear_token` (for example `#CLEAR`) explicitly empties a field.
   * Sparse files are fine: loan number plus changed columns. The pre-flight blocks only if the loan-number or action column is missing.
2. **Only real changes count.** Values are compared after type normalisation and after the same automatic fixes applied at boarding.
   * A row identical to SSE is `unchanged`. Nothing is written, and only a slim marker row is staged.
   * A vendor re-sending a defect that a reviewer already corrected (`corrections_kept`) does not undo the correction.
3. **Change control.**
   * A change to a protected field raises **CHG01** and goes to maker + checker (T4). Protected fields cover identity, rate, investor, HMDA and property. A rate change on an ARM loan is routine.
   * Original terms (`set_once_fields`) are never overwritten by change files. A vendor `NoteRate` column that also feeds `original_interest_rate` cannot rewrite the original rate.
4. **Pre-existing issues don't block.** If a rule already failed on the boarded record and this change doesn't touch that field, the update still applies. The issue is counted, not raised again.
5. **Write only what changed, under optimistic concurrency.**
   * Each SSE row has `lbp_version`. At write time the live rows are locked. If the version moved since the delta was computed, the delta is rebased.
   * A field is a conflict only if SSE now differs from both the value the vendor saw and the value it sent.
   * Conflicts are held as **CHG05** for a person to decide. Non-overlapping changes merge.
6. **Closes never delete.** The row is marked `lbp_status = closed` with a date and reason.
7. **Every applied change is logged** in `loan_changes` (old → new, NPI masked). It is visible per file and per loan (`/api/loans/{loan}/history`).
8. **Reconciliation:** source rows = applied + held + rejected + unchanged. Every applied update or close must appear in the change log.

### Exceptions raised by change files

| Rule | When | How a reviewer resolves it |
|---|---|---|
| CHG01 | Protected field changed | Apply the vendor value, keep the SSE value and apply the rest, or reject (T4) |
| CHG02 | Update or close for a loan not in SSE | Enter the correct loan number. The change is merged onto that loan and protected fields are still checked |
| CHG03 | Change for a closed loan | Reopen and apply, or reject |
| CHG04 | Loan missing from a snapshot | Confirm closed, or keep active |
| CHG05 | Concurrent change | Keep the SSE value or apply the vendor's |
| CHG06 | Loan belongs to another vendor | Approve as a documented servicing transfer (maker + checker), or reject |
| ACT01 | Unknown action code | Apply with the default action, or reject; then add the code to the profile |

Held changes resolve in the Exception Manager and are re-applied to the *live* record, so resolving an old file's exception after newer files have landed is safe. Replay is for full tapes only.

## 3. Snapshots

* Rows are planned as adds or updates, and an identical row is `unchanged`.
* Active loans of that vendor (across all its feeds) that are absent from the file become **CHG04** close reviews (T3; bulk resolve is allowed).
* If more than `max_missing_pct` (default 5%) of the portfolio is absent, the file is treated as **truncated**:
  * No reviews are raised.
  * The batch is flagged and an alert is sent.
  * After checking with the vendor, an SME can raise the reviews anyway.
* A large update count is explained per file (`fields_changed`). For example, a new mapping version backfilling a field shows which field changed on how many loans.

## 4. Per-vendor file order

* The sequence comes from the file name (a regex with one capture group) or from a column. It is either a running number or a date.
* The gate and the processing lease run in one transaction behind a row lock on the source. Two workers can never both decide "my file is next" (tested on PostgreSQL with 8 racing workers).

| Situation | Status | Resolution |
|---|---|---|
| An earlier file of this vendor is still pending | `waiting` | Released automatically when that file completes |
| Integer gap (file 44 arrives, 43 never did) and the profile is strict | `waiting` | 43 arrives; or Ops skips the gap with a reason |
| File is not newer than the last applied one | `out_of_order` | An SME discards it, or applies it with **every** change held for dual control |
| Same sequence as a pending file | Refused at arrival | Discard the pending one first |

The vendor's applied cursor (`sources.last_sequence`) only moves forward. It moves in the same transaction that completes the batch.

## 5. The delivery scheduler

File arrival stays **event-driven**: a file is processed the moment it lands. The scheduler watches deadlines and pulls files for vendors that don't push. It never delays processing.

### Schedules

A schedule is a 5-field cron expression evaluated in the vendor's IANA timezone, so 06:00 New York stays 06:00 across daylight-saving changes. It runs on a business calendar: US Federal Reserve holidays, with "skip" or "next business day". It also sets these options:

* grace (late after)
* miss-after
* how early a file is accepted
* files per delivery
* an optional filename filter
* the load type for pulled files

### Deliveries

Each due time becomes a delivery, which moves through these states:

* `expected` → `received` (on time) or `late` (alert once) → `missed` (alert once) → `received_late`
* `waived` when Ops records a reason, which stops the alerts

A file is matched to the oldest still-live window. If none is live, it matches the window that just passed, if that window was missed. Otherwise it is an unscheduled arrival. A file today never fills a gap from weeks ago.

### Pull connectors (`scheduling/pullers.py`)

| Connector | Details |
|---|---|
| SFTP | Pinned host key (SHA-256) is mandatory: an unknown or changed key is refused before any credential is sent. Credentials are read from Secrets Manager under `<name>/vendors/`. |
| Vendor S3 | Optional cross-account role. |
| Drop folder | For local use, or an EFS-mounted SFTP gateway. |

Guardrails for every connector:

* Hosts and buckets must be on `LBP_PULL_ALLOWED_HOSTS` (Terraform: `vendor_sftp_hosts`, `vendor_pull_buckets`).
* Egress on tcp/22 opens only to `vendor_sftp_cidrs`.
* Only allowed file types and sizes are fetched; files still being written are retried.
* Each remote file is fetched exactly once.
* Remote files are never deleted.

In AWS, pulled files are written to the raw zone, where the normal arrival event registers them.

### Running the tick

| Environment | How the tick runs |
|---|---|
| AWS | EventBridge Scheduler (`rate(5 minutes)`) → `scheduler_tick` Lambda (reserved concurrency 1); due pulls start the `lbp-vendor-pull` Glue job |
| Local | The API process ticks every minute; the worker ticks when `LBP_SCHEDULER_ENABLED=true` |
| Manually | `python -m lbp.cli tick` |

The tick is safe to run concurrently:

* a database leader lease admits one tick at a time
* deliveries are unique per (schedule, due time)
* alerts are stamped once, after commit

A **dead-man's-switch alarm** pages if no tick has run for 15 minutes; a second alarm pages if ticks keep failing.

### Governance

* Schedules and delivery profiles are configuration with consequences (alerts, ordering, outbound connections). Create and change both follow maker-checker: the proposer cannot approve.
* Timing changes drop only *future* expected windows. History is kept.
* All actions are in the hash-chained audit log.

## 6. Evidence

| Check | Result |
|---|---|
| Incremental throughput | 47,757 sparse updates applied in 17.6 s (2,713 rows/s, 2 workers, SQLite), reconciliation balanced. Same rate as full boarding. |
| Tests | `test_incremental.py` (sparse updates, closes, CHG01–05, ACT01, rebase on conflict, loan-number correction, gap/skip/out-of-order, pre-existing issues, snapshot diff and truncation guard, kept corrections) |
| | `test_scheduler.py` (cron, DST, Fed holidays, delivery lifecycle, alerts once, leader lease, matching, maker-checker, local and S3 pulls) |
| | `test_sftp_pull.py` (real in-process SFTP server: host-key pinning, Secrets Manager credentials) |
| | `test_lambdas.py` (Step Functions path with a waiting file released by reconcile) |
| | `test_concurrency.py` (sequencing gate race on PostgreSQL) |
| | `test_api.py` (endpoints and role matrix) |
| | Migration `0002` round-trips on PostgreSQL with no model drift |
