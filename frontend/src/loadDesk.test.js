import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildAttentionRows, buildLoadHealth, DUE_SOON_MS, scheduleDays } from "./loadDesk.js";

describe("buildLoadHealth", () => {
  it("counts running late missed stuck and exceptions", () => {
    const h = buildLoadHealth({
      batches: [
        { status: "running" },
        { status: "blocked" },
        { status: "waiting" },
        { status: "completed" },
      ],
      deliveries: [{ status: "late" }, { status: "missed" }, { status: "expected" }],
      openExceptions: 4,
    });
    assert.deepEqual(h, { running: 1, late: 1, missed: 1, stuck: 2, openExceptions: 4 });
  });
});

describe("buildAttentionRows", () => {
  const now = Date.parse("2026-11-05T12:00:00Z");

  it("orders missed before late before stuck batch before running before due-soon", () => {
    const rows = buildAttentionRows({
      now,
      batches: [
        { batch_id: "b-run", filename: "run.csv", status: "running", progress_pct: 40, processed: 40, total_rows: 100, started_at: "2026-11-05T11:00:00Z" },
        { batch_id: "b-block", filename: "block.csv", status: "blocked", started_at: "2026-11-05T10:00:00Z" },
      ],
      deliveries: [
        { delivery_id: "d-late", status: "late", due_at: "2026-11-05T08:00:00Z", schedule_name: "Late sch", vendor_name: "V", source_name: "F", batch_ids: [] },
        { delivery_id: "d-miss", status: "missed", due_at: "2026-11-04T08:00:00Z", schedule_name: "Miss sch", batch_ids: [] },
        { delivery_id: "d-soon", status: "expected", due_at: "2026-11-05T13:00:00Z", schedule_name: "Soon", batch_ids: [] },
        { delivery_id: "d-far", status: "expected", due_at: "2026-11-06T12:00:00Z", schedule_name: "Far", batch_ids: [] },
      ],
    });
    assert.deepEqual(rows.map((r) => r.id), [
      "delivery:d-miss",
      "delivery:d-late",
      "batch:b-block",
      "batch:b-run",
      "delivery:d-soon",
    ]);
    assert.ok(now + DUE_SOON_MS < Date.parse("2026-11-06T12:00:00Z"));
  });

  it("skips delivery when a linked batch is already in attention", () => {
    const rows = buildAttentionRows({
      now,
      batches: [{ batch_id: "b1", filename: "f.csv", status: "waiting", started_at: "t" }],
      deliveries: [{
        delivery_id: "d1", status: "late", due_at: "t", schedule_name: "S",
        batch_ids: ["b1"], batches: [{ batch_id: "b1", status: "waiting" }],
      }],
    });
    assert.deepEqual(rows.map((r) => r.kind), ["batch"]);
    assert.equal(rows[0].batchId, "b1");
  });

  it("keeps a queued file on the desk with its current step", () => {
    const rows = buildAttentionRows({
      now,
      batches: [{
        batch_id: "b-q", filename: "pcg_aws_run_3.csv", status: "queued", started_at: "t",
        pipeline: { steps: [{ label: "Glue", state: "running", summary: "standard" }] },
      }],
      deliveries: [],
    });
    assert.equal(rows.length, 1);
    assert.equal(rows[0].status, "queued");
    assert.equal(rows[0].meta, "Glue · standard");
  });
});

describe("scheduleDays", () => {
  const now = new Date("2026-11-06T15:00:00Z");

  it("groups windows by the date on the label and keeps earlier days as filters", () => {
    const days = scheduleDays([
      { delivery_id: "today", status: "expected", local_label: "2026-11-06 09:00 EST", due_at: "2026-11-06T14:00:00Z", schedule_name: "PCG", vendor_name: "PennyMac", source_name: "Retail" },
      { delivery_id: "miss", status: "missed", local_label: "2026-11-05 09:00 EST", due_at: "2026-11-05T14:00:00Z", schedule_name: "Summit", vendor_name: "Summit", source_name: "Tape" },
      { delivery_id: "tmrw", status: "expected", local_label: "2026-11-07 09:00 EST", due_at: "2026-11-07T14:00:00Z", schedule_name: "Tomorrow" },
    ], now);
    assert.equal(days.today, "2026-11-06");
    assert.deepEqual(days.dates.map((d) => d.id), ["2026-11-06", "2026-11-05"]);
    assert.equal(days.dates[0].label, "Today");
    assert.equal(days.dates[0].heading, "Friday, Nov 6, 2026");
    assert.equal(days.dates[1].label, "Thu, Nov 5");
    assert.equal(days.dates[1].missed, 1);
    assert.equal(days.byDate["2026-11-05"][0].delivery.delivery_id, "miss");
    assert.equal(days.byDate["2026-11-06"][0].when, "2026-11-06 09:00 EST");
  });
});
