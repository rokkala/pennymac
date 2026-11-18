import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { canArchive, canRestore, canDelete, canDiscardMapping, splitFeeds, archivedLine, RESTORE_NOTE } from "./lifecycleModel.js";
import { canCap } from "./roles.js";

const u = (...roles) => ({ roles });

describe("canArchive", () => {
  it("lets onboarding archive a feed that is not live", () => {
    assert.equal(canArchive(u("onboarding"), { status: "mapping" }), true);
    assert.equal(canArchive(u("onboarding"), { status: "draft" }), true);
  });
  it("needs the reviewer for a live feed", () => {
    assert.equal(canArchive(u("onboarding"), { status: "live" }), false);
    assert.equal(canArchive(u("onboarding_reviewer"), { status: "live" }), true);
    assert.equal(canArchive(u("admin"), { status: "live" }), true);
  });
  it("is false for roles without edit rights and for archived feeds", () => {
    assert.equal(canArchive(u("monitoring"), { status: "mapping" }), false);
    assert.equal(canArchive(u("admin"), { status: "retired" }), false);
  });
});

describe("canRestore", () => {
  it("is for archived feeds, by anyone who may edit", () => {
    assert.equal(canRestore(u("onboarding"), { status: "retired" }), true);
    assert.equal(canRestore(u("monitoring"), { status: "retired" }), false);
    assert.equal(canRestore(u("admin"), { status: "live" }), false);
  });
});

describe("canDelete", () => {
  it("is admin only and not for a feed known to have history", () => {
    assert.equal(canDelete(u("admin"), { status: "retired" }), true);
    assert.equal(canDelete(u("onboarding_reviewer"), { status: "retired" }), false);
    assert.equal(canDelete(u("admin"), { status: "retired", has_history: true }), false);
  });
});

describe("canDiscardMapping", () => {
  it("is for draft mappings only, on a feed that is not archived", () => {
    assert.equal(canDiscardMapping(u("onboarding"), { status: "draft" }, { status: "mapping" }), true);
    assert.equal(canDiscardMapping(u("onboarding"), { status: "rejected" }, { status: "mapping" }), false);
    assert.equal(canDiscardMapping(u("onboarding"), { status: "approved" }, { status: "live" }), false);
    assert.equal(canDiscardMapping(u("onboarding"), { status: "in_review" }, { status: "mapping" }), false);
    assert.equal(canDiscardMapping(u("monitoring"), { status: "draft" }, { status: "mapping" }), false);
    assert.equal(canDiscardMapping(u("onboarding"), { status: "draft" }, { status: "retired" }), false);
  });
});

describe("splitFeeds / archivedLine", () => {
  it("separates archived feeds", () => {
    const r = splitFeeds([{ status: "live" }, { status: "retired" }, { status: "mapping" }]);
    assert.equal(r.active.length, 2);
    assert.equal(r.archived.length, 1);
  });
  it("describes who and when", () => {
    assert.match(archivedLine({ retired_reason: "Vendor left", retired_at: "2026-11-01T00:00:00Z" }), /Vendor left/);
    assert.equal(archivedLine({}), "");
  });
  it("says schedules stay paused on restore", () => assert.match(RESTORE_NOTE, /paused/));
});

describe("caps", () => {
  it("archiveFeed and deleteFeed", () => {
    assert.equal(canCap(u("onboarding"), "archiveFeed"), true);
    assert.equal(canCap(u("monitoring"), "archiveFeed"), false);
    assert.equal(canCap(u("onboarding_reviewer"), "deleteFeed"), false);
    assert.equal(canCap(u("admin"), "deleteFeed"), true);
  });
});
