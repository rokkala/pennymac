import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildWorkCards } from "./workToday.js";

describe("buildWorkCards", () => {
  it("hides exceptions when capability is false even if count > 0", () => {
    const cards = buildWorkCards({
      canWorkExceptions: false,
      openExceptions: 12,
      canReviewRules: false,
      ntfUnread: 0,
      canDemoSetup: false,
      showMappingLink: false,
      showPolicyLink: false,
    });
    assert.equal(cards.find((c) => c.id === "exceptions"), undefined);
  });
  it("hides rule reviews when unread is zero", () => {
    const cards = buildWorkCards({
      canWorkExceptions: true,
      openExceptions: 0,
      canReviewRules: true,
      ntfUnread: 0,
      canDemoSetup: false,
      showMappingLink: false,
      showPolicyLink: false,
    });
    assert.equal(cards.find((c) => c.id === "rule_reviews"), undefined);
  });
  it("orders loads then running then exceptions then reviews then demo then mapping then policy", () => {
    const cards = buildWorkCards({
      canWorkExceptions: true,
      openExceptions: 3,
      canReviewRules: true,
      ntfUnread: 2,
      canDemoSetup: true,
      showMappingLink: true,
      showPolicyLink: true,
      lateDeliveries: 2,
      runningBatches: 1,
      stuckBatches: 1,
    });
    assert.deepEqual(cards.map((c) => c.id), ["loads", "running", "exceptions", "rule_reviews", "demo_setup", "mapping", "policy"]);
    assert.equal(cards[0].detail, "2 late/missed · 1 stuck");
    assert.equal(cards[2].cta, "Work queue");
    assert.equal(cards[3].qs, "queue=awaiting_review");
  });
});
