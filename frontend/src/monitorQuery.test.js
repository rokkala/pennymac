import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildBatchesPath, splitLiveAndHistory, LIVE_STATUSES } from "./monitorQuery.js";

describe("buildBatchesPath", () => {
  it("encodes days, status list, and q", () => {
    const path = buildBatchesPath({ days: 7, status: ["failed", "blocked"], q: "pcg", limit: 50 });
    assert.match(path, /\/api\/batches\?/);
    assert.match(path, /days=7/);
    assert.match(path, /status=failed%2Cblocked|status=failed,blocked/);
    assert.match(path, /q=pcg/);
    assert.match(path, /limit=50/);
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
