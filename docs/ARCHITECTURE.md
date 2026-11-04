# Architecture: React web app, Glue data plane, signed configuration

**In short:** people configure and approve in the web app, and Glue does the work. Approval is the only way a configuration reaches Glue. Glue checks the configuration's signature before it boards a single loan.

```
 Web app (React, CloudFront)  ──JWT──▶  API Gateway ─▶ api Lambda (FastAPI)        control plane: configuration,
   Vendors & Mapping, Deliveries,                      │                          approvals, exceptions, analytics.
   Import Monitor, Exceptions, Rules,                  │  approve mapping /        Never transforms or loads loan data.
   Analytics, Policy & Audit, Personas                 │  delivery profile / rule
                                                       ▼
                                   config_store.publish ─▶ s3://processed/config/feeds/<feed>/v<n>.json + current.json
                                   (compile + HMAC-SHA256 sign;          (signed bundle: mapping, value maps, delivery
                                    key in Secrets Manager)               profile, parse options, profile, live rules)
                                                       │
 Vendor file ─▶ S3 raw/incoming/<feed>/ ─EventBridge─▶ on_file_arrival ─▶ Step Functions
 API upload  ─▶ S3 raw/uploads/<feed>/  ──────────────────────────────────▶   Route (Lambda: standard or Spark?)
 Vendor pull (Glue lbp-vendor-pull) ─▶ raw/incoming/ ─┘                        Glue lbp-feed  |  lbp-feed-spark   (.sync)
                                                                                  └─ load + verify signed config
                                                                                  └─ sequencing gate, pre-flight
                                                                                  └─ map, validate, triage T1–T5
                                                                                  └─ throttled micro-batches → SSE (RDS)
                                                                                  └─ checkpoint, reconcile, advance cursor
                                                                               Finalize (Lambda) → start released files
                                                                               SNS notify / MarkFailed
```

## Why this split

| Concern | Decision |
|---|---|
| All data integration on Glue | Every byte of loan data is parsed, mapped, validated and loaded inside a Glue job. Lambdas only register files, route, report and serve the API. |
| Driven by the web app | Glue jobs take one argument (`--batch_id`, or `--schedule_id` for pulls). Everything else comes from the feed's published configuration, which only the web app's approval flows produce. |
| Drafts never run | A draft mapping or proposed delivery profile is not published. Glue reads `current.json`, which approvals write. |
| Tamper-evident | Each bundle carries the SHA-256 of its canonical JSON and an HMAC signature. A hand-edited, truncated or stale bundle is refused, and the batch fails with `configuration: …` (audited as `batch.config_rejected`). |
| Live safety switches | The T1 kill switch and auto-suspension, and a vendor's suspended status, are read from the database at run time, not from the bundle. They act on the very next row. |
| Same code everywhere | The `lbp` wheel is installed into every Glue job (`--additional-python-modules`). The tests, the local worker and Glue all run the same mapping, rule and triage code. |

## Glue jobs

| Job | Runtime | Used for |
|---|---|---|
| `lbp-feed` | Glue 5.0 (Python 3.11), 2 × G.1X, driver only | Every batch by default: full tapes, change files, snapshots, Excel. Also replays held loans (`--mode replay`). Max concurrent runs = `glue_feed_concurrency`, the primary SSE protection knob. |
| `lbp-feed-spark` | Glue 5.0 Spark, auto-scaling to `glue_spark_max_workers` | Full CSV / TXT tapes above `glue_threshold_rows`. Partitions run the same mapping and rule code (`mapInPandas`). The driver persists in ordered, bounded micro-batches, so SSE sees a fixed number of connections whatever the worker count. Writes Parquet to the processed zone for Athena. If it fails, Step Functions resumes the batch on `lbp-feed` from the last checkpoint. |
| `lbp-vendor-pull` | Glue 5.0, driver only | SFTP (pinned host key) or S3 pulls for vendors that do not push. Pulled files land in `raw/incoming/` and arrive like any other file. |

Glue Python shell is not used: it supports only Python 3.9, and `lbp` needs 3.11 or later.

All three jobs run in the VPC through a Glue `NETWORK` connection, with the SSE / RDS security group rules shared with the control-plane Lambdas. Logs and bookmarks are encrypted with the platform KMS key. Any FAILED, TIMEOUT or ERROR run pages through EventBridge → SNS. The jobs emit `LBP/Pipeline` metrics (`LoansProcessed`, `LoansFailed`, `BatchSeconds`) for the dashboard and the failure-rate alarm.

**Notebooks** (`aws/glue/notebooks/`) are for development only: profiling a new vendor's file and trying rules against a sample in a Glue interactive session. They read published configuration and never write to SSE.

## When configuration is published

| Event | Published |
|---|---|
| Mapping version approved (SME, not the preparer) | that feed |
| Delivery profile change approved (a second SME) | that feed |
| Rule enters or leaves active / canary / shadow, or retires | every live feed |
| Feed moved to another vendor | every live feed (a vendor's feed list is part of each bundle) |
| `migrate` Lambda on each deploy | any live feed whose bundle is missing |
| Republish (SME, with a reason) | that feed. Used after a failed publication or a signing-key rotation. No new version is created if nothing changed. |

The web app shows each feed's publication as a "Glue config vN" chip (on feed cards and in the mapping workbench). Open it to see the version, the mapping version, rule counts, the signature status, whether it is in sync with the active mapping, and the publication history.

## Web app

The app is React 18 with no UI framework, built by Vite. A single-file demo build runs in the browser against a mock of the API.

**Pages** hold the lists. **Pop-up dialogs** hold everything you do to one item:

- Batch detail, upload, replay preview, loan-change log, and the sequencing and pre-flight actions.
- Exception review, with ← / → through the queue. Rejecting, escalating, returning, rolling back and bulk-resolving each ask for confirmation or a reason.
- Field inspector, validation preview, version diff, and the submit, send-back and approve steps.
- Delivery-profile edit and review, schedule approval and pause, delivery waiver and pull-now.
- Rule detail, authoring and lifecycle transitions.
- Policy thresholds, the T1 kill switch, audit entry detail and audit-chain verification.
- Vendor status changes and feed moves.

All dialogs share one component (`ui.jsx` `Modal`) with these behaviours:

- **Sizes:** sm, md, lg and xl.
- **Stacking:** a reason prompt can open over a detail dialog.
- **Focus:** focus is trapped inside the dialog and restored on close.
- **Closing:** Escape or a backdrop click closes only the top dialog. Closing is blocked while a request is in flight.
- **Navigation:** previous / next buttons, plus keyboard arrows when you are not typing.
- **Scroll:** the page behind the dialog does not scroll.
- **Phone width:** dialogs go full screen.

`ConfirmModal`, `ReasonModal` and `useDialog()` cover the audited-action pattern.
