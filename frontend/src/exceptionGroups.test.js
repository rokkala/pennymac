import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  groupExceptions, exceptionFiltersFromSearch, loadDay, groupsFromLoads, fileScopedAllOpen,
  nextOpenId, tierForLoads, PAGE_SIZE, hasMoreExceptions,
} from "./exceptionGroups.js";

describe("groupExceptions", () => {
  it("groups by filename + vendor + load day (not batch_id alone)", () => {
    const groups = groupExceptions([
      { exception_id: "1", vendor_id: "v1", vendor_name: "PCG", batch_id: "bat_a", filename: "tape.csv", created_at: "2026-11-07T01:00:00Z" },
      { exception_id: "2", vendor_id: "v1", vendor_name: "PCG", batch_id: "bat_b", filename: "tape.csv", created_at: "2026-11-07T02:00:00Z" },
      { exception_id: "3", vendor_id: "v1", vendor_name: "PCG", batch_id: "bat_c", filename: "other.csv", created_at: "2026-11-07T03:00:00Z" },
    ]);
    assert.equal(groups.length, 2);
    const tape = groups.find((g) => g.filename === "tape.csv");
    assert.equal(tape.items.length, 2);
    assert.equal(tape.loaded_on, "2026-11-07");
    assert.ok(tape.key.includes("tape.csv"));
    assert.doesNotMatch(tape.key, /bat_a/);
  });
  it("deep-links the newest batch_id when the same filename has multiple loads", () => {
    const groups = groupExceptions([
      { exception_id: "1", vendor_id: "v1", vendor_name: "PCG", batch_id: "bat_old", filename: "tape.csv", created_at: "2026-11-07T01:00:00Z" },
      { exception_id: "2", vendor_id: "v1", vendor_name: "PCG", batch_id: "bat_new", filename: "tape.csv", created_at: "2026-11-07T09:00:00Z" },
    ]);
    assert.equal(groups[0].batch_id, "bat_new");
  });
  it("loadDay uses the calendar day of the timestamp", () => {
    assert.equal(loadDay("2026-11-07T15:22:00Z"), "2026-11-07");
    assert.equal(loadDay(""), "—");
  });
});

describe("exceptionFiltersFromSearch", () => {
  it("reads batch_id / loaded_on / vendor_id from the hash query", () => {
    assert.deepEqual(
      exceptionFiltersFromSearch("batch_id=bat_1&loaded_on=2026-11-07&vendor_id=ven_x"),
      { batch_id: "bat_1", loaded_on: "2026-11-07", vendor_id: "ven_x" },
    );
    assert.deepEqual(exceptionFiltersFromSearch(""), { batch_id: "", loaded_on: "", vendor_id: "" });
  });
});

describe("groupsFromLoads", () => {
  it("builds one filename group per load with open_count (no loan rows yet)", () => {
    const groups = groupsFromLoads([
      { batch_id: "bat_a", filename: "a.csv", vendor_id: "v", vendor_name: "PCG", loaded_on: "2026-11-07", open_count: 12 },
      { batch_id: "bat_b", filename: "b.csv", vendor_id: "v", vendor_name: "PCG", loaded_on: "2026-11-07", open_count: 3 },
    ]);
    assert.equal(groups.length, 2);
    assert.equal(groups[0].filename, "a.csv");
    assert.equal(groups[0].open_count, 12);
    assert.equal(groups[0].items, null);
  });
});

describe("fileScopedAllOpen", () => {
  it("is true for open-ish tabs when a batch filter is set", () => {
    assert.equal(fileScopedAllOpen({ batchId: "bat_1", tab: "T2" }), true);
    assert.equal(fileScopedAllOpen({ batchId: "bat_1", tab: "T4" }), true);
    assert.equal(fileScopedAllOpen({ batchId: "bat_1", tab: "T5" }), false);
    assert.equal(fileScopedAllOpen({ batchId: "", tab: "T2" }), false);
    assert.equal(fileScopedAllOpen({ batchId: "bat_1", tab: "checker" }), false);
  });
});

describe("tierForLoads", () => {
  it("scopes browse counts to the active tier tab; All open has no tier", () => {
    assert.equal(tierForLoads("T2"), "T2");
    assert.equal(tierForLoads("T4"), "T4");
    assert.equal(tierForLoads("open"), "");
    assert.equal(tierForLoads("checker"), "");
    assert.equal(tierForLoads("resolved"), "");
  });
});

describe("nextOpenId", () => {
  it("advances to the next loan after the current one (then previous if at end)", () => {
    const items = [{ exception_id: "a" }, { exception_id: "b" }, { exception_id: "c" }];
    assert.equal(nextOpenId(items, "a"), "b");
    assert.equal(nextOpenId(items, "b"), "c");
    assert.equal(nextOpenId(items, "c"), "b");
    assert.equal(nextOpenId(items, "missing"), "a");
    assert.equal(nextOpenId([], "a"), null);
  });
});

describe("hasMoreExceptions", () => {
  it("uses PAGE_SIZE pages against the API total", () => {
    assert.equal(PAGE_SIZE, 200);
    assert.equal(hasMoreExceptions(200, 51360), true);
    assert.equal(hasMoreExceptions(31, 31), false);
    assert.equal(hasMoreExceptions(0, 0), false);
  });
});
