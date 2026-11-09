import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { parseHash } from "./hash.js";

/** Mirrors HowItWorks selection rules for deep links (kept in sync by review). */
function honorPersonaDefault(raw) {
  const { params } = parseHash(raw);
  return !params.get("step") && !params.get("path");
}

function resolveSel(raw, stepIds, firstYours) {
  const step = parseHash(raw).params.get("step");
  return step && stepIds.includes(step) ? step : firstYours;
}

describe("guide deep link rules", () => {
  it("path-only hash blocks persona default", () => {
    assert.equal(honorPersonaDefault("#guide?path=execution"), false);
  });
  it("bare guide allows persona default", () => {
    assert.equal(honorPersonaDefault("#guide"), true);
  });
  it("selects firstYours when step is on the other path", () => {
    assert.equal(resolveSel("#guide?step=mapping", ["arrive", "batch"], "arrive"), "arrive");
  });
  it("keeps step when it belongs to current path", () => {
    assert.equal(resolveSel("#guide?step=mapping", ["vendor", "mapping", "publish"], "vendor"), "mapping");
  });
});
