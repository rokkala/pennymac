import assert from "node:assert/strict";
import { can, canCap, CAPS, expandRoles, canRaiseExceptions, exceptionTabsFor, defaultExceptionTab, isMonitoringExceptionDesk, seesRunDesk } from "../src/roles.js";

const monitoring = { id: "monitoring", roles: ["monitoring"] };
const monReview = { id: "monitoring.reviewer", roles: ["monitoring_reviewer"] };
const compliance = { id: "compliance.reviewer", roles: ["compliance_reviewer"] };
const admin = { id: "admin", roles: ["admin"] };

assert.equal(canCap(monitoring, "replay"), true);
assert.equal(canCap(monitoring, "upload"), true);
assert.equal(canCap(monitoring, "workExceptions"), true);
assert.equal(canCap(monitoring, "checkerApprove"), false); // raise only — cannot approve own T4
assert.equal(canCap(monReview, "checkerApprove"), true);
assert.equal(canCap(monReview, "workExceptions"), true); // API still inherits; UI raise is separate
assert.equal(canRaiseExceptions(monitoring), true);
assert.equal(canRaiseExceptions(monReview), false); // accept-only on Exception Manager
assert.equal(canRaiseExceptions(admin), true);
assert.deepEqual(
  exceptionTabsFor(monReview, [{ id: "open" }, { id: "checker" }, { id: "T4" }, { id: "resolved" }]).map((t) => t.id),
  ["checker", "resolved"],
);
assert.deepEqual(
  exceptionTabsFor(monitoring, [
    { id: "open" }, { id: "T1" }, { id: "T2" }, { id: "T3" }, { id: "T4" },
    { id: "checker" }, { id: "T5" }, { id: "resolved" },
  ]).map((t) => t.id),
  ["open", "T2", "T3", "T4", "resolved"],
);
assert.equal(defaultExceptionTab(monitoring), "T2");
assert.equal(defaultExceptionTab(monReview), "checker");
assert.deepEqual(
  exceptionTabsFor(compliance, [
    { id: "open" }, { id: "T2" }, { id: "T5" }, { id: "checker" }, { id: "resolved" },
  ]).map((t) => t.id),
  ["T5", "resolved"],
);
assert.equal(defaultExceptionTab(compliance), "T5");
assert.equal(isMonitoringExceptionDesk(monitoring), true);
assert.equal(isMonitoringExceptionDesk(monReview), false);
assert.equal(isMonitoringExceptionDesk(compliance), false);
assert.equal(seesRunDesk(monitoring), true);
assert.equal(seesRunDesk(monReview), true);
assert.equal(seesRunDesk(compliance), true);
assert.equal(seesRunDesk(admin), true);
assert.equal(seesRunDesk({ id: "onboarding", roles: ["onboarding"] }), false);
assert.equal(seesRunDesk({ id: "onboarding.reviewer", roles: ["onboarding_reviewer"] }), false);
assert.equal(canCap(monReview, "upload"), true);
assert.equal(canCap(admin, "replay"), true);
// legacy "reviewer" is not a live role check — expand aliases on the user, not on the required name
assert.equal(can(monitoring, "reviewer"), false);
assert.equal(can({ id: "legacy", roles: ["reviewer"] }, "monitoring"), true);
assert.equal(can(monitoring, "monitoring"), true);
assert.equal(can(monitoring, "onboarding"), false);
assert.ok(CAPS.replay.includes("monitoring"));
assert.equal(canCap({ id: "onboarding.reviewer", roles: ["onboarding_reviewer"] }, "readMaintenance"), true);
assert.equal(canCap({ id: "compliance.reviewer", roles: ["compliance_reviewer"] }, "editPolicy"), true);
assert.deepEqual(expandRoles(["onboarding_reviewer"]).sort(), ["onboarding", "onboarding_reviewer"].sort());
assert.deepEqual(expandRoles(["sme"]).sort(), ["onboarding", "onboarding_reviewer"].sort());
console.log("check-can ok");
