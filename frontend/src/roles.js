/** Same rule as backend Principal.has: admin bypasses any role check. */
export function can(user, ...roles) {
  const rs = user?.roles || [];
  return rs.includes("admin") || roles.some((r) => rs.includes(r));
}

/** Capability → roles allowed (mirrors backend ROUTE_ROLES / EDIT_MAPPING / WORK_EXCEPTIONS). */
export const CAPS = {
  editMapping: ["analyst", "sme"],
  approveMapping: ["sme"],
  upload: ["ops"],
  pauseBatch: ["ops"],
  resumeBatch: ["ops", "sme"],
  overridePreflight: ["sme", "compliance"],
  replay: ["ops", "sme"],
  workExceptions: ["reviewer", "checker", "compliance"],
  checkerApprove: ["checker", "compliance"],
  complianceAct: ["compliance"],
  editRules: ["sme", "compliance"],
  authorRules: ["sme", "compliance", "analyst"],
  editPolicy: ["compliance"],
  demoSetup: ["admin"],
  editVendors: ["analyst", "sme"],
  vendorLifecycle: ["sme", "compliance"],
  moveFeed: ["sme"],
  publishConfig: ["sme"],
  editDelivery: ["analyst", "sme"],
  approveDelivery: ["sme"],
  skipGap: ["ops", "sme"],
  applyOutOfOrder: ["sme", "compliance"],
  discardBatch: ["ops", "sme"],
  snapshotReviews: ["sme"],
  schedules: ["ops", "sme"],
  approveSchedule: ["sme", "compliance"],
  readAudit: ["compliance", "sme"],
  readMaintenance: ["sme", "admin"],
  managePersonas: ["admin"],
};

export const canCap = (user, cap) => {
  const need = CAPS[cap];
  if (!need) throw new Error(`unknown capability: ${cap}`);
  return can(user, ...need);
};
