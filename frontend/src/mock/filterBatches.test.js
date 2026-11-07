import { describe, it } from "node:test";
import assert from "node:assert/strict";

/** Mirror of mock GET /api/batches filter rules for a unit check. */
function filterBatches(rows, q) {
  const ATTN = new Set(["failed", "blocked", "waiting", "paused", "out_of_order"]);
  const statuses = (q.get("status") || "").split(",").map((x) => x.trim()).filter(Boolean);
  const needle = (q.get("q") || "").trim().toLowerCase();
  const days = q.get("days") ? Number(q.get("days")) : null;
  const sinceMs = days && [1, 7, 30].includes(days) ? Date.now() - days * 86400000 : null;
  const match = (b) => {
    if (statuses.length && !statuses.includes(b.status)) return false;
    if (needle && !(String(b.filename || "").toLowerCase().includes(needle))) return false;
    const t = Date.parse(b.created_at || 0);
    if (sinceMs && Number.isFinite(t) && t < sinceMs) return false;
    return true;
  };
  const filtered = rows.filter(match);
  const attnStatuses = statuses.length ? statuses.filter((x) => ATTN.has(x)) : [...ATTN];
  const attentionCount = rows.filter((b) => {
    if (!attnStatuses.includes(b.status)) return false;
    if (needle && !(String(b.filename || "").toLowerCase().includes(needle))) return false;
    const t = Date.parse(b.created_at || 0);
    if (sinceMs && Number.isFinite(t) && t < sinceMs) return false;
    return true;
  }).length;
  const limit = Math.min(200, Math.max(1, Number(q.get("limit") || 50)));
  return { batches: filtered.slice(0, limit), attention: attentionCount };
}

describe("mock batch filters", () => {
  const rows = [
    { batch_id: "1", filename: "a.csv", status: "failed", created_at: new Date().toISOString() },
    { batch_id: "2", filename: "b.csv", status: "failed", created_at: new Date().toISOString() },
    { batch_id: "3", filename: "pcg.csv", status: "completed", created_at: new Date().toISOString() },
  ];
  it("limits rows but keeps uncapped attention", () => {
    const q = new URLSearchParams("limit=1&days=1");
    const out = filterBatches(rows, q);
    assert.equal(out.batches.length, 1);
    assert.equal(out.attention, 2);
  });
  it("filters by q on filename", () => {
    const q = new URLSearchParams("q=pcg&days=1");
    const out = filterBatches(rows, q);
    assert.equal(out.batches.length, 1);
    assert.equal(out.batches[0].filename, "pcg.csv");
  });
});
