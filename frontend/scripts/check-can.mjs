import assert from "node:assert/strict";
import { can, canCap, CAPS, expandRoles } from "../src/roles.js";

const monitoring = { id: "monitoring", roles: ["monitoring"] };
const monReview = { id: "monitoring.reviewer", roles: ["monitoring_reviewer"] };
const admin = { id: "admin", roles: ["admin"] };

assert.equal(canCap(monitoring, "replay"), true);
assert.equal(canCap(monitoring, "upload"), true);
assert.equal(canCap(monitoring, "checkerApprove"), false);
assert.equal(canCap(monReview, "checkerApprove"), true);
assert.equal(canCap(monReview, "upload"), true); // reviewer ⊇ member
assert.equal(canCap(admin, "replay"), true);
assert.equal(can(monitoring, "monitoring"), true);
assert.equal(can(monitoring, "onboarding"), false);
assert.ok(CAPS.replay.includes("monitoring"));
assert.equal(canCap({ id: "onboarding.reviewer", roles: ["onboarding_reviewer"] }, "readMaintenance"), true);
assert.equal(canCap({ id: "compliance.reviewer", roles: ["compliance_reviewer"] }, "editPolicy"), true);
assert.deepEqual(expandRoles(["onboarding_reviewer"]).sort(), ["onboarding", "onboarding_reviewer"].sort());
assert.deepEqual(expandRoles(["sme"]).sort(), ["onboarding", "onboarding_reviewer"].sort());
console.log("check-can ok");
