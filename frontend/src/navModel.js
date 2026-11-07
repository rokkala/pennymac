/** Rail information architecture: Guide → Setup → Run → Govern. */

export const NAV_GROUPS = [
  { id: "guide", label: "Guide", pages: ["guide"] },
  { id: "setup", label: "Setup", pages: ["sources", "rules", "deliveries"] },
  { id: "run", label: "Run", pages: ["overview", "monitor", "imports", "exceptions", "analytics"] },
  { id: "govern", label: "Govern", pages: ["governance", "maintenance", "personas"] },
];

/** First screen this person may open, in rail order. Skips empty groups. */
export function firstAllowedPage(allowedIds) {
  const order = NAV_GROUPS.flatMap((g) => g.pages);
  return order.find((id) => allowedIds.includes(id)) || "guide";
}

export function visibleNav(groups, allowedIds) {
  const allow = allowedIds == null ? null : new Set(allowedIds);
  return groups
    .map((g) => ({
      ...g,
      pages: allow ? g.pages.filter((id) => allow.has(id)) : [...g.pages],
    }))
    .filter((g) => g.pages.length > 0);
}
