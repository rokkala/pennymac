# Multi-file feeds: master/detail file sets

**In short:** some vendors send one delivery as several files: a **master** file with one row per loan, plus
**detail** files with many rows per loan (fees, escrow items, borrowers) linked by a key. A feed can declare
this shape as a **layout**. The platform then collects the files of one delivery into a **file set**, waits
until the set is complete, joins it into one row per loan, and loads it as **one batch** with the usual
mapping, rules, exceptions, approval, audit and replay. A feed with no layout is a single-file feed and works
exactly as before.

Phase 1 (this release) supports the `merge` and `aggregate` modes on the standard engine. The design is in
[superpowers/specs/2026-11-17-multi-file-feeds-design.md](superpowers/specs/2026-11-17-multi-file-feeds-design.md).

---

## 1. Concepts

| Term | Meaning |
|---|---|
| **Master** | The one file with one row per primary record (a loan). Its rows decide the loan count, and the joined output follows its file order. |
| **Detail** | Any other file of the delivery (a **role**, e.g. `escrow_items`). Its rows attach to master rows by key. |
| **Relation** | How one detail joins the master: key columns (`on`), key normalization, mode, and what to do with orphans, missing details, duplicate masters, and a low match rate. |
| **Mode** | `merge` (1:1): the detail's columns are added to the master row as `role.column`. `aggregate` (1:N): detail rows are reduced to the declared columns (`sum`, `count`, `min`, `max`, `first`, `last`, `any`, `concat_distinct`) under their `as` names. |
| **File set** | The files of one delivery. One set = one delivery = one sequence number = one batch. |
| **Readiness** | When a set is complete (`require`), how files are paired into a set (`pairing`), how long to wait (`wait_timeout_minutes`) and what happens then (`on_timeout`). |
| **Join stage** | Runs inside the batch before pre-flight and mapping. It joins the set once into `data_dir/joined/<batch_id>.csv`; the rest of the pipeline reads that file in place of the master. |

Mapping uses the joined columns: master columns keep their names, merged detail columns are `role.column`,
aggregate outputs use their `as` name. Phase 1 maps everything onto the existing `loan` entity (`sse_loans`).

## 2. Layout and readiness reference

The layout example from the design (Phase 1 accepts the `merge` and `aggregate` modes; `flatten` and `child`
are later phases):

```yaml
layout:
  files:
    - role: master            # exactly one master
      entity: loan
      name_pattern: "loans_(?P<date>\d{8})\.csv"
      key: [loan_id]
      required: true
      parse_options: {...}    # per-file (delimiter, header, sheet, encoding)
    - role: borrowers
      name_pattern: "borrowers_(?P<date>\d{8})\.csv"
      required: true|false
      columns: [...]          # optional: declared columns, checked per role in pre-flight
      parse_options: {...}
  relations:
    - detail: borrowers
      to: master
      on: [{parent: loan_id, detail: loan_ref}]
      normalize: [trim, strip_leading_zeros, upper]     # applied to both sides of every key part
      cardinality: one | many # merge is always one
      mode: merge | aggregate
      join: left | inner
      on_orphan_detail: exception | drop
      on_missing_detail: exception | allow
      on_duplicate_master: reject_all | first | last
      min_match_rate: 0.98    # below this the batch is blocked before any load
      aggregate: {columns: [{as: total_fees, op: sum, col: fee_amt, where: ..., order_by: ...}]}

readiness:
  require: all_required | master_only
  pairing: sequence | business_date | filename_token | window_minutes
  window_minutes: N           # only with pairing: window_minutes
  wait_timeout_minutes: N
  on_timeout: fail | load_master_only | alert_only
```

| Field | Default | Notes |
|---|---|---|
| `relations[].join` | `left` | `inner` drops masters without a detail, always as a JOIN06 exception, never silently. |
| `relations[].cardinality` | `one` for merge, `many` otherwise | |
| `relations[].normalize` | `[trim]` | Applies to the join key only; stored values keep their original form. `strip_leading_zeros` on `000` gives `0`. Empty or null key parts never match. |
| `on_orphan_detail` | `exception` | `drop` discards detail rows without a master (counted, no exception). |
| `on_missing_detail` | `allow` | `exception`: a master without a detail is excluded with JOIN02. |
| `on_duplicate_master` | `reject_all` | `first` / `last` keep one row; every dropped row is a JOIN03. |
| `min_match_rate` | `0.0` | See note (d) in section 7. |
| `relations[].to` | | Must be `master` in Phase 1 (a detail of a detail is a later phase). |
| `readiness.require` | `all_required` | `master_only` is accepted only when every detail is non-required. |
| `readiness.pairing` | `business_date` | `sequence`, `business_date` and `filename_token` all compare the captured value for equality. |
| `readiness.wait_timeout_minutes` | `240` | |
| `readiness.on_timeout` | `alert_only` | `load_master_only` is accepted only when every detail is non-required. |

Aggregate rules: with no `order_by`, `first`, `last` and `concat_distinct` use detail file order;
`concat_distinct` joins with `|` in first-seen order; `sum`, `min` and `max` ignore nulls and empty strings and
give null for a group with no values; `count` counts rows. `where` and `order_by` use the transform
expression grammar (`{"==": [{"var": "ItemType"}, "TAX"]}`). Two roles producing the same output column is a
validation error.

The demo feed's layout, as code, is `samples.master_detail_layout()`: a loan master plus `escrow_items`
aggregated into `tax_total`, `hazard_total`, `escrow_item_count` and `escrow_payees`.

## 3. Onboard a master/detail vendor

### In the web app

1. **Vendors & Mapping:** pick the vendor, "Add feed", and upload a sample of the **master** file. Map it as
   usual (Priya) but do not submit yet if you want to map detail columns (step 4).
2. **Delivery & schedule** tab: click "This feed arrives as several files…". The **File layout** tab opens.
3. **Files:** the master role (name pattern with a named group such as `(?P<date>\d{8})`, key columns), then
   one card per detail role (name pattern, required or not, declared columns if you know them).
   **Relations:** matching columns, normalizers, mode, policies, minimum match rate, aggregate columns.
   **Readiness:** require, pairing, timeout and timeout action.
4. **Join preview:** upload one sample per role. You see the match rate, per-role counts (read, matched,
   orphaned, rejected), the JOIN codes in words and the first joined rows with PII masked. A preview on a
   sample is a sanity check only (note (d)).
5. **Propose** the layout. A different SME (Dan) opens the feed and **approves** it; the same person cannot do
   both. Approval publishes a new signed feed bundle that carries the layout and readiness.
6. Map the joined columns (merged `role.column` names such as `escrow_items.ItemType`, aggregate outputs such
   as `tax_total`). In Phase 1 the workbench's column picker lists the sampled master columns only, and adding
   a field on a joined name is refused, so use the workaround in "Mapping joined columns in Phase 1" below.
   Then submit and approve the mapping as usual.

### Through the API

```bash
H='-H "X-User: priya" -H "X-Roles: onboarding"'
# 1. feed + mapping (as for a single-file feed): POST /api/sources, field edits, submit, approve
# 2. propose the layout (analyst or SME)
curl -X PUT localhost:8000/api/sources/$SID/layout -H "X-User: priya" -H "X-Roles: onboarding" \
  -H 'Content-Type: application/json' -d @layout.json          # {"layout": {...}, "readiness": {...}}
# 3. optional dry run on samples: one multipart part per role, named by the role
curl -X POST localhost:8000/api/sources/$SID/layout/preview -H "X-User: priya" -H "X-Roles: onboarding" \
  -F master=@loans_20261117.csv -F escrow_items=@escrow_items_20261117.csv
# 4. a different SME approves (publishes the bundle)
curl -X POST localhost:8000/api/sources/$SID/layout/decide -H "X-User: dan" -H "X-Roles: onboarding_reviewer" \
  -H 'Content-Type: application/json' -d '{"approve": true, "comment": "matches the vendor spec"}'
# 5. deliver: one file at a time (routed by name, or force a role with -F role=...) ...
curl -X POST localhost:8000/api/upload -H "X-User: maria" -H "X-Roles: ops" -F source_id=$SID -F file=@loans_20261117.csv
#    -> {"set_id": "...", "role": "master", "status": "waiting", "batch_id": null}
# ... or the whole delivery: several files, or one zip, with an optional manifest {role: filename}
curl -X POST localhost:8000/api/upload/set -H "X-User: maria" -H "X-Roles: ops" -F source_id=$SID \
  -F files=@delivery_20261117.zip -F 'manifest={"master": "loans_20261117.csv"}'
```

In Python the same steps are `multifile.service.propose_layout` / `decide_layout` and
`multifile.fileset.attach_file`; `tests/test_multifile_e2e.py` runs the whole flow.

**Mapping joined columns in Phase 1.** The mapping service checks a new field's source against the sampled
master file, so `add_field` refuses `role.column` and aggregate names. Add the field on any master column,
then change its source (`POST /api/mappings/{id}/fields/{target}` with `action: override` and
`sources: ["tax_total"]`), as `demo_setup.py` does.

## 4. Delivery scenarios

| Scenario | What happens |
|---|---|
| **Together** (one zip, or several files in one request, or files landing in one drop) | Every file is routed by its name (or the manifest) to its role and attached to one set. When the last required file attaches, the set is `ready`, then `consumed`: one batch is queued with the master as its `file_path` and the other roles in `batch_files`. |
| **Separate** (master in the morning, details at noon) | The first file opens a `waiting` set (Import Monitor and Vendor Deliveries show "Waiting for escrow_items file"). The second file with the same pairing value joins it and the batch is queued. No batch exists while the set waits. |
| **One missing** | The set waits until `wait_timeout_minutes`. Then the late/missed alert fires naming the missing role, and `on_timeout` applies: `alert_only` keeps waiting, `fail` expires the set, `load_master_only` queues the master alone (only when every missing detail is non-required). An SME can also accept the partial set with a reason (section 6). |
| **Mismatched dates** (`loans_20261117`, `escrow_items_20261118`) | Pairing never joins files whose pairing values differ. Each opens its own waiting set; stale details are never joined silently. Fix a misrouted file with a `repair` override. |
| **Re-sent** | The same file again for the same role of a waiting set changes nothing. A different file for that role replaces the member (audited `file_set.member_replaced`). The identical set again after it was loaded is refused as a duplicate (HTTP 409, `duplicate_of`). A re-sent file for a set that was already loaded opens a **new** set, which must be completed like any set (note (h) for S3). |

## 5. Troubleshooting by exception code

Join exceptions are in the Exception Manager with category `join`, the role chip and the code. They never
stop the join; the batch reports them in `reconciliation.join.exceptions`.

A join exception has no staged loan behind it (the row never reached staging), so its only action is
**Acknowledge and close…** with a mandatory reason (`POST /api/exceptions/{id}/acknowledge`, Monitoring or
Compliance; audited `exception.join_acknowledged`). It closes that one exception as `resolved`; nothing is
loaded or rejected and nothing is added to precedent memory. Value resolve, bulk resolve, reject-loan,
compliance clear and AI suggest are refused for join exceptions. To load the excluded masters, fix the files
and send the set again.

| Code | Meaning | What to do |
|---|---|---|
| **JOIN01** orphan detail | A detail row whose key matches no master row (only when `on_orphan_detail: exception`). Recorded on the detail role and its row number. The master rows still load. | Check the key columns and `normalize` (case, zero padding, spaces). If the vendor routinely sends extra rows, set `on_orphan_detail: drop`. If whole loans are missing from the master, ask the vendor for a corrected master. |
| **JOIN02** required detail missing | A master row with no detail row, under `on_missing_detail: exception`. The master is excluded. | Confirm with the vendor; re-send a corrected set, or relax the policy to `allow` through a layout change. |
| **JOIN03** duplicate master key | Two or more master rows normalize to the same key. `reject_all` excludes them all; `first` / `last` keep one and record the others. | Fix the master file; check that `normalize` is not merging distinct keys. |
| **JOIN04** cardinality violation | More than one detail row for a master under `merge` (or `cardinality: one`). The master is excluded rather than picking one silently. | If 1:N is legitimate, change the relation to `aggregate`. Otherwise the vendor must remove the duplicates. |
| **JOIN05** key unparseable | An empty or null key part, on either side. The row is rejected (a master row is excluded). | Fix the source rows; a blank key never matches by design. |
| **JOIN06** inner join dropped the master | `join: inner` and the master has no detail. Always recorded. | Expected under `inner`; use `left` if those masters should load. |
| **JOIN07** aggregate value not numeric | A `sum` / `min` / `max` source value is not a number. `$` and thousands separators (`1,234.50`) are accepted; a decimal comma (`1,5`, `12,50`, `1.234,5`) is not numeric. The value is skipped; the master still joins. | Fix the detail file or add a `where` filter. The value itself is not in the message. |

A batch **blocked** before any load has one of two reasons: a role's file is missing declared or referenced
columns (pre-flight per role, the role is named), or a relation's match rate is below `min_match_rate`. Both
are overridable by an SME with a reason ("Override and run…", `POST /api/batches/{id}/override-preflight`); the joined
file is kept, so the resumed batch loads exactly what was checked.

## 6. Operations

**File-set states.**

| State | Meaning |
|---|---|
| `waiting` | Opened by its first file; waiting for the other required files. |
| `ready` | Complete (or released by `load_master_only`); its batch is being queued. |
| `consumed` | Its batch is queued; the set is closed. |
| `expired` | Timed out under `on_timeout: fail`. A late file opens a new set. |
| `overridden` | Accepted partial by a person; its batch is being queued. |
| `discarded` | Discarded by a person, emptied by a repair, or a duplicate of an earlier set. |

**Overrides** (`onboarding_reviewer`, `compliance_reviewer` or `admin`; a reason is required; audited
`fileset.override`): in the file-set panel of Import Monitor / Vendor Deliveries, or
`POST /api/file-sets/{set_id}/override` with

- `accept_partial` (waiting or expired set with a master): queue the batch with the files present. Missing
  details join as empty files and follow `on_missing_detail`. Their relations are exempt from `min_match_rate`
  (the override already accepted the missing file), so no second override is needed; relations whose detail
  file is present are still gated.
- `discard`: close the set without loading.
- `repair` (`target_pairing_key`, optional `member_role`): move a file to the set with another pairing value,
  before the batch is queued.

`GET /api/file-sets?source_id=&status=` lists sets with members, row counts, pairing value and expiry.

**Timeouts and alerts.** The scheduler tick sweeps sets past `wait_timeout_minutes` once each: it raises
`delivery_late` (`alert_only`) or `delivery_missed` (`fail`, `load_master_only`), naming the missing roles,
then applies `on_timeout`. A handled timeout is recorded in the set's `override.timeout` and its `expires_at` is
cleared, so the sweep never selects that set again: under `alert_only` the set stays `waiting` (no further
alerts or per-tick work) and a late file still completes it. The sweep also re-queues any ready set whose
batch could not be queued earlier, unattended (like S3 and scheduled arrivals): a set whose batch cannot be
sequenced, or whose vendor is suspended, becomes a **failed batch** with the reason and the set ends
`consumed`. Any other persistent failure keeps the set `ready` and is retried each tick, but is recorded on
the set, audited (`file_set.error`) only when its message changes, and alerted once (`file_set_error`).

**Load type.** File-set batches load as `full` in Phase 1. A layout cannot be proposed for a feed whose
delivery profile is `snapshot` or `incremental`, and a set batch with such a load type is refused (an
unattended arrival records it as a failed batch). `POST /api/upload` to a layout feed refuses
`allow_duplicate`, `reason` and `load_type` (HTTP 400) instead of ignoring them.

**Publishing.** Approving a layout publishes a new signed bundle. If the publish fails, the approval is kept
and the decision returns HTTP 502 saying so; republish with `POST /api/sources/{id}/publish`. Until then the
feed refuses files (uploads 400, S3 arrivals alerted, pulls recorded as errors): a feed with an approved
layout is never treated as a single-file feed.

**Counts.** A batch's `reconciliation.join` holds master rows read, rows excluded by the join, joined rows,
and per role: rows read, matched, orphaned, rejected. The primary count stays the master ("40 loans").

**Replay** of held loans of a file-set batch re-reads the stored joined file (never the master alone); if the
joined file is gone, replay refuses.

**Scale.** The local join keeps memory bounded with SQLite temp tables. `tests/test_join_scale.py` (marked
`slow`, run with `pytest -m slow tests/test_join_scale.py`, size via `LBP_SCALE_ROWS`) joins 1,000,000
masters with 10,000,000 detail rows; on an Apple Silicon laptop it took 72.5 s with a peak RSS of 93 MiB.

## 7. Behavior notes and limits

- **(a)** `name_pattern` is a regular expression applied with fullmatch to the bare filename. Named capture
  groups supply the pairing value. The group names are irrelevant, but the VALUES must match across roles
  (for example the same date).
- **(b)** `require: all_required` means wait for every declared file until the wait timeout. The `required`
  flag only governs whether a partial load is allowed on timeout (`load_master_only` needs every missing
  detail to be non-required). `master_only` releases a set on the master alone, and S3 arrivals come in any
  order, so an S3-fed `master_only` feed can release before its detail.
- **(c)** A merge relation always has cardinality one (the default for merge), and more than one detail row
  per key is a cardinality violation (JOIN04, master excluded).
- **(d)** The match-rate gate uses each relation's master-side rate (master rows with at least one matching
  detail over master rows) and, with `on_orphan_detail: exception`, also the detail-side rate. Rates measured
  on a preview sample are not reliable.
- **(e)** JOIN02, JOIN03, JOIN04 and JOIN06 exceptions are recorded with role `master` and the master's row
  number.
- **(f)** The join key of an exception (`loan_number`, and `key` in the preview) is a keyed fingerprint:
  `tok_` + 12 hex characters of HMAC-SHA256 under a key derived from the server's config-signing secret, so it
  cannot be recomputed from a guessed key without that secret. It is deterministic per deployment (equal keys
  give equal tokens). Raw rows in exceptions and in staged `raw` are masked by PII type (profile, mapping,
  column names, and for detail or aggregate columns of unknown type, values that look like an SSN, email or
  phone); a key column that is not detected as PII stays readable in the raw row, and a partially masked
  PII key keeps its last four characters.
- **(g)** The joined file is reused on resume even if the layout has changed since.
- **(h)** S3 redelivery of the last file of an already loaded set opens a new waiting set that later times out
  and alerts.
- **(i)** Scheduled pulls for a layout feed need a placeholder glob `pattern` on the schedule; the layout's
  name patterns decide routing.
- **(j)** File-set batches run on the standard engine, never on Glue/Spark, in Phase 1. Replay re-runs from
  the stored joined file.
- **(k)** The client form's role-name rule is stricter than the server: lowercase letters, digits and
  underscore, starting with a letter.
- **(l)** Phase 1 limits: modes `merge` and `aggregate` only, every relation joins the master, and file-set
  batches load as `full` (flatten, child records, Spark parity, relation trees and snapshot/incremental sets
  come in later phases). PostgreSQL was not exercised in this work (SQLite only), and the new
  migration 0007 should be run against PostgreSQL before production. The old dev DB needs
  `python -m lbp.cli migrate`.
- **(m)** A relation whose detail role is absent (accepted as missing by an `accept_partial` override, or
  released by a `load_master_only` timeout; listed in `join_summary.absent_roles`) is exempt from the
  `min_match_rate` gate. The exemption never applies to a relation whose detail file is present. The empty
  file an absent role joins against also carries the role's columns the mapping reads (`role.col` sources), so
  the drift pre-flight does not report them as missing and no second override is needed.
- **(n)** The mapping service validates new fields against the sampled master columns only; see "Mapping
  joined columns in Phase 1" in section 3.

## 8. Demo

`demo_setup` adds **PennyMac Retail (PCG) / Escrow items feed (two files)**: yesterday's loan + escrow items
set is loaded (with a few JOIN01 orphans), and today's loan file waits for its escrow items file. Upload
`demo_uploads/3_multi_file/escrow_items_<today>.csv` to the feed to complete the set. The files come from
`samples.generate_master_detail(dir, n)`: about 3 escrow items per loan, every 10th loan without items, a few
orphan items, and loan numbers spelled with lower case, leading zeros or spaces in about 30% of the items.
