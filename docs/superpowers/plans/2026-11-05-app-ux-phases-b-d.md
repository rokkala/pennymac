# App UX Phases B–D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (Native continuous). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the full-app UX rebuild: Run path, Setup path, and Govern pages all use Phase A chrome (`PageHeader`, `ActionBar`, `EmptyState`) with one primary CTA per context; no new product features.

**Architecture:** Presentation-only pass on remaining pages. Reuse `PageHeader` / `ActionBar` / `EmptyState` from `ui.jsx`. Keep all API calls, modals, and maker-checker behaviour. Deliveries included in Phase B so Setup/Run split is complete without deferral.

**Tech Stack:** Vite React 18, hand CSS, existing `ui.jsx` primitives, `node --test` only if a pure helper appears (prefer none).

**Spec:** `docs/superpowers/specs/2026-11-05-app-ux-full-rebuild-design.md` §§4–5, phases B–D

## Global Constraints

- No Tailwind/shadcn; no backend APIs; no behaviour changes to dual-control / Confirm/Reason modals.
- One primary button per page header and per row ActionBar where multiple actions exist.
- `guideHref` on PageHeader where a matching HowItWorks step id exists.
- Preserve capability gates (`canCap`).
- `npm test`, `npm run lint`, `npm run build`, `npm run build:demo` must pass at end.
- Commit/push to `feature/app-ux-phase-a`; do **not** open a PR.

## Review Focus

1. Ops without upload must not see Upload as primary on Imports (secondary or absent).
2. Exception row actions: claim/resolve remains the single primary when available; danger stays danger.
3. Sources workbench: Approve/Publish is primary when that is the next gate for the persona — not buried among equals.
4. Governance kill-switch remains visually unmistakable (danger) after PageHeader swap.
5. Empty lists show `EmptyState` with one CTA, never a blank table only.

---

### Task 1: Phase B — Imports

**Files:** Modify `frontend/src/pages/Imports.jsx`

- [ ] Replace page-head with `PageHeader` (eyebrow `Run`, title `Import Monitor`, sub one line, `guideHref="#guide?path=execution&step=arrive"`, primary = Upload when `canCap upload`)
- [ ] Where batch row/toolbar has many equal buttons, wrap with `ActionBar` putting Resume/Pause as primary when that is the live state
- [ ] Empty batch list → `EmptyState` with Upload or guide CTA
- [ ] Lint Imports.jsx

### Task 2: Phase B — Exceptions

**Files:** Modify `frontend/src/pages/Exceptions.jsx`

- [ ] `PageHeader` (eyebrow `Run`, guide `#guide?path=execution&step=exceptions`)
- [ ] Queue empty → `EmptyState` “No open exceptions”
- [ ] Row/detail ActionBar: one primary (Claim / Resolve / Approve as today by state)
- [ ] Lint

### Task 3: Phase B — Analytics + Deliveries

**Files:** Modify `Analytics.jsx`, `Deliveries.jsx`

- [ ] Both get `PageHeader` + guide links (`#guide` execution for analytics optional; deliveries `#guide?path=setup&step=schedule`)
- [ ] Deliveries: pending schedule approval → primary Approve when `canCap approveSchedule`
- [ ] Lint

### Task 4: Phase C — Sources / Vendors / DeliveryProfile / FeedConfig chrome

**Files:** `Sources.jsx`, `Vendors.jsx`, `DeliveryProfile.jsx`, `FeedConfig.jsx` (headers/actions only)

- [ ] Sources list/workbench page head → `PageHeader` (`#guide?path=setup&step=mapping`)
- [ ] Vendors list: primary Add vendor when `editVendors`
- [ ] DeliveryProfile panel actions: Approve primary when pending + `approveDelivery`
- [ ] No mapping logic changes
- [ ] Lint

### Task 5: Phase C — Rules PageHeader alignment

**Files:** `Rules.jsx`

- [ ] Swap page-head for `PageHeader` (eyebrow `Setup`, guide `#guide?path=setup&step=rules`, primary New rule when `authorRules`)
- [ ] Keep existing review/author ActionBar behaviour
- [ ] Lint

### Task 6: Phase D — Governance, Maintenance, Personas

**Files:** `Governance.jsx`, `Maintenance.jsx`, `Personas.jsx`

- [ ] Each uses `PageHeader`
- [ ] Governance: Demo setup secondary; kill switch stays danger
- [ ] Maintenance / Personas: clear primary (New template / Add user)
- [ ] Lint

### Task 7: Sweep + verify

- [ ] Grep `page-head` under `frontend/src` — only inside `PageHeader` implementation or none left in pages
- [ ] `npm test && npm run lint && npm run build && npm run build:demo`
- [ ] Commit + push branch (no PR)

## Spec coverage

| Spec item | Task |
|---|---|
| Phase B Run path | 1–3 |
| Phase C Setup path | 4–5 |
| Phase D Govern + sweep | 6–7 |
