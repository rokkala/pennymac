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

export const canCap = (user, cap) => {
  const need = CAPS[cap];
  if (!need) throw new Error(`unknown capability: ${cap}`);
  return can(user, ...need);
};
