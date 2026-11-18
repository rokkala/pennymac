/** Queue-tab help copy for Exception Manager. */
export const EXCEPTION_TAB_HELP = {
  open: {
    title: "All open",
    body: "Every exception still awaiting action across tiers. Use a tier tab when you want only one kind of work.",
    who: "Monitoring works most open items; Compliance handles T5.",
  },
  T1: {
    title: "Already applied",
    body: "T1. Low-risk formatting or code fixes at 0.95 confidence or higher. Already applied, audited, sampled for QA, and reversible in the rollback window.",
    who: "Monitoring spot-checks and rolls back bad auto-fixes.",
  },
  T2: {
    title: "Suggest a fix",
    body: "T2. Medium-risk fields at 0.80–0.95 confidence. A proposed fix is filled in; you confirm it or type a different value.",
    who: "Monitoring confirms or edits the proposed fix.",
  },
  T3: {
    title: "Review",
    body: "T3. Confidence below 0.80. Any suggestion is a hint only — you decide the value.",
    who: "Monitoring reviews and resolves.",
  },
  T4: {
    title: "Needs a second person",
    body: "T4. Regulated or high-risk fields (rate, term, FICO, DTI, HMDA, identity). Enter a verified value and submit. Nothing is applied until a different person accepts.",
    who: "Monitoring submits; a different Monitoring · Reviewer accepts.",
  },
  checker: {
    title: "Waiting for you",
    body: "T4. Fixes already submitted. Accept applies the value. Return sends it back with your note.",
    who: "Monitoring · Reviewer only, and not the person who submitted it.",
  },
  T5: {
    title: "Holds",
    body: "T5. OFAC hit or fraud alert. The loan stays halted until Compliance clears or rejects it.",
    who: "Compliance · Reviewer only.",
  },
  resolved: {
    title: "Done",
    body: "Finished items — accepted, cleared, or otherwise closed. Use this for history.",
    who: "Anyone who can open Loans to fix can read.",
  },
};

export function helpForExceptionTab(id) {
  return EXCEPTION_TAB_HELP[id] || null;
}
