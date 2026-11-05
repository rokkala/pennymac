# App UX full rebuild (IA + visual system + every page)

**Date:** 2026-11-05  
**Status:** implemented on `feature/app-ux-phase-a` — Phases A–D; plans in `docs/superpowers/plans/2026-11-05-app-ux-phase-a.md` and `docs/superpowers/plans/2026-11-05-app-ux-phases-b-d.md`  
**Classification:** architectural  
**Audience choice:** **C** — demo walkthrough **and** day-to-day operators  
**Approach choice:** **3** — full visual + information-architecture rebuild (every page)

Supersedes the *delivery scope* of `2026-11-03-frontend-ui-design-system-design.md` (Phase 1 was **reverted**). Visual DNA from that doc (teal accent, dark rail, Archivo + IBM Plex) remains locked. Rule-engine authoring / review / notifications specs stay in force; this doc reorganizes how people *find* and *finish* work across the console.

---

## Intent

Make the Loan Boarding Console feel like one coherent product: a stakeholder can walk the story without getting lost, and an operator can see **what to do next** for their role without hunting through a flat nav of eleven peers.

**Success criteria**

1. **Nav teaches the job.** Sections read as **Setup → Run → Govern** (plus Guide), not an unordered list of screens.
2. **Overview does two jobs.** Demo / story lane *and* persona-scoped “Your work today” queues (exceptions, rule reviews, deliveries waiting, drafts needing approval).
3. **One primary action per context.** Page headers and item rows follow the Rules ActionBar pattern: one primary CTA, secondary/overflow for the rest; no duplicate buttons that hide the real next step.
4. **Every page uses the same chrome.** Shared `PageHeader`, `Section`, `EmptyState`, `ActionBar`, status/tier language, and modal sizes — visually upgraded end-to-end, not a partial restyle.
5. **How it works stays the map.** Guide steps deep-link into the right page (and, where cheap, the right tab/queue); persona filtering already present stays.
6. **Contracts unchanged.** FastAPI routes, maker-checker, Cognito/persona simulation, vendor scope, `build` / `build:demo` keep working. No backend feature work in this rebuild unless a UX need forces a tiny read-only aggregate (see §6).

**Non-goals**

- Next.js / App Router / RSC migration.
- Replacing Cognito or inventing a second brand (no purple/indigo SaaS look; no cream+serif editorial; no broadsheet).
- Rewriting Glue, signing, or pipeline behaviour.
- Re-litigating guided rule authoring / peer-pool notifications (keep those behaviours; only fit them into the new shell patterns).
- Retrying Tailwind + shadcn in this program (see §2 — Phase 1 was rolled back).

---

## Decisions locked

| Decision | Choice |
|---|---|
| Audience | **C** — dual: demo story + operator queues |
| Scope | **3** — IA + full visual rebuild of **all** pages in `PAGES` |
| Delivery | **Phased full rebuild** (A→D below). Spec covers the whole product; implementation plans are one phase at a time |
| Stack | **Evolve existing Vite + hand CSS + `ui.jsx`** into a tokenized design system and shared layout primitives. **Do not** reintroduce Tailwind/shadcn unless a later plan proves `build:demo` parity and the prior rollback reason is resolved in writing |
| Visual DNA | Keep servicing teal + dark rail + Archivo / IBM Plex; denser hierarchy and clearer surfaces |
| Routing | Keep hash routing + `PAGES` registry; add **nav groups** and optional hash query conventions (`#rules?queue=…` already exists — extend consistently) |
| Capability gates | Keep `roles.js` / `canCap` / screen allow-lists; IA must not expose actions the persona cannot perform |

---

## Current pain (facts)

- Flat nav: Overview, How it works, Import Monitor, Vendor Deliveries, Vendors & Mapping, Exception Manager, Rule Engine, Analytics, Policy & Audit, Maintenance, Personas — no Setup/Run/Govern grouping.
- Overview is executive charts only; CTAs are generic (“Work exceptions”) and do not surface *my* rule-review queue, mapping approvals, or delivery waits.
- Pages share ad-hoc headers and button rows; Rules was recently cleaned up, but Imports / Exceptions / Sources / Governance still mix many equal-weight buttons.
- ~4.5k lines of page UI + one `styles.css` / `ui.jsx` façade; prior Tailwind Phase 1 did not stick.

---

## Design

### 1. Information architecture

**Rail structure (always visible groups; items still capability-filtered):**

```text
Guide
  · How it works

Setup
  · Vendors & Mapping     (sources)
  · Rule Engine           (rules) + notification badge
  · Vendor Deliveries     (deliveries)   ← schedule / pull side of setup+run

Run
  · Overview              (home)
  · Import Monitor        (imports)
  · Exception Manager     (exceptions) + open-count badge
  · Analytics             (analytics)

Govern
  · Policy & Audit        (governance)
  · Maintenance           (maintenance, capability-gated)
  · Personas              (personas, admin-gated)
```

**Notes**

- **Overview stays under Run** (operator home) but also hosts the demo story strip — see §3.
- **Deliveries** sits under Setup because schedule/profile work is setup-shaped; deep links from Run (Import Monitor “pull now”) still land there. Label in rail can stay “Vendor Deliveries”.
- **How it works** is first under Guide so demos start there or from Overview’s “Walk the product” CTA.
- Do **not** rename page `id`s (`sources`, `rules`, …) — only labels/grouping and deep-link queries change. Bookmark hashes keep working.

**Cross-links (required pattern)**

Every page header may include a single text link “Why this step” → `#guide` with optional `?step=<id>` matching `HowItWorks` step ids (`vendor`, `mapping`, `arrive`, …). Guide steps already `go(page)`; extend to `go(page, qs)` where queues exist.

### 2. Visual / component system (no Tailwind retry)

**Tokens** (`styles.css` or split `tokens.css` imported once): keep existing CSS variables; add explicit type scale, spacing rhythm (4/8/12/16/24), surface elevation (`--surface`, `--surface-2`, `--elevated`), and semantic action colors for primary / danger / quiet. Light + `prefers-color-scheme` / `data-theme` dark remain.

**Primitives** (implement in `ui.jsx` or thin `layout/*.jsx` imported by pages — public API stays stable where possible):

| Primitive | Job |
|---|---|
| `PageHeader` | Eyebrow + title + one-line sub + **primary** slot + optional secondary/overflow |
| `Section` / `Panel` | Titled block; Panel stays for charts/tables |
| `ActionBar` | Row/item actions: one `.primary`, rest `.btn` / menu |
| `EmptyState` | Title, one sentence, one CTA |
| `QueueCard` | Count + label + CTA for Overview “Your work today” |
| `NavGroup` | Rail group label + links |
| `Status` / `Tier` | Unchanged semantics; restyle only |
| `Modal` family | Behaviour parity mandatory (stack, focus trap, Escape, in-flight block, sm/md/lg/xl) — restyle chrome, do not swap for Radix unless a dedicated task proves parity |

**Motion:** 150–250ms hover/focus transitions; respect `prefers-reduced-motion`. No glow-heavy effects.

**Icons:** Lucide or Heroicons SVG only if needed; no emoji as UI icons.

### 3. Overview — dual audience home

Replace chart-only home with a **two-band** layout (one composition, not a widget dashboard dump):

**Band A — Story (demo / stakeholder)**  
Short product line + KPI strip (keep existing executive KPIs) + primary CTA **Walk the product** → guide. Optional **Demo setup…** when capability + config allow (unchanged gate).

**Band B — Your work today (operator)**  
Persona-scoped cards only when counts > 0 or capability applies:

| Card | Shown when | Goes to |
|---|---|---|
| Open exceptions | `workExceptions` | `#exceptions` |
| Rules awaiting your review | notifications unread / awaiting_review (not author) | `#rules?queue=awaiting_review` |
| Batches needing attention | ops/sme relevant stuck/held if API already exposes (else omit — no new backend in Phase A) | `#imports` |
| Mapping / delivery approvals | if existing APIs already expose pending counts; else link to Sources with copy “Check approvals” without fake numbers | `#sources` |
| Policy / kill-switch | compliance | `#governance` |

Charts move **below** Band B or behind a “Trends” disclosure so the first viewport answers “what should I do?” Charts must not dominate the first screen on operator personas.

### 4. Page-by-page intent (full rebuild checklist)

Behaviour and APIs stay; presentation + action hierarchy change.

| Page | Rebuild focus |
|---|---|
| **How it works** | Grouped Setup/Execution already exists; add step deep-link query; visual align to PageHeader; clearer “You do this” vs “Ask …” |
| **Overview** | §3 dual home |
| **Imports** | PageHeader; batch list ActionBar; modal chrome; one primary per batch state |
| **Deliveries** | Same patterns; schedule approval primary when pending |
| **Vendors & Mapping** | Clear list → workbench hierarchy; publish / approve as primary when that is the next gate |
| **Exceptions** | Queue-first; claim/resolve primary; tier filters quieter |
| **Rules** | Keep linear author + review CTAs; only adapt to shared PageHeader/ActionBar tokens |
| **Analytics** | PageHeader + panel rhythm; no new metrics |
| **Governance** | Policy vs audit vs demo-setup sections; kill switch visually unmistakable |
| **Maintenance** | Templates + glue jobs as sections with one job each |
| **Personas** | Admin table clarity; no visual parity with consumer pages required beyond tokens |

### 5. Interaction rules (product-wide)

1. **One primary per visible context** (page, row, or modal footer).
2. **Author ≠ approver** UI remains fail-closed (Rules and any dual-control elsewhere).
3. **Destructive** actions always confirm / reason via existing Confirm/Reason modals.
4. **Empty states** never show a dead table; always one sentence + next step.
5. **Vendor scope bar** stays; copy stays plain language.
6. **Badges** on Exceptions and Rules only (open work / unread reviews).

### 6. Data flow and optional API

```text
Shell (grouped nav, badges)
  → Page (PageHeader + body)
    → ui primitives
    → api.js / mock (unchanged contracts)

Overview Band B prefers existing endpoints:
  /api/exceptions/summary, /api/notifications, /api/analytics/executive, …
```

**Optional (Phase B+ only if a card would otherwise lie):** a single read-only `GET /api/workbench/summary` aggregating pending counts. Default plan: **no new endpoint** until Phase A ships with links-without-counts where data is missing.

### 7. Accessibility and errors

- Keep ErrorBoundary; restyle to system Panel.
- Focus-visible rings; Modal focus trap; keyboard nav for queues.
- Status/tier never colour-only.
- Contrast ≥ 4.5:1 on text; rail ink already constrained — do not lighten active nav below contrast.

### 8. Testing and verification

Per phase:

- `npm run lint` on touched files.
- Manual persona matrix: Ops, Analyst, SME, Reviewer, Checker, Compliance, Admin — each sees correct nav groups and Overview cards.
- `npm run build` and `npm run build:demo`; open demo once for shell + Overview + one Setup + one Run page.
- No Playwright suite required unless already present (YAGNI).

### 9. Phased delivery (implementation plans map 1:1)

| Phase | Ships | Exit gate |
|---|---|---|
| **A — Shell + home + guide** | Nav groups, tokens/primitives (`PageHeader`, `NavGroup`, `QueueCard`, `EmptyState`, `ActionBar`), Overview dual home, How it works deep links, ErrorBoundary restyle | Demo walk Overview→Guide→one Setup page works; operator persona sees at least exception + rule-review cards when data exists |
| **B — Run path** | Imports, Exceptions, Analytics (+ Deliveries chrome if not done in C) | Operator can upload/work exceptions without button clutter |
| **C — Setup path** | Sources/Vendors/Feed/DeliveryProfile surfaces, Rules token alignment, Deliveries if deferred | SME can complete mapping→publish path with clear primaries |
| **D — Govern + sweep** | Governance, Maintenance, Personas; grep leftover one-off headers; trim dead CSS | All eleven pages share chrome; demo + live smoke |

**Do not start Phase B code until Phase A is merged and accepted.** Each phase gets its own `writing-plans` document after this spec is approved.

### 10. Risks

| Risk | Mitigation |
|---|---|
| Scope balloons into product features | Hard rule: presentation + IA only; optional summary API is the only backend exception |
| Tailwind temptation mid-flight | Locked out in this spec; reopen only with written rollback postmortem |
| Overview becomes a noisy dashboard | Band A/B composition rule; charts demoted |
| Hash/query breaks bookmarks | Keep page ids; only add query params |
| Dual-control modal regression | Restyle Modal; parity checklist before any behaviour change |

---

## Out of scope (explicit)

- Changing Glue jobs, signing, or publish semantics.
- New rule DSL or exception tiers.
- Mobile-native apps.
- Rebrand away from PennyMac / LDS IntelliMap subtitle.

---

## Spec self-review

- No TBD placeholders left for blocking decisions; optional workbench API is explicitly deferred.
- Consistent with audience C + approach 3; phased so one plan is not the entire rewrite.
- Stack decision consistent with reverted Phase 1 (no contradiction with “full visual rebuild” — rebuild UX/IA/pages on evolved CSS system).
- Page ids preserved; Rules prior work not undone.

---

## Approval

Please review this file and say whether to proceed to the **Phase A implementation plan** (shell + Overview + guide only), or request edits first.
