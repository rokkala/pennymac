import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { parseHash, buildHash } from "./hash.js";

describe("parseHash", () => {
  it("splits id and query", () => {
    const p = parseHash("#guide?step=mapping&path=setup");
    assert.equal(p.id, "guide");
    assert.equal(p.params.get("step"), "mapping");
    assert.equal(p.params.get("path"), "setup");
  });
  it("handles bare id", () => {
    assert.equal(parseHash("rules").id, "rules");
    assert.equal(parseHash("rules").params.toString(), "");
  });
});

describe("buildHash", () => {
  it("omits empty query", () => assert.equal(buildHash("overview"), "overview"));
  it("joins params", () => assert.equal(buildHash("guide", { path: "setup", step: "mapping" }), "guide?path=setup&step=mapping"));
  it("accepts query string", () => assert.equal(buildHash("rules", "queue=awaiting_review"), "rules?queue=awaiting_review"));
});
