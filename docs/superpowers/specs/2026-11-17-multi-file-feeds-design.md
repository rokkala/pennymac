# Multi-file feeds: master/detail file sets, joins and child records

Status: draft for approval. Date: 2026-11-17.

## Intent

Today a feed delivers one file, and a batch is one file. Vendors also send a **master** file (one row per
primary record, e.g. a loan) plus one or more **detail** files (many rows per master: borrowers, fees,
payments) linked by a key. The platform must accept such a **file set**, wait until it is complete, join it,
and load the result, with the same maker-checker approval, audit, exceptions, replay and Glue scale as a
single-file feed.

This is a **framework**, not a loan feature. The join, readiness and child-record machinery must contain no
loan-specific code; "loan", "borrower" and the SSE schema are configuration (the default entity pack).

## Goals

- A feed declares **files** (roles) and **relations** between them; one file set = one batch.
- Support every practical delivery shape:
  - Arrival: together (zip/one drop), separate files same day, one missing, mismatched dates.
  - Detail shape: 1:1 merge, 1:N flattened to columns, 1:N aggregated onto the master, 1:N loaded as
    **child records** in their own target tables.
  - Data problems: orphan details, masters without details, key-format mismatches, duplicate master keys,
    details far larger than the master.
- Same semantics on the local engine (SQLite/Postgres) and on Glue/Spark, proven by shared golden fixtures.
- Everything configurable in the web app, approved by maker-checker, compiled into the signed feed bundle.
- Single-file feeds behave exactly as today (no layout declared = legacy path).

## Non-goals

- A general ETL graph: unions, filters, arbitrary expressions between files. Only key normalization,
  join, flatten, aggregate and child load.
- Changing how existing single-file feeds, delivery profiles, or the SSE loan schema work.
- Vendor-side bundling or format conversion beyond zip + manifest.
- Streaming/real-time ingestion.

## Anti-goals (a failure even if it technically works)

- Loan-specific names or fields in the join, readiness or entity code.
- A silent partial load. Loading with a file missing, or with unmatched rows, must be an explicit policy or
  a recorded override with a reason, never a default accident.
- Local and Glue giving different joined output for the same files.
- NPI from detail files reaching logs, error messages or unmasked exception rows.
- Regressions or new required config for existing single-file feeds.

## Constraints from the existing system

- The data plane (Glue) reads only the signed feed bundle (`config_store.py`). Layout, relations and
  per-entity mappings must be compiled into the bundle and approved like a mapping.
- Batches checkpoint by row index and resume. The joined stream must therefore be **deterministic**:
  output follows master file order; child/detail rows keep detail file order within a master.
- One DB abstraction supports SQLite, PostgreSQL and SQL Server (`store/db.py`); new tables must work on all.
- `sse_loans` is one flat row per loan generated from `sse_target.ATTRIBUTES`; borrower fields are columns.
- Sequencing gate, delivery schedules, late/missed alerts and pulls assume one file per delivery.
- Pre-flight, profiler, replay and the Mapping UI look at one file's columns.

## Approaches considered

| | A: pre-join before the pipeline | **B: file sets + join stage in the pipeline (chosen)** | C: general ETL graph |
|---|---|---|---|
| Idea | Produce one flat file, run today's pipeline | Feed declares files and relations; batch = file set; join is a pipeline stage | Visual flow of arbitrary joins/unions/filters |
| Covers all situations | No (no wait-for-both, fan-out, child tables) | Yes | Yes, and much more |
| Cost | Smallest | Medium, phased | Largest, a different product |
| Verdict | Rejected: logic duplicated per engine, no child records | Chosen by the user | Rejected: out of scope |

## Design

### 1. Entities (the generic target)

An **entity** is a named record type: `name`, `key` (attribute names), `attributes` (the existing
`TargetAttribute` metadata: dtype, length, required, risk, pii, codes, synonyms), and a target table.

- The current SSE schema becomes the default **entity pack**: entity `loan` -> table `sse_loans`
  (unchanged, same columns).
- A feed may declare **child entities** (e.g. `borrower`, key = parent key + child key). Their tables are
  generated from the attribute definitions, named `sse_<entity>`, with columns for the parent key,
  child key, and the same `lbp_*` audit columns as `sse_loans`.
- Entity definitions live in config (versioned with the feed bundle), not in Python constants. How the
  entity pack is stored and edited is left to the builder, but it must be possible to add an entity without
  a code change.

### 2. Feed layout and relations

A feed may declare a **layout**. Without one, the feed is single-file (legacy).

```
layout:
  files:
    - role: master            # exactly one master
      entity: loan
      name_pattern: "loans_*.csv"
      key: [loan_id]
      required: true
      parse_options: {...}    # per-file (delimiter, header, sheet, encoding)
    - role: borrowers
      name_pattern: "borrowers_*.csv"
      required: true|false
      parse_options: {...}
  relations:
    - detail: borrowers
      to: master              # parent role (a relation tree; see phase 5)
      on: [{parent: loan_id, detail: loan_ref}]
      normalize: [trim, strip_leading_zeros, upper]     # applied to both sides of every key part
      cardinality: many       # one | many
      mode: merge | flatten | aggregate | child
      join: left | inner
      on_orphan_detail: exception | drop
      on_missing_detail: exception | allow
      on_duplicate_master: reject_all | first | last
      min_match_rate: 0.98    # below this the batch is blocked (as a pre-flight block)
      # mode-specific:
      flatten:   {order_by: [...], max_n: 2, slot_pattern: "{role}_{n}_{col}", on_overflow: fail | warn_drop}
      aggregate: {columns: [{as: total_fees, op: sum|count|min|max|first|last|any|concat_distinct, col: fee_amt, where: ..., order_by: ...}]}
      child:     {entity: borrower, child_key: [borrower_seq], on_child_fail: hold_parent | load_parent_flagged | ignore}
```

- **merge** (1:1): detail columns are added to the master row, namespaced `role.column`. A duplicate detail
  key under `cardinality: one` is a cardinality violation (exception, not a silent first-wins).
- **flatten**: first `max_n` ordered detail rows become `slot_pattern` columns; overflow follows `on_overflow`.
- **aggregate**: detail rows are reduced to the declared columns on the master row.
- **child**: detail rows are not merged into the master. Each becomes a record of the child entity with its
  own mapping, rules, exceptions and target table, linked by the parent key and loaded with the parent batch.

### 3. Mapping and rules across entities

- Mapping source fields are addressed as `role.column` (flattened and aggregated columns appear under
  their declared names). The Mapping UI groups columns by role.
- A feed has one mapping **per entity** (master entity + each child entity), each versioned and approved.
  The bundle contains all of them; the `mappings` table gains an `entity` discriminator.
- Rules are scoped to an entity (default: the master entity, so existing rules are unaffected).
- Exceptions record the **role/entity** and row number within that file; raw values remain masked by the
  existing PII handling, applied per file role.

### 4. File sets, readiness and intake

New: `file_sets` (set id, source, pairing key, status `waiting | ready | expired | overridden | consumed`,
created/ready timestamps) and `batch_files` (batch, role, filename, path, sha256, rows). `batches` keeps its
single `file_path` for the master so legacy code and screens still work; the other roles live in `batch_files`.

Readiness is declared per feed:

```
readiness:
  require: all_required | master_only
  pairing: sequence | business_date | filename_token | window_minutes: N
  wait_timeout_minutes: N
  on_timeout: fail | load_master_only | alert_only      # load_master_only only if details are all non-required
```

- A file is routed to its role by `name_pattern`, then attached to the open file set with the same pairing
  key (e.g. same date in the filename, same sequence, or arrival within the window). If none is open, a new
  file set opens.
- A set becomes `ready` when the declared requirement is met; only then is a batch queued. Waiting sets are
  visible in Import Monitor and Vendor Deliveries ("waiting for borrowers file").
- On timeout, the late/missed delivery alerts fire; the set then follows `on_timeout`. A person with the
  right role may also **override** (accept partial, discard, or re-pair) with a recorded reason, like the
  existing sequencing overrides.
- Mismatched dates: pairing never joins files whose pairing keys differ; a lone file stays `waiting` until
  the timeout, so stale details are never joined silently.
- Intake paths all accept sets: multi-file upload and presign per role, a zip with an optional manifest
  (`role -> filename`), and scheduled pulls (one pull pattern per role, set completes when all arrive).

### 5. The join stage

A new stage `pipeline/joiner.py` runs after file-set readiness and before pre-flight/mapping. It is a pure
function of `(layout, inputs by role) -> stream of joined master records + child records + join exceptions`.

- Key normalization is one shared definition (the listed ops) used by every engine.
- **Local engine:** bounded memory. Details are hash-partitioned or externally sorted to temp storage by
  normalized key; the master streams in file order and pulls its details. A detail file larger than memory
  must still work.
- **Spark engine:** the same layout compiled to DataFrame joins; output order restored by master row index.
- **Parity:** one set of golden fixtures (files + layout -> expected joined output and exception list)
  runs against both engines in CI. The Spark path for layout feeds stays disabled (the feed runs on the
  standard engine, as the size threshold would otherwise send it to Spark) until it passes parity.
- Join exceptions use new codes (builder to number them): orphan detail, missing required detail,
  duplicate master key, cardinality violation, flatten overflow, key unparseable.

### 6. Pre-flight, replay, changes

- Pre-flight runs per file against its declared columns (existing drift logic, per role) plus a **join
  pre-check** on a sample: key coverage, match rate, cardinality violations. Failing `min_match_rate`
  blocks the batch the same way a drift block does, and is overridable with a reason.
- Replay re-runs the join for held loans from the stored file set; exceptions superseded as today.
- Incremental / change files: a file set may carry change files for the master and/or child entities.
  `child` mode details are upserted by (parent key, child key) with optimistic concurrency like loans.
  Detail-only sets are supported for `child` mode only; for merge/flatten/aggregate a detail-only set
  cannot recompute the master row and is rejected with a clear error (phase 5).

### 7. Counts, observability and PII

- A batch reports, per role: rows read, matched, orphaned, rejected; and per entity: rows loaded. The
  primary count everywhere stays the master entity ("1,000 loans"); child and detail counts appear as
  breakdowns ("3,400 borrower rows").
- Retention and masking rules apply to every role's stored raw files and exception payloads; attributes
  flagged `pii` on child entities are masked like loan attributes.

### 8. Web app

- **Feed layout editor** (Vendor/Feed screen): files with sample upload per role, relations, mode options,
  readiness policy. Changes go through maker-checker like delivery profiles.
- **Join preview** on samples: match rate, orphan and missing counts, and a few joined rows (PII masked).
- **Mapping** grouped by role/entity; one tab per entity.
- Import Monitor/Vendor Deliveries show file-set state and per-role counts; exceptions filter by role.

### 9. Glue / AWS

- Feed job inputs change from one path to `inputs: {role: uri}` (single-file feeds pass one role).
- Step Functions gains a readiness gate and, for large sets, a Spark join state that writes joined parquet
  for the existing map/persist/load states. Child entities load through the existing load job pattern.
- The signed bundle carries layout, relations, readiness and all entity mappings; the join code is part of
  the same wheel that already ships `lbp`.

## Phasing (each phase ships working and tested)

1. **Foundation:** layout model and validation, bundle compile/sign, file sets + readiness + intake
   (multi-upload, zip, pull), join stage for **merge and aggregate** on the local engine, join exceptions,
   per-role pre-flight, layout editor and join preview, golden fixtures. Legacy feeds untouched.
2. **Flatten.**
3. **Child records:** entity registry, generated child tables, per-entity mapping/rules, loader and
   parent/child failure policies, replay.
4. **Glue/Spark parity:** Spark join, Step Functions states, parity CI, large-detail spill tests; lifts the
   layout-feed Spark restriction.
5. **Incremental detail-only and relation trees** (detail of a detail, e.g. borrower -> income).

## Decisions left to the builder

- Storage and editing format of entity definitions; table-naming details; DDL migration mechanism per DB.
- External-sort/spill implementation and temp location; Spark join tuning.
- Exact exception codes, API shapes, UI layout details, manifest file format.
- Test data volumes for the large-detail case.

## Calls made after the builder check (author's calls, open to correction)

- **Pairing key.** Extracted by a named capture group in `name_pattern` (e.g. `loans_(?P<date>\d{8}).csv`),
  or from the manifest, never from file contents. `sequence`/`business_date`/`filename_token` all compare
  the captured value for equality; `window_minutes` pairs files whose arrival times are within N minutes.
  Several sets may be open at once; a file joins the open set with the equal key, else opens a new one.
- **Deliveries and sequencing.** A file set counts as **one delivery** and one sequence number for the
  sequencing gate and the late/missed alerts; the set is "arrived" when it is `ready`. The alert text
  names the missing role.
- **Re-delivery.** Each file is deduplicated by sha256 as today. A re-sent file for a role in a set that is
  already `consumed` opens a **new** set (correction), subject to the sequencing gate. An `overridden`
  set can be re-paired only before its batch is queued. Set identity = hash of its members' sha256 by role.
- **Roles and permissions.** Layout and readiness changes reuse the delivery-profile maker-checker and its
  roles; set overrides reuse the sequencing-override roles. No new roles or RBAC schema in this project.
- **Join semantics (pinned by the golden fixtures, which are the spec of record):**
  - `normalize` applies to the join key only; stored values keep their original form. `strip_leading_zeros`
    on all-zero input yields `"0"`. Empty or null key parts never match (orphan/missing-key exception).
  - With no `order_by`, `first`/`last`/flatten/`concat_distinct` use detail **file order**;
    `concat_distinct` joins with `|` in first-seen order.
  - `sum/min/max` ignore nulls and empty strings; a group with no non-null values yields null; `count` counts rows.
  - Two roles producing the same output column name is a layout validation error, never a silent overwrite.
  - `where` and `order_by` use the existing transform expression grammar (`mapping/transforms.py`), no new language.
- **`min_match_rate`.** Denominator is master rows with at least one matching detail, over master rows
  (and, separately, detail rows with a master over detail rows; both are reported, the threshold applies to
  the master-side rate unless `on_orphan_detail: exception` is set, then to both). The pre-flight sample can
  block; the full run re-checks, and if it falls below the threshold the batch is `blocked` before any load
  (the join completes first, so no partial load), overridable with a reason. For `join: inner`,
  `on_missing_detail` must be `exception` or `allow`; masters dropped by an inner join are always logged as
  exceptions, never silently.
- **Phase 1 mapping target.** Phase 1 maps `role.column` fields onto the existing `loan` entity
  (`sse_loans`). The bundle format has `mappings` keyed by entity from day one (one entry, `loan`), so
  Phase 3 adds entries without changing the format.
- **Layout authoring.** The layout editor works from hand-entered columns or a sample per role; per-role
  profiling reuses the existing profiler.
- **Extension points.** Existing bundles and mapping rows migrate by adding `entity = 'loan'` with a
  default; feeds with no layout skip the join stage and file-set tables entirely.

## Owner decisions (confirmed 2026-11-17)

1. **Child records vs. parent (Phase 3).** Proposed: children **live with the parent batch**: parent and its
   children load in one transaction per micro-batch (checkpoint stays by master row index). Default
   `on_child_fail: hold_parent`, i.e. a parent with any failed child is held with all its good children, and
   replay re-runs the whole parent; `load_parent_flagged` loads the parent without its failed children and
   marks the parent row. Is that the right default, or should children have their own independent lifecycle?
2. **Database and scale for Phase 1.** Proposed: Phase 1 supports **SQLite and PostgreSQL**; SQL Server is a
   design constraint and is added in phase 4 with the AWS work. The local join must handle a detail file at
   least 10x the master (tested at 10M detail rows) using SQLite temp-table partitioning rather than a
   custom external sort. Is SQL Server needed earlier, and is 10M detail rows the right target?
