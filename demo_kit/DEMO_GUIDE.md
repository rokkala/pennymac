# Demo kit: test data and a ready-to-run demo

Every file below is **synthetic**. Borrower names, SSNs, emails, phone numbers and addresses are generated, and no real borrower data appears anywhere.

## What is in the kit

| Path | Contents |
|---|---|
| `files/1_preloaded/<vendor>/<feed>/` | The 16 files the platform already loaded when the demo starts. Use them to show the source data behind what is on screen. |
| `files/2_upload_live/<vendor>/<feed>/` | 8 files you upload during the demo. Each one triggers one behaviour, and every one has been run against the demo state to confirm the outcome described below. |
| `MANIFEST.csv` | One row per file: vendor, feed, row count, what it shows, and the expected outcome. Opens in Excel. |
| `start_demo.sh` | Builds the demo state from scratch and starts the platform at http://localhost:8000. |
| `../sample_data/` | The four original layout samples: PCG CSV, Atlas Excel, Cornerstone pipe-delimited TXT, Summit CSV. |

## Two ways to demo

| | Live platform (recommended) | Clickable demo (no install) |
|---|---|---|
| How | From the repo root: `./demo_kit/start_demo.sh`, then open http://localhost:8000. Or Platform Admin → **Policy & Audit → Load demo scenario…** | Open the published "Loan Boarding Console" page, or `frontend/dist-demo/index.html` |
| State | The scenario below, built by the real engine (`lbp.demo_setup`) | The same scenario, captured as a snapshot |
| Uploads | Real: copy from `$LBP_DATA_DIR/demo_uploads/2_upload_live` (or `demo_kit/files/2_upload_live`) | Simulated progress only. Use it for walking through screens, not for uploads. |
| Scale | Default **compact** (~200 rows/feed). Pass `--full` / choose Full in the UI for sales scale. | Snapshot is usually full-scale. |

Run `start_demo.sh` within a few hours of the demo. Delivery due times, "late" flags and "2 min ago" labels are all relative to when the script runs. Existing data is left alone unless you pass `--force` or check **Wipe** in the UI.

## Personas (the "Signed in as" switcher, bottom left)

| Persona | Roles | Use for |
|---|---|---|
| Priya · Data Analyst | analyst | Onboarding vendors and feeds, preparing mappings, proposing delivery profiles |
| Dan · SME | sme, analyst | Approving mappings and profiles (it must be a different person from the preparer), overrides, republishing configuration |
| Maria · Boarding Ops | ops | Uploads, pause / resume, skipping a sequence gap, waiving deliveries, pull-now |
| Lee · Exception Reviewer | reviewer | T2 / T3 fixes, T4 maker |
| Sam · Checker | checker, reviewer | T4 checker: approving another person's fix |
| Ana · Compliance | compliance, checker | T5 OFAC / fraud, policy thresholds, the T1 kill switch, audit-chain verification |
| Platform Admin | all | Avoid in the demo: it hides the maker-checker story |

## The pre-loaded state

| Vendor | Feeds | What is already there |
|---|---|---|
| **PennyMac Retail (PCG)** | Daily retail tape (CSV, full tapes) | Day 1 and day 2 boarded. Today's file `pcg_retail_2026-11-02.csv` is **blocked by schema drift** (NoteRate renamed, MaturityDate format changed). Today's delivery shows **late**. |
| **Atlas Capital Partners** | Bulk acquisition tape (Excel) | One tape boarded, and a monthly schedule. |
| **Cornerstone Servicing** | Boarding tapes (pipe TXT); Intraday change files | Two tapes boarded, plus a 120-loan **re-send** held as DUP02. Change files #41 and #42 applied. **#44 is waiting** because #43 never arrived. #41 produces a CHG01 protected rate change, CHG02 unknown loans, ACT01 an unknown action code and CHG06 a loan owned by another vendor. A CHG05 conflict appeared after a rate change was approved. |
| **Summit Home Lending** | Loan tape (CSV); Weekly portfolio snapshot (SFTP pull) | "Owner-Occ" occupancy values were fixed through a value translation in **mapping v2**; the **Replay preview** shows the held loans now boarding. The weekly snapshot raised **12 CHG04 close reviews**. |
| **Westside Lending** | Loan tape | **Mid-onboarding**: a draft mapping waits for analyst review. |

Across the platform:

- About 18K loans in SSE.
- Exceptions in every tier: T1 auto-applied, T2 / T3 open, T4 open and awaiting a checker, T5 escalated, plus resolved history.
- 22 migrated rules. R015 v2 (DTI 45%) is running as a **10% canary**, and one authored draft rule exists.
- Four delivery schedules with a month of on-time / late / missed / waived history.
- A signed, published Glue configuration for every live feed.

## Suggested run of show (about 25 minutes)

1. **Overview and vendors (Priya, 3 min).** Open Vendors & Mapping and pick a vendor. Each vendor owns feeds, and each feed has mapping versions, a delivery profile, a schedule and a **Glue config vN** badge. Click the badge: this is the signed configuration Glue runs. Drafts are never published.
2. **Onboard a new vendor live (Priya, 4 min).** Click "Onboard vendor" and enter **Harbor Lending**. Then "Add feed", name it "Loan tape", and upload `2_upload_live/Harbor_Lending_new_vendor/Loan_tape/harbor_lending_first_tape.csv`. The file is profiled, PII is flagged and 100% of columns are auto-mapped. Open a field to show the transformation steps, sample trace and DQ checks, and use ← → to move through fields. Click "Submit for approval…".
3. **Approve (switch to Dan, 1 min).** Click "Approve…": the dialog shows what changed and the DQ results. Approve and publish. The feed's Glue config badge appears. If you try to approve as Priya, the app refuses.
4. **Happy path (Maria, 3 min).** In the Import Monitor, click "Upload file" and choose PCG / Daily retail tape with `pcg_retail_2026-11-04.csv`. Open the batch: you see pre-flight pass, micro-batches, throughput, and reconciliation of source = boarded + held + rejected. Expect about 2,400 boarded and about 100 held.
5. **Schema drift (Maria then Dan, 3 min).** Upload `pcg_retail_2026-11-04_RENAMED_COLUMN.csv`. It is **blocked before any row loads**. Open it: two mapped columns are missing, with a rename suggestion. "Create mapping fix…" opens the draft mapping for an SME, or Dan can use "Override and run…", which asks for a reason.
6. **Exception Manager (Lee, Sam, Ana, 5 min).**
   - **T2:** accept the AI fix, and the next exception opens.
   - **Reject loan…:** show the reason prompt.
   - **T4:** submit as maker (Lee), then approve as checker (Sam). The same person cannot do both.
   - **T5 OFAC hit:** only Compliance (Ana) can act, and an investigation note is required.
   - **Root causes:** the panel at the top groups exceptions into fixable mapping defects.
7. **Change files and ordering (Maria, 3 min).**
   - In the Import Monitor, `SUBSVC_DELTA_000044.txt` is **waiting**. Upload `SUBSVC_DELTA_000043.txt` to Cornerstone / Intraday change files. #43 applies, then #44 is released and applies on its own.
   - Upload `SUBSVC_DELTA_000040.txt`: it is held as **out of order** and nothing is applied. "Discard…" asks for a reason.
   - Open #41 and click "View loan changes" for field-level was → now values (NPI masked).
8. **Re-send protection (Maria, 1 min).** Upload `sub_servicing_RESEND.txt` to Cornerstone / Boarding tapes. All 60 rows go to **DUP02** dual control with an SSE vs incoming comparison. Nothing is overwritten.
9. **Snapshot truncation guard (Maria, 1 min).** Upload `correspondent_snapshot_<date>.csv` (from `2_upload_live`) to Summit / Weekly portfolio snapshot. Half the portfolio is missing, so it is flagged **truncated**, no close reviews are raised, and an alert fires.
10. **Replay (Maria, 1 min).** Open `correspondent_2026-11-02.csv` and click "Preview replay…". The held "Owner-Occ" loans now board on mapping v2.
11. **Deliveries and governance (Ana, 2 min).**
    - Vendor Deliveries: PCG is late. Use "Waive…" (asks for a reason) or "Pull now…".
    - Rule Engine: open R015 to see the canary, and lifecycle transitions that ask for a comment.
    - Policy & Audit: "Change thresholds…" (two people), "Kill switch…" for T1, "Verify chain" for the audit log.

## How the test data is made

`backend/lbp/samples.py` generates loans with realistic distributions: loan types, rates, terms, LTV, DTI, FICO, states, investors and escrow. **About 6% of rows carry a deliberate defect** so that every rule and tier has something to catch:

- missing or invalid property state
- rate ×10
- FICO typo (×10 or 0)
- missing SSN
- 3-digit ZIP
- maturity before note date
- current balance above original amount
- missing last name
- bad occupancy code
- OFAC hit (T5)
- fraud flag (T5)

Each vendor's layout differs on purpose, so mapping has real work to do:

| Vendor | Layout |
|---|---|
| PCG | Clean CSV |
| Atlas | Excel with different headers |
| Cornerstone | Pipe-delimited, cents amounts, YYYYMMDD dates |
| Summit | CSV with `$1,234.56` amounts and composite name / address columns |

The scenario on top of that (drift, re-sends, change files, snapshots, value-translation fix, rule canary, schedules) is built by `backend/lbp/demo_setup.py` (shared by the CLI, API, and `start_demo.sh`). Re-run any time:

```bash
cd backend && python -m lbp.cli demo-setup --data-dir ../.demo_data --kit ../demo_kit --force --scale compact
# or: python scripts/demo_setup.py --data-dir ../.demo_data --kit ../demo_kit --force
```

The automated tests exercise the same module with compact scale.
