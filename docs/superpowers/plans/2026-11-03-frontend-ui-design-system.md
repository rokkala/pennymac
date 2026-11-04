# Frontend UI Design System (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Loan Boarding Console shell and four demo-path pages to a Tailwind + shadcn design system while keeping teal/rail DNA, FastAPI, and `build:demo`.

**Architecture:** Add Tailwind v3 + shadcn-style components under `frontend/src/components/ui/`. Bridge existing CSS variables into Tailwind theme. Keep `ui.jsx` as the public façade (Panel, Kpis, Status, Modal, ToastHost, …) so out-of-scope pages keep compiling. Restyle shell + Overview / Imports / Exceptions / Sources+Vendors presentation only; no API or auth changes. Restyle Modal in place first — do not swap to Radix Dialog until behaviour parity is proven.

**Tech Stack:** React 18, Vite 5.4, Tailwind CSS v3, postcss, autoprefixer, class-variance-authority, clsx, tailwind-merge, Radix primitives only as pulled in by shadcn components used, existing hand SVG charts.

**Spec:** `docs/superpowers/specs/2026-11-03-frontend-ui-design-system-design.md`

## Global Constraints

- Stay on Vite SPA + hash routing; no Next.js in this plan.
- Preserve teal accent (`#0b6e72` / `#4fb8b8`) and dark rail (`#14262e` / `#0a1216`); no purple/indigo rebrand.
- Phase 1 pages only: shell + Overview, Imports, Exceptions, Vendors & Mapping (`Sources.jsx` + `Vendors.jsx`).
- Out-of-scope pages (Deliveries, Rules, Analytics, Governance) must keep working; do not delete CSS classes they still use.
- Keep `ui.jsx` export names and Modal behaviour (stacking, focus trap, Escape, scroll lock, optional nav).
- `npm run build` and `npm run build:demo` must both succeed; demo single-file must include styles.
- No backend / demo-kit / API contract changes.
- Commits: only if the user explicitly asked to commit; otherwise skip commit steps.
- After code changes: `graphify update .` once at the end (not every task).
- Before UI code for a task that changes look: follow `ui-ux-pro-max` domain/stack search if that skill is available in the session.

## Review Focus

- `npm run build:demo` after Tailwind — CSS must appear in the single HTML file (not a missing external sheet).
- Narrow viewport (≤760px) — rail becomes top strip; nav still scrollable; no broken grid.
- Persona switch / vendor scope — still remounts page and scopes API via existing `api.js` (no regression).
- Modal open → Escape / backdrop — still closes top modal only; body scroll locked while open.
- Governance “Load demo” / Overview “Demo setup…” — still reachable and functional after Overview restyle.

---

## File structure

| File | Responsibility |
|---|---|
| `frontend/package.json` | Add Tailwind, postcss, cva, clsx, tailwind-merge, needed Radix packages |
| `frontend/tailwind.config.js` | Theme extends from CSS vars; content paths |
| `frontend/postcss.config.js` | Tailwind + autoprefixer |
| `frontend/src/index.css` | `@tailwind` layers + keep/import token `:root` block (or move tokens here from `styles.css`) |
| `frontend/src/styles.css` | Shrink to legacy layout helpers still needed by out-of-scope pages + modal/table utilities |
| `frontend/src/lib/utils.js` | `cn(...inputs)` via clsx + twMerge |
| `frontend/src/components/ui/button.jsx` | shadcn Button |
| `frontend/src/components/ui/card.jsx` | Card primitives for Panel façade |
| `frontend/src/components/ui/badge.jsx` | Badge for Status/Tier chrome |
| `frontend/src/components/ui/input.jsx` | Input |
| `frontend/src/components/ui/tabs.jsx` | Tabs (optional if existing Tabs restyled via Tailwind classes instead) |
| `frontend/src/ui.jsx` | Façade: wire Panel/Kpis/Status/Toast to new components; restyle Modal classes |
| `frontend/src/App.jsx` | Shell rewrite with Tailwind |
| `frontend/src/main.jsx` | Import `index.css` (+ keep legacy `styles.css` as needed) |
| `frontend/src/pages/Overview.jsx` | Presentation pass |
| `frontend/src/pages/Imports.jsx` | Presentation pass |
| `frontend/src/pages/Exceptions.jsx` | Presentation pass |
| `frontend/src/pages/Sources.jsx` | Presentation pass |
| `frontend/src/pages/Vendors.jsx` | Presentation pass (list/workspace chrome) |
| `frontend/scripts/check-cn.mjs` | Tiny Node self-check for `cn` |
| `frontend/README.md` | Note Tailwind major + how to add a shadcn component |

---

### Task 1: Tailwind scaffold + `cn` + token bridge

**Files:**
- Create: `frontend/tailwind.config.js`, `frontend/postcss.config.js`, `frontend/src/lib/utils.js`, `frontend/src/index.css`, `frontend/scripts/check-cn.mjs`
- Modify: `frontend/package.json`, `frontend/src/main.jsx`
- Keep: existing `:root` token values from `styles.css` (copy into `index.css` or `@import` them)

**Interfaces:**
- Produces: `cn(...inputs: any[]) => string` in `frontend/src/lib/utils.js`
- Produces: Tailwind utilities resolving `bg-background`, `text-foreground`, `bg-accent`, `bg-rail` (or equivalent names mapped to CSS vars)
- Consumes: existing CSS variable names `--bg`, `--surface`, `--ink`, `--accent`, `--rail`, etc.

- [ ] **Step 1: Write the failing self-check**

```js
// frontend/scripts/check-cn.mjs — assert cn merges and twMerge wins on conflicts
import { cn } from "../src/lib/utils.js";
import assert from "node:assert/strict";
assert.equal(cn("px-2", "px-4"), "px-4");
assert.ok(cn("a", false && "b", "c").includes("a") && cn("a", false && "b", "c").includes("c"));
console.log("check-cn ok");
```

- [ ] **Step 2: Run check to verify it fails**

Run: `cd frontend && node scripts/check-cn.mjs`  
Expected: FAIL (module not found)

- [ ] **Step 3: Install deps + implement `cn` + Tailwind config + token CSS**

Install (exact majors flexible within Tailwind **v3**): `tailwindcss@3 postcss autoprefixer class-variance-authority clsx tailwind-merge`.  
`tailwind.config.js` `content`: `["./index.html", "./src/**/*.{js,jsx}"]`.  
Map theme colors to `var(--…)` from existing tokens.  
`index.css`: `@tailwind base/components/utilities` + full `:root` / dark theme blocks moved or duplicated from `styles.css`.  
`main.jsx`: `import "./index.css"` then `import "./styles.css"` (legacy still loaded).

- [ ] **Step 4: Run self-check + prove builds see Tailwind**

Run: `cd frontend && node scripts/check-cn.mjs`  
Expected: `check-cn ok`

Run: `cd frontend && npm run build`  
Expected: success; grep `dist/assets/*.css` (or JS-injected CSS) for a known utility you add temporarily to `App.jsx` like `sr-only` / or confirm Tailwind base present.

Run: `cd frontend && npm run build:demo`  
Expected: success; `dist-demo/index.html` contains substantial CSS (search for `--accent` or `.shell`).

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 2: shadcn primitives + `ui.jsx` façade (Panel, Kpis, Status, Button classes, Toast)

**Files:**
- Create: `frontend/src/components/ui/button.jsx`, `card.jsx`, `badge.jsx`, `input.jsx` (minimal set)
- Modify: `frontend/src/ui.jsx` (Panel, Kpis, Status, ToastHost visuals; keep hooks/API identical)
- Modify: `frontend/src/styles.css` only if Button/Panel classnames move to Tailwind and legacy `.btn`/`.panel` need thin compatibility aliases for out-of-scope pages

**Interfaces:**
- Consumes: `cn` from `lib/utils.js`
- Produces (unchanged signatures):
  - `Panel({ title, actions, children, pad = true, sub })`
  - `Kpis({ items: { label, value, detail? }[] })`
  - `Status({ s })`, `Tier({ t })`, `ToastHost`, `useToast`
- Produces: `Button` optional re-export **or** keep `.btn` / `.btn.primary` working via Tailwind `@apply` in `styles.css` so pages need not change class names in this task

- [ ] **Step 1: Add a tiny export smoke in `check-cn.mjs` (or sibling `check-ui-exports.mjs`)**

Assert `STATUS_CLASS` mapping still used: import nothing heavy — instead assert after façade change that `human("pending_checker") === "pending checker"` still holds (already in ui.jsx). Extend check file:

```js
import { human } from "../src/ui.jsx"; // only if Node can load JSX — if not, keep human test in a .js extract OR skip and rely on lint+build
```

**If Node cannot import JSX without a loader:** do not fight it — verification for this task is `npm run lint` + `npm run build` + visual: Overview still shows KPIs. Document that in the step result.

- [ ] **Step 2: Implement Button/Card/Badge/Input + restyle façade**

Panel → Card shell with denser header. Kpis → elevated strip with clearer type. Status → Badge colours via existing `STATUS_CLASS`. Toast → same API, updated classes. Prefer `@apply` on `.btn`, `.panel`, `.kpi`, `.pill` so Deliveries/Rules keep working without edits.

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run lint && npm run build && npm run build:demo`  
Expected: all pass

Manual: open `npm run dev`, Overview KPIs + a toast from any action still appear.

- [ ] **Step 4: Commit** (skip unless user asked)

---

### Task 3: Shell rewrite (`App.jsx`)

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/styles.css` — remove or slim shell rules replaced by Tailwind (keep mobile behaviour)

**Interfaces:**
- Consumes: `ToastHost`, `useApi`, `PAGES`, persona/vendor APIs unchanged
- Produces: same props to pages: `go`, `persona`, `vendor`, `pickVendor`, `vendors`, `reloadVendors`

- [ ] **Step 1: Rewrite shell markup with Tailwind**

Keep hash routing, ErrorBoundary, vendor scope, exception count badge, DEMO tag, Cognito vs persona foot. Active nav: inset accent bar (desktop) / bottom accent (mobile ≤760px).

- [ ] **Step 2: Verify responsive + all eight nav targets**

Run: `cd frontend && npm run lint && npm run build`  
Manual: resize to phone width — rail top strip; click every nav item including Governance; persona switch remounts main.

- [ ] **Step 3: Commit** (skip unless user asked)

---

### Task 4: Modal restyle (behaviour-preserving)

**Files:**
- Modify: `frontend/src/ui.jsx` (`Modal`, `ConfirmModal`, `ReasonModal` chrome only)
- Modify: `frontend/src/styles.css` (`.scrim`, `.modal*` — Tailwind-aligned tokens / elevation)

**Interfaces:**
- Consumes / Produces: existing `Modal({ title, sub, onClose, children, footer, actions, size, nav, busy, className })` — **no signature change**

- [ ] **Step 1: Restyle only**

Do **not** replace with Radix Dialog in this task. Keep stacking array, focus trap, Escape, body.modal-open, sizes sm/md/lg/xl.

- [ ] **Step 2: Verify Review Focus modal behaviours**

Manual: open Import batch modal or Exception detail → Escape closes; open ReasonModal from a flow if available; body does not scroll behind.  
Run: `cd frontend && npm run build`

- [ ] **Step 3: Commit** (skip unless user asked)

---

### Task 5: Overview presentation pass

**Files:**
- Modify: `frontend/src/pages/Overview.jsx`

**Interfaces:**
- Consumes: `Panel`, `Kpis`, `Loading`, charts, `go("governance"|"imports"|"exceptions")`
- No new API fields

- [ ] **Step 1: Upgrade page-head, KPI strip usage, panel layout, CTA row**

Keep Demo setup button gating (`!DEMO && cfg.demo && demo_setup.available && admin`). Charts stay `charts.jsx`.

- [ ] **Step 2: Verify**

Manual: Overview loads against API; Demo setup… still goes to governance when eligible; charts render.  
Run: `cd frontend && npm run lint`

- [ ] **Step 3: Commit** (skip unless user asked)

---

### Task 6: Imports presentation pass

**Files:**
- Modify: `frontend/src/pages/Imports.jsx`

**Interfaces:**
- Unchanged `api` / `scoped` / dialogs; presentation of tables, drop zone, BatchModal chrome only

- [ ] **Step 1: Upgrade page-head, KPIs, table density, drop zone, modal chrome classes**

- [ ] **Step 2: Verify**

Manual: list batches; open one batch modal; upload drop zone still highlights.  
Run: `cd frontend && npm run lint`

- [ ] **Step 3: Commit** (skip unless user asked)

---

### Task 7: Exceptions presentation pass

**Files:**
- Modify: `frontend/src/pages/Exceptions.jsx`

**Interfaces:**
- Unchanged claim/resolve/API; denser queue, Tier/Status badges, filters/tabs

- [ ] **Step 1: Upgrade queue layout, tier badges, detail panel chrome**

- [ ] **Step 2: Verify**

Manual: open Exception Manager; tier filters; open an exception modal; claim/release if data present.  
Run: `cd frontend && npm run lint`

- [ ] **Step 3: Commit** (skip unless user asked)

---

### Task 8: Vendors & Mapping presentation pass

**Files:**
- Modify: `frontend/src/pages/Sources.jsx`, `frontend/src/pages/Vendors.jsx`
- Touch `FeedConfig.jsx` / `DeliveryProfile.jsx` only if shared chrome classes break — prefer fixing via legacy CSS aliases

**Interfaces:**
- Unchanged vendor/mapping APIs; `VendorList` / `VendorWorkspace` exports stay

- [ ] **Step 1: Upgrade list/workspace hierarchy, mapping tables, status chips**

- [ ] **Step 2: Verify**

Manual: open Vendors & Mapping; select a vendor; mapping table usable.  
Run: `cd frontend && npm run lint && npm run build && npm run build:demo`

- [ ] **Step 3: Commit** (skip unless user asked)

---

### Task 9: Legacy CSS trim + docs + graphify

**Files:**
- Modify: `frontend/src/styles.css` (remove dead shell rules only after grepping usages)
- Create/Modify: `frontend/README.md` (Tailwind v3, how to add components under `components/ui`)
- Run: `graphify update .`

**Interfaces:** none new

- [ ] **Step 1: Grep before delete**

For any class you remove from `styles.css`, run ripgrep under `frontend/src` and keep the rule if referenced by Deliveries/Rules/Analytics/Governance/FeedConfig/DeliveryProfile.

- [ ] **Step 2: Final verification (Review Focus checklist)**

Run:

```bash
cd frontend && npm run lint && npm run build && npm run build:demo
# confirm dist-demo/index.html contains --accent or .shell
rg -n "accent|shell" dist-demo/index.html | head
```

Manual checklist:

- [ ] Desktop shell + four upgraded pages look elevated (not flat grey soup)
- [ ] ≤760px rail → top strip
- [ ] All eight pages open without error boundary
- [ ] Persona + vendor scope still work
- [ ] Modal Escape / scroll lock
- [ ] Overview → Demo setup… → Governance when eligible
- [ ] `build:demo` HTML self-contained with CSS

- [ ] **Step 3: `graphify update .`** from repo root

- [ ] **Step 4: Commit** (skip unless user asked)

---

## Self-review notes (author)

- Spec §1–9 covered by Tasks 1–9; Phase 2 Next.js explicitly not tasked.
- Modal Radix swap deferred (Task 4 restyle only) per spec risk mitigation.
- `cn` gets a real automated check; JSX façade relies on lint/build/manual where Node cannot import JSX — called out in Task 2.
- Proportion: tasks describe signatures and checks, not full page JSX transcripts.
