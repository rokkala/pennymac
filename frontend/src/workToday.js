/** Overview “Your work today” cards — pure flags in, cards out. */

export function buildWorkCards({
  canWorkExceptions,
  openExceptions,
  canReviewRules,
  ntfUnread,
  canDemoSetup,
  showMappingLink,
  showPolicyLink,
  lateDeliveries = 0,
  runningBatches = 0,
  stuckBatches = 0,
}) {
  const cards = [];
  if (lateDeliveries > 0 || stuckBatches > 0) {
    cards.push({
      id: "loads",
      title: "Loads need attention",
      detail: [
        lateDeliveries > 0 ? `${lateDeliveries} late/missed` : null,
        stuckBatches > 0 ? `${stuckBatches} stuck` : null,
      ].filter(Boolean).join(" · "),
      cta: "See desk",
      page: "overview",
      qs: "focus=attention",
    });
  }
  if (runningBatches > 0) {
    cards.push({
      id: "running",
      title: "Batches running",
      detail: `${runningBatches} in flight`,
      cta: "Watch progress",
      page: "overview",
      qs: "focus=attention",
    });
  }
  if (canWorkExceptions && openExceptions > 0) {
    cards.push({
      id: "exceptions",
      title: "Open exceptions",
      detail: `${openExceptions} needing attention`,
      cta: "Work queue",
      page: "exceptions",
    });
  }
  if (canReviewRules && ntfUnread > 0) {
    cards.push({
      id: "rule_reviews",
      title: "Rules waiting for review",
      detail: `${ntfUnread} unread`,
      cta: "Open reviews",
      page: "rules",
      qs: "queue=awaiting_review",
    });
  }
  if (canDemoSetup) {
    cards.push({
      id: "demo_setup",
      title: "Demo environment",
      detail: "Load the synthetic walkthrough kit.",
      cta: "Demo setup…",
      page: "governance",
    });
  }
  if (showMappingLink) {
    cards.push({
      id: "mapping",
      title: "Vendors & mapping",
      detail: "Drafts, approvals, and Glue publish.",
      cta: "Open workspace",
      page: "sources",
    });
  }
  if (showPolicyLink) {
    cards.push({
      id: "policy",
      title: "Policy & audit",
      detail: "Thresholds, kill switch, and audit.",
      cta: "Open policy",
      page: "governance",
    });
  }
  return cards;
}
