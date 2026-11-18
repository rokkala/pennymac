import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  buildBatchesPath, splitLiveAndHistory, deskOrder, LIVE_STATUSES, batchStep,
} from "./monitorQuery.js";

describe("buildBatchesPath", () => {
  it("encodes days, status list, and q", () => {
    const path = buildBatchesPath({ days: 7, status: ["failed", "blocked"], q: "pcg", limit: 50 });
    assert.match(path, /\/api\/batches\?/);
    assert.match(path, /days=7/);
    assert.match(path, /status=failed%2Cblocked|status=failed,blocked/);
    assert.match(path, /q=pcg/);
    assert.match(path, /limit=50/);
  });
  it("uses since/until for custom range and omits days", () => {
    const path = buildBatchesPath({
      days: null,
      since: "2026-11-01T00:00:00.000Z",
      until: "2026-11-07T23:59:59.000Z",
      limit: 50,
    });
    assert.match(path, /since=2026-11-01/);
    assert.match(path, /until=2026-11-07/);
    assert.doesNotMatch(path, /days=/);
  });
});

describe("splitLiveAndHistory", () => {
  it("puts live statuses in live and the rest in history", () => {
    const { live, history } = splitLiveAndHistory([
      { batch_id: "a", status: "running" },
      { batch_id: "b", status: "completed" },
      { batch_id: "c", status: "paused" },
    ]);
    assert.deepEqual(live.map((x) => x.batch_id), ["a", "c"]);
    assert.deepEqual(history.map((x) => x.batch_id), ["b"]);
  });
  it("exports the live status set used by Monitor", () => {
    assert.ok(LIVE_STATUSES.has("queued"));
    assert.ok(LIVE_STATUSES.has("running"));
    assert.ok(LIVE_STATUSES.has("pausing"));
    assert.ok(LIVE_STATUSES.has("paused"));
  });
});

describe("deskOrder", () => {
  it("navigates Live then History even when API returns mixed order", () => {
    const rows = [
      { batch_id: "done", status: "completed" },
      { batch_id: "live", status: "running" },
      { batch_id: "old", status: "failed" },
    ];
    assert.deepEqual(deskOrder(rows).map((x) => x.batch_id), ["live", "done", "old"]);
  });
});

describe("batchStep", () => {
  it("prefers the running Step Functions step when pipeline is present", () => {
    const s = batchStep({
      status: "running",
      progress_pct: 40,
      pipeline: {
        steps: [
          { name: "Route", label: "Route", state: "succeeded" },
          { name: "GlueStandard", label: "Glue", state: "running", summary: "engine glue" },
        ],
        current: { name: "GlueStandard", label: "Glue", state: "running", summary: "engine glue" },
      },
    });
    assert.equal(s.label, "Glue");
    assert.equal(s.state, "running");
    assert.match(s.detail || "", /engine glue/);
  });
  it("falls back to a local phase from status when there is no pipeline", () => {
    assert.equal(batchStep({ status: "blocked" }).label, "Preflight");
    assert.equal(batchStep({ status: "waiting" }).label, "Waiting");
    assert.equal(batchStep({ status: "paused", progress_pct: 20 }).label, "Paused");
    assert.equal(batchStep({ status: "running", progress_pct: 33.3 }).label, "Processing");
    assert.match(batchStep({ status: "running", progress_pct: 33.3 }).detail || "", /33/);
    assert.equal(batchStep({ status: "completed" }).label, "Done");
    assert.equal(batchStep({ status: "failed" }).label, "Failed");
    assert.equal(batchStep({ status: "claimed" }).label, "Claimed");
    assert.equal(batchStep({ status: "queued" }).label, "Queued");
  });
  it("prefers the last local pipeline step label when SF current is absent", () => {
    const s = batchStep({
      status: "running",
      progress_pct: 10,
      pipeline: {
        steps: [
          { name: "parse", label: "Parse", state: "succeeded" },
          { name: "validate", label: "Validate", state: "running", summary: "row 120" },
        ],
      },
    });
    assert.equal(s.label, "Validate");
    assert.match(s.detail || "", /row 120/);
  });
  it("shows checkpoint detail for local running batches with micro-batches", () => {
    const s = batchStep({
      status: "running",
      progress_pct: 40,
      micro_batches: 12,
    });
    assert.equal(s.label, "Processing");
    assert.match(s.detail || "", /12/);
  });
  it("keeps long errors on title only so the Step cell stays short", () => {
    const s = batchStep({ status: "failed", error: "PermissionError: [Errno 1] Operation not permitted" });
    assert.equal(s.label, "Failed");
    assert.equal(s.detail, null);
    assert.match(s.title || "", /PermissionError/);
    const blocked = batchStep({ status: "blocked", error: "Blocked: 1 mapped column(s) missing; and more text" });
    assert.equal(blocked.detail, null);
    assert.match(blocked.title || "", /Blocked/);
  });
});
