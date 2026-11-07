import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { SCREEN, exceptionDeskSub } from "./screenCopy.js";

describe("screen names", () => {
  it("uses the job name on every renamed screen", () => {
    assert.equal(SCREEN.imports.label, "File loads");
    assert.equal(SCREEN.monitor.label, "Monitor");
    assert.match(SCREEN.monitor.sub, /Live loads/);
    assert.equal(SCREEN.exceptions.label, "Loans to fix");
    assert.equal(SCREEN.deliveries.label, "Delivery schedule");
    assert.equal(SCREEN.sources.label, "Vendors");
    assert.equal(SCREEN.rules.label, "Rules");
    assert.equal(SCREEN.governance.label, "Policy");
  });
  it("tells each exception desk what to do", () => {
    assert.match(exceptionDeskSub({ acceptOnly: true }), /Accept or return/);
    assert.match(exceptionDeskSub({ monitoringDesk: true }), /Confirm a suggested fix/);
    assert.match(exceptionDeskSub({}), /Clear a false positive/);
  });
});
