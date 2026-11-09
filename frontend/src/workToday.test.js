import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildWorkCards, queueHandoff } from "./workToday.js";

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
    assert.equal(cards[2].cta, "Open loans");
    assert.equal(cards[2].title, "Loans to fix");
    assert.equal(cards[3].qs, "queue=awaiting_review");
  });
  it("names the other team when this role has nothing to do", () => {
    const tiers = { T2: { open: 4 }, T4: { pending_checker: 2 }, T5: { escalated: 3 } };
    assert.equal(queueHandoff({ tiers, canWorkExceptions: true, canCheck: true, canComp: true }), null);
    assert.match(queueHandoff({ tiers, canWorkExceptions: false, canCheck: false, canComp: false }), /Monitoring still has 4/);
    assert.match(queueHandoff({ tiers, canWorkExceptions: true, canCheck: false, canComp: false }), /reviewer still has 2/);
    assert.match(queueHandoff({ tiers, canWorkExceptions: true, canCheck: true, canComp: false }), /Compliance still has 3/);
  });
});
