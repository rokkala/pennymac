# App UX Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the shell information architecture (Setup → Run → Govern + Guide), shared layout primitives, dual-audience Overview home, and How it works deep links — without rewriting Imports/Exceptions/Sources yet.

**Architecture:** Extract pure helpers (`hash`, `navModel`, `workToday`) tested with Node’s built-in test runner; evolve `styles.css` tokens + `ui.jsx` façades (`PageHeader`, `ActionBar`, `EmptyState`, `QueueCard`); regroup `App.jsx` rail; rebuild `Overview.jsx` Band A/B; teach `HowItWorks.jsx` to honor `#guide?step=` / `#guide?path=setup|execution&step=`.

**Tech Stack:** Vite React 18 SPA, existing hand CSS + `ui.jsx`, `node --test` for pure JS (no new npm deps), ESLint.

**Spec:** `docs/superpowers/specs/2026-11-05-app-ux-full-rebuild-design.md` (Phase A only)

## Global Constraints

- No Tailwind / shadcn; evolve hand CSS only.
- Keep page `id`s (`overview`, `guide`, `imports`, …); only grouping and query params change.
- Preserve teal / dark rail / Archivo + IBM Plex DNA; no purple SaaS look.
- No backend API changes in Phase A (Overview cards use existing endpoints or link without fake counts).
- Capability gates via `canCap` / screen allow-list unchanged.
- `npm run build` and `npm run build:demo` must both succeed.
- Do not redesign Imports, Exceptions, Sources, Deliveries, Analytics, Governance, Maintenance, Personas beyond what shared chrome automatically gives them.
- Commit only when the human asks (plan commit steps are optional checkpoints).

## Review Focus

1. Persona with no `workExceptions` must not see an exceptions QueueCard.
2. Rule-review card must not appear for zero unread when there is no awaiting_review signal (no fake badge).
3. Hash `#guide?step=mapping` must open Setup path and select that step even if persona default mode is Execution.
4. Allowed-screens filter must still hide Maintenance/Personas when not permitted; groups with zero visible pages must not render empty headings.
5. Mobile rail-as-top-strip must remain usable after NavGroup markup (no broken sticky rail).

---

## File map

| File | Responsibility |
|---|---|
| `frontend/src/hash.js` | `parseHash()`, `buildHash(id, params)` |
| `frontend/src/navModel.js` | `NAV_GROUPS`, `visibleNav(groups, pageIdsAllowed)` |
| `frontend/src/workToday.js` | `buildWorkCards({ persona, openExceptions, ntfUnread, demoSetup })` |
| `frontend/src/hash.test.js` | Node tests for hash |
| `frontend/src/navModel.test.js` | Node tests for nav |
| `frontend/src/workToday.test.js` | Node tests for Overview cards |
| `frontend/src/ui.jsx` | Export `PageHeader`, `ActionBar`, `EmptyState`, `QueueCard` |
| `frontend/src/styles.css` | Tokens + `.nav-group`, `.queue-grid`, PageHeader/ActionBar/EmptyState |
| `frontend/src/App.jsx` | Grouped nav; use `parseHash` / `buildHash`; restyle ErrorBoundary |
| `frontend/src/pages/Overview.jsx` | Band A story + Band B work cards + charts below |
| `frontend/src/pages/HowItWorks.jsx` | Read hash query; `go(page, qs)` from steps; PageHeader |
| `frontend/package.json` | Add `"test": "node --test src/*.test.js"` |

---

### Task 1: Hash helpers

**Files:**
- Create: `frontend/src/hash.js`
- Create: `frontend/src/hash.test.js`
- Modify: `frontend/package.json` (add `test` script)

**Interfaces:**
- Produces:
  - `parseHash(raw: string) -> { id: string, params: URLSearchParams }` — strips leading `#`; `id` is path before `?`; empty → `{ id: "", params }`
  - `buildHash(id: string, params?: Record<string,string> | URLSearchParams | string) -> string` — no leading `#`; omits `?` when no params; string form is already `a=b&c=d`

- [ ] **Step 1: Write the failing tests**

```js
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { parseHash, buildHash } from "./hash.js";

describe("parseHash", () => {
  it("splits id and query", () => {
    assert.deepEqual(
      { id: parseHash("#guide?step=mapping&path=setup").id, step: parseHash("#guide?step=mapping&path=setup").params.get("step"), path: parseHash("#guide?step=mapping&path=setup").params.get("path") },
      { id: "guide", step: "mapping", path: "setup" },
    );
  });
  it("handles bare id", () => {
    assert.equal(parseHash("rules").id, "rules");
    assert.equal(parseHash("rules").params.toString(), "");
  });
});

describe("buildHash", () => {
  it("omits empty query", () => assert.equal(buildHash("overview"), "overview"));
  it("joins params", () => assert.equal(buildHash("guide", { path: "setup", step: "mapping" }), "guide?path=setup&step=mapping"));
  it("accepts query string", () => assert.equal(buildHash("rules", "queue=awaiting_review"), "rules?queue=awaiting_review"));
});
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `cd frontend && node --test src/hash.test.js`  
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `parseHash` / `buildHash` in `frontend/src/hash.js`**

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd frontend && node --test src/hash.test.js`  
Expected: PASS

- [ ] **Step 5: Add `"test": "node --test src/*.test.js"` to `frontend/package.json` scripts**

---

### Task 2: Nav model

**Files:**
- Create: `frontend/src/navModel.js`
- Create: `frontend/src/navModel.test.js`

**Interfaces:**
- Consumes: none
- Produces:
  - `NAV_GROUPS: Array<{ id: string, label: string, pages: string[] }>` exactly:
    - `guide`: `["guide"]`
    - `setup`: `["sources", "rules", "deliveries"]`
    - `run`: `["overview", "imports", "exceptions", "analytics"]`
    - `govern`: `["governance", "maintenance", "personas"]`
  - `visibleNav(groups, allowedIds: string[] | null) -> Array<{ id, label, pages: string[] }>` — if `allowedIds` is null, keep all page ids as listed; else filter each group’s `pages` to those in `allowedIds`; **drop groups whose `pages` is empty**

- [ ] **Step 1: Write failing tests** for exact group order/ids and empty-group drop when `allowedIds = ["overview","imports"]`

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `navModel.js`**

- [ ] **Step 4: Run — expect PASS** (`node --test src/navModel.test.js`)

---

### Task 3: Work-today cards

**Files:**
- Create: `frontend/src/workToday.js`
- Create: `frontend/src/workToday.test.js`
- Modify: none yet (Overview wires later)

**Interfaces:**
- Consumes: caller passes booleans/numbers already gated (keep `canCap` out of the pure module to avoid importing React roles in node tests — pass flags)
- Produces:
  - `buildWorkCards(input) -> Array<{ id: string, title: string, detail: string, cta: string, page: string, qs?: string }>`
  - Input shape:
    ```ts
    {
      canWorkExceptions: boolean,
      openExceptions: number,          // 0+; card only if canWorkExceptions && openExceptions > 0
      canReviewRules: boolean,         // true if persona can author/approve path peers — Overview will pass canCap authorRules || editRules
      ntfUnread: number,               // card if canReviewRules && ntfUnread > 0
      canDemoSetup: boolean,           // show demo card only if true (Overview also checks cfg)
      showMappingLink: boolean,        // analyst/sme: always offer “Check mapping & publish” without a count
      showPolicyLink: boolean,         // compliance: “Policy & kill switch”
    }
    ```
  - Exact titles/CTAs (copy locked):
    | id | title | cta | page | qs |
    |---|---|---|---|---|
    | `exceptions` | `Open exceptions` | `Work queue` | `exceptions` | — |
    | `rule_reviews` | `Rules waiting for review` | `Open reviews` | `rules` | `queue=awaiting_review` |
    | `demo_setup` | `Demo environment` | `Demo setup…` | `governance` | — |
    | `mapping` | `Vendors & mapping` | `Open workspace` | `sources` | — |
    | `policy` | `Policy & audit` | `Open policy` | `governance` | — |
  - `detail` for exceptions: `${openExceptions} needing attention`; for rule_reviews: `${ntfUnread} unread`; mapping/policy/demo: one short sentence each (`"Drafts, approvals, and Glue publish."`, `"Thresholds, kill switch, and audit."`, `"Load the synthetic walkthrough kit."`)
  - Order: exceptions, rule_reviews, demo_setup, mapping, policy (omit when not shown)

- [ ] **Step 1: Write failing tests** covering Review Focus items 1–2 (no exceptions card when `canWorkExceptions` false even if count > 0; no rule card when `ntfUnread === 0`)

- [ ] **Step 2–4: Implement and pass**

---

### Task 4: Layout primitives + CSS

**Files:**
- Modify: `frontend/src/ui.jsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces React components (same file as existing exports):

```jsx
// PageHeader({ eyebrow, title, sub, primary, secondary, guideHref })
//   primary / secondary: React nodes (buttons). guideHref optional string like "#guide?step=arrive" rendered as text link “Why this step”
// ActionBar({ primary, children })  // primary node first visually; children = secondary actions
// EmptyState({ title, body, action })
// QueueCard({ title, detail, cta, onClick })  // button card; onClick required
```

- [ ] **Step 1: Add CSS** — `.nav-group` (eyebrow label over links), `.nav-group + .nav-group { margin-top: 10px }`, `.queue-grid` (auto-fill minmax 220px), `.queue-card`, `.action-bar`, `.empty-state`, elevation token `--elevated` if missing; do not remove existing `.page-head` (PageHeader can render `className="page-head"` for compatibility)

- [ ] **Step 2: Implement components in `ui.jsx` and export them**

- [ ] **Step 3: Lint**

Run: `cd frontend && npm run lint`  
Expected: clean on `ui.jsx`

---

### Task 5: Grouped shell in App.jsx

**Files:**
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Consumes: `NAV_GROUPS`, `visibleNav`, `parseHash`, `buildHash` from Tasks 1–2
- `PAGES` array stays the registry of `{ id, label, el }`
- `pageIdFromHash` uses `parseHash` and validates id against `PAGES`
- `go(id, qs)` uses `buildHash`
- Rail: map `visibleNav(NAV_GROUPS, allowed ?? null)` then for each group render `<div className="nav-group"><span className="eyebrow">…</span>…links…</div>` inside `<nav>`
- When `allowed` is null, build allowed list as all `PAGES` ids that pass today’s maintenance/personas `canCap` filters (same logic as current `navPages` filter) — i.e. compute `navPages` first, then `visibleNav(NAV_GROUPS, navPages.map(p => p.id))`
- Keep exception + rules badges
- ErrorBoundary: use Panel-like markup / `EmptyState` with Try again

- [ ] **Step 1: Wire imports and replace flat nav with grouped nav**

- [ ] **Step 2: Manual check** — switch persona Admin vs Reviewer; Confirm Maintenance hidden for Reviewer and Govern group still shows Policy if allowed; no empty “Maintenance-only” group artifacts

- [ ] **Step 3: Lint App.jsx**

---

### Task 6: Overview dual home

**Files:**
- Modify: `frontend/src/pages/Overview.jsx`

**Interfaces:**
- Consumes: `PageHeader`, `QueueCard`, `buildWorkCards`, `canCap`, existing `useApi` endpoints (`/api/analytics/executive`, `/api/analytics/exceptions`, `/api/config`, plus `scoped("/api/exceptions/summary")` and `/api/notifications` for counts — or accept counts via optional props if already on parent; prefer fetching in Overview to avoid App prop drilling)
- Band A: PageHeader eyebrow `Home`, title `Loan boarding`, sub one sentence from current copy shortened; primary = Work exceptions if `canCap workExceptions` else Upload if upload else Walk the product; secondary includes How it works + Demo setup when gated
- Band B: heading `Your work today`; if `buildWorkCards(...).length === 0`, show `EmptyState` title `You’re caught up` body `No open queues for your role right now.` action → guide
- Charts: keep existing panels **below** Band B (same data)

Card flags mapping:
- `canWorkExceptions` ← `canCap(who, "workExceptions")`
- `openExceptions` ← sum open+pending_checker+escalated from exceptions summary (same formula as App badge) or executive `open_blocking_exceptions` if summary slow — prefer summary for consistency with badge
- `canReviewRules` ← `canCap(who, "authorRules") || canCap(who, "editRules")`
- `ntfUnread` ← notifications unread count
- `canDemoSetup` ← same as today’s `showDemo`
- `showMappingLink` ← `canCap editMapping || approveMapping || editVendors || publishConfig`
- `showPolicyLink` ← `canCap editPolicy || readAudit`

- [ ] **Step 1: Implement Overview bands**

- [ ] **Step 2: Manual** — persona Reviewer with open exceptions sees card; Analyst without exceptions still sees mapping link; Compliance sees policy

- [ ] **Step 3: Lint**

---

### Task 7: How it works deep links

**Files:**
- Modify: `frontend/src/pages/HowItWorks.jsx`

**Interfaces:**
- On mount + hashchange: `parseHash(location.hash)`; if `params.path` is `setup`|`execution`, set mode; if `params.step` matches a step id in SETUP or EXECUTION, set mode to that list’s path and `sel` to that id (Review Focus #3)
- Step CTA: `go(move.page)` may pass qs later; for now keep page id; optional `guideHref` not required on this page
- Replace page-head markup with `PageHeader`
- Export nothing new; step ids already on SETUP/EXECUTION objects

- [ ] **Step 1: Add hash sync effect**

- [ ] **Step 2: Manual** — from Overview or console set `location.hash = 'guide?path=setup&step=mapping'`; expect Setup tab + mapping selected

- [ ] **Step 3: From Overview Band A, Walk the product → `go("guide")`; optional secondary links can use `go("guide", "path=setup&step=publish")` for go-live — add one link in Overview Band A secondary **only if** cheap: button “See publish step” → that hash (optional; skip if it clutters — YAGNI: skip unless Band A has room)

---

### Task 8: Verify Phase A exit gate

**Files:** none (verification only)

- [ ] **Step 1: Unit tests**

Run: `cd frontend && npm test`  
Expected: all hash/nav/workToday tests PASS

- [ ] **Step 2: Lint + builds**

Run: `cd frontend && npm run lint && npm run build && npm run build:demo`  
Expected: success

- [ ] **Step 3: Manual smoke checklist**

- [ ] Rail shows Guide / Setup / Run / Govern labels
- [ ] Overview Band A + Band B; charts not above work cards
- [ ] Reviewer: exceptions card when opens > 0
- [ ] Rules badge still deep-links `queue=awaiting_review`
- [ ] `#guide?path=setup&step=publish` selects publish
- [ ] Demo build opens shell + Overview

Phase A exit (from spec): demo walk Overview→Guide→one Setup page; operator sees exception + rule-review cards when data exists.

---

## Spec coverage (self-review)

| Spec Phase A item | Task |
|---|---|
| Nav groups | 2, 5 |
| Tokens / PageHeader / ActionBar / EmptyState / QueueCard | 4 |
| Overview dual home | 3, 6 |
| How it works deep links | 1, 7 |
| ErrorBoundary restyle | 5 |
| No Tailwind; no backend | Global Constraints |
| build + build:demo | 8 |

Phases B–D intentionally **not** in this plan.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-05-app-ux-phase-a.md`. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven** — A fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end. Most thorough; costs a fresh context per task and per review.
- **Native** — I implement every task myself in this session, then one fresh reviewer on the most capable model checks the whole branch. Cheapest and fastest; no independent review until the end.

**For this plan I recommend Native**, because the tasks are tightly sequential (helpers → primitives → App → Overview → Guide) and a shipped mistake is mostly UI wiring, not a new dual-control backend. Does the plan capture what you want, and which approach should we use?
