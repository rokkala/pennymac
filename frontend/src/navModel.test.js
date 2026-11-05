import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { NAV_GROUPS, visibleNav } from "./navModel.js";

describe("NAV_GROUPS", () => {
  it("locks Guide → Setup → Run → Govern order and page ids", () => {
    assert.deepEqual(NAV_GROUPS.map((g) => g.id), ["guide", "setup", "run", "govern"]);
    assert.deepEqual(NAV_GROUPS.find((g) => g.id === "guide").pages, ["guide"]);
    assert.deepEqual(NAV_GROUPS.find((g) => g.id === "setup").pages, ["sources", "rules", "deliveries"]);
    assert.deepEqual(NAV_GROUPS.find((g) => g.id === "run").pages, ["overview", "imports", "exceptions", "analytics"]);
    assert.deepEqual(NAV_GROUPS.find((g) => g.id === "govern").pages, ["governance", "maintenance", "personas"]);
  });
});

describe("visibleNav", () => {
  it("keeps all pages when allowedIds is null", () => {
    const v = visibleNav(NAV_GROUPS, null);
    assert.equal(v.length, 4);
    assert.deepEqual(v.find((g) => g.id === "setup").pages, ["sources", "rules", "deliveries"]);
  });
  it("drops empty groups when filtering", () => {
    const v = visibleNav(NAV_GROUPS, ["overview", "imports"]);
    assert.deepEqual(v.map((g) => g.id), ["run"]);
    assert.deepEqual(v[0].pages, ["overview", "imports"]);
  });
});
