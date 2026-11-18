import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { filterBatches } from "./filterBatches.js";

describe("mock batch filters", () => {
  const rows = [
    { batch_id: "1", filename: "a.csv", status: "failed", created_at: new Date().toISOString(), throughput_lps: 0 },
    { batch_id: "2", filename: "b.csv", status: "failed", created_at: new Date().toISOString(), throughput_lps: 0 },
    { batch_id: "3", filename: "pcg.csv", status: "completed", created_at: new Date().toISOString(), throughput_lps: 0 },
    { batch_id: "4", filename: "live.csv", status: "running", created_at: new Date().toISOString(), throughput_lps: 12 },
    { batch_id: "5", filename: "live2.csv", status: "queued", created_at: new Date().toISOString(), throughput_lps: 8 },
  ];
  it("limits rows but keeps uncapped attention and running", () => {
    const q = new URLSearchParams("limit=1&days=1");
    const out = filterBatches(rows, q);
    assert.equal(out.batches.length, 1);
    assert.equal(out.attention, 2);
    assert.equal(out.running, 2);
    assert.equal(out.current_throughput_lps, 20);
  });
  it("filters by q on filename as a literal substring", () => {
    const q = new URLSearchParams("q=pcg&days=1");
    const out = filterBatches(rows, q);
    assert.equal(out.batches.length, 1);
    assert.equal(out.batches[0].filename, "pcg.csv");
  });
  it("treats % in q as a literal character", () => {
    const withPct = [
      ...rows,
      { batch_id: "6", filename: "has%x.csv", status: "completed", created_at: new Date().toISOString() },
    ];
    const out = filterBatches(withPct, new URLSearchParams("q=%&days=1"));
    assert.deepEqual(out.batches.map((b) => b.filename), ["has%x.csv"]);
  });
});
