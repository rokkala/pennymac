/** Overview “Your work today” cards — pure flags in, cards out. */

export function buildWorkCards({
  canWorkExceptions,
  openExceptions,
  exceptionQueue = null,
  exceptionCount = 0,
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
  const queue = exceptionQueue || (canWorkExceptions && openExceptions > 0 ? "loans" : null);
  const queueCount = exceptionQueue ? exceptionCount : openExceptions;
  if (queue === "loans" && queueCount > 0) {
    cards.push({
      id: "exceptions",
      title: "Loans to fix",
      detail: `${queueCount} still open`,
      cta: "Open loans",
      page: "exceptions",
    });
  } else if (queue === "accept" && queueCount > 0) {
    cards.push({
      id: "exceptions",
      title: "Waiting for you",
      detail: `${queueCount} submitted fixes`,
      cta: "Accept or return",
      page: "exceptions",
    });
  } else if (queue === "holds" && queueCount > 0) {
    cards.push({
      id: "exceptions",
      title: "Holds",
      detail: `${queueCount} OFAC or fraud`,
      cta: "Review holds",
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
      title: "Vendors",
      detail: "Seller files and column maps.",
      cta: "Open workspace",
      page: "sources",
    });
  }
  if (showPolicyLink) {
    cards.push({
      id: "policy",
      title: "Policy",
      detail: "Who may auto-apply a fix, and the audit.",
      cta: "Open policy",
      page: "governance",
    });
  }
  return cards;
}

/** When this role's queues are empty, name the team that still has the work. */
export function queueHandoff({ tiers, canWorkExceptions, canCheck, canComp }) {
  if (!tiers) return null;
  const rows = Object.values(tiers);
  const open = rows.reduce((a, t) => a + (t.open || 0), 0);
  const pending = rows.reduce((a, t) => a + (t.pending_checker || 0), 0);
  const escalated = rows.reduce((a, t) => a + (t.escalated || 0), 0);
  const notes = [];
  if (!canWorkExceptions && open > 0) notes.push(`Monitoring still has ${open} loans to fix`);
  if (!canCheck && pending > 0) notes.push(`A reviewer still has ${pending} fixes waiting`);
  if (!canComp && escalated > 0) notes.push(`Compliance still has ${escalated} holds`);
  return notes.length ? `${notes.join(". ")}.` : null;
}
