/** Same rule as backend Principal.has: admin bypasses any role check.
 *  Reviewer groups include their team member powers (mirrors backend expand_roles).
 */
const REVIEWER_INCLUDES = {
  onboarding_reviewer: "onboarding",
  monitoring_reviewer: "monitoring",
  compliance_reviewer: "compliance",
};

const LEGACY = {
  analyst: "onboarding",
  sme: "onboarding_reviewer",
  ops: "monitoring",
  reviewer: "monitoring",
  checker: "monitoring_reviewer",
};

export function expandRoles(roles) {
  const out = [];
  for (const raw of roles || []) {
    const r = LEGACY[raw] || raw;
    if (!out.includes(r)) out.push(r);
    const member = REVIEWER_INCLUDES[r];
    if (member && !out.includes(member)) out.push(member);
  }
  return out;
}

export function can(user, ...roles) {
  const rs = expandRoles(user?.roles || []);
  return rs.includes("admin") || roles.some((r) => rs.includes(r));
}

/** Capability → roles allowed (mirrors backend ROUTE_ROLES). Reviewers inherit member caps via expandRoles. */
export const CAPS = {
  editMapping: ["onboarding"],
  approveMapping: ["onboarding_reviewer"],
  upload: ["monitoring"],
  pauseBatch: ["monitoring"],
  resumeBatch: ["monitoring", "onboarding_reviewer"],
  overridePreflight: ["onboarding_reviewer", "compliance_reviewer"],
  replay: ["monitoring", "onboarding_reviewer"],
  workExceptions: ["monitoring", "compliance"],
  checkerApprove: ["monitoring_reviewer"],
  complianceAct: ["compliance_reviewer"],
  editRules: ["onboarding", "compliance_reviewer"],
  authorRules: ["onboarding"],
  editPolicy: ["compliance_reviewer"],
  demoSetup: ["admin"],
  editVendors: ["onboarding"],
  vendorLifecycle: ["onboarding_reviewer", "compliance_reviewer"],
  moveFeed: ["onboarding_reviewer"],
  publishConfig: ["onboarding_reviewer"],
  editDelivery: ["onboarding"],
  approveDelivery: ["onboarding_reviewer"],
  skipGap: ["monitoring", "onboarding_reviewer"],
  applyOutOfOrder: ["onboarding_reviewer", "compliance_reviewer"],
  discardBatch: ["monitoring", "onboarding_reviewer"],
  snapshotReviews: ["onboarding_reviewer"],
  schedules: ["monitoring", "onboarding"],
  approveSchedule: ["onboarding_reviewer", "compliance_reviewer"],
  readAudit: ["compliance_reviewer", "onboarding_reviewer"],
  readMaintenance: ["onboarding_reviewer", "admin"],
  managePersonas: ["admin"],
};

/** Run section: boarding desk, file loads, loans to fix, analytics. Onboarding does not. */
export function seesRunDesk(user) {
  return can(user, "monitoring", "compliance");
}

export const canCap = (user, cap) => {
  const need = CAPS[cap];
  if (!need) throw new Error(`unknown capability: ${cap}`);
  return can(user, ...need);
};

/** Exception Manager desk (raise / resolve). Monitoring · Reviewer is accept-only in the UI. */
export function canRaiseExceptions(user) {
  if (can(user, "admin")) return true;
  if (canCap(user, "checkerApprove")) return false;
  return canCap(user, "workExceptions");
}

/** Exception Manager tabs eligible for this persona. */
export function exceptionTabsFor(user, tabs) {
  if (can(user, "admin")) return tabs;
  if (canCap(user, "checkerApprove")) return tabs.filter((t) => t.id === "checker" || t.id === "resolved");
  // Monitoring desk: All open + T2–T4; skip T1 QA / submitted / T5.
  if (canRaiseExceptions(user) && can(user, "monitoring")) {
    return tabs.filter((t) => ["open", "T2", "T3", "T4", "resolved"].includes(t.id));
  }
  // Compliance desk: T5 halt queue only (member or reviewer).
  if (can(user, "compliance") && !can(user, "monitoring") && !can(user, "onboarding")) {
    return tabs.filter((t) => t.id === "T5" || t.id === "resolved");
  }
  return tabs;
}

/** First eligible Exception Manager tab for this persona. */
export function defaultExceptionTab(user) {
  // Monitoring keeps Suggest (T2) as home; All open is available but not the landing tab.
  const preferred = isMonitoringExceptionDesk(user)
    ? [{ id: "T2" }, { id: "open" }, { id: "resolved" }]
    : [{ id: "open" }, { id: "T2" }, { id: "checker" }, { id: "T5" }, { id: "resolved" }];
  return exceptionTabsFor(user, preferred)[0]?.id || "open";
}

/** True when this persona raises/resolves T2–T4 on the Exception Manager desk. */
export function isMonitoringExceptionDesk(user) {
  return canRaiseExceptions(user) && can(user, "monitoring");
}
