import assert from "node:assert/strict";
import { can, canCap, CAPS } from "../src/roles.js";

const lee = { id: "lee.reviewer", roles: ["reviewer"] };
const maria = { id: "maria.ops", roles: ["ops"] };
const admin = { id: "admin", roles: ["admin"] };

assert.equal(canCap(lee, "replay"), false);
assert.equal(canCap(maria, "replay"), true);
assert.equal(canCap(admin, "replay"), true);
assert.equal(canCap(lee, "upload"), false);
assert.equal(canCap(maria, "upload"), true);
assert.equal(can(lee, "reviewer"), true);
assert.equal(can(lee, "ops"), false);
assert.ok(CAPS.replay.includes("ops"));
assert.equal(canCap(lee, "readMaintenance"), false);
assert.equal(canCap({ id: "dan.sme", roles: ["sme", "analyst"] }, "readMaintenance"), true);
assert.equal(canCap(admin, "readMaintenance"), true);
console.log("check-can ok");
