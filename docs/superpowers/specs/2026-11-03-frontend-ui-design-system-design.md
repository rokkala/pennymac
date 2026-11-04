# Frontend UI design system (Phase 1)

**Date:** 2026-11-03  
**Status:** reverted — Phase 1 UI rollback (original hand CSS restored)  
**Classification:** architectural

## Intent

Make the Loan Boarding Console feel like a finished **enterprise BFSI** product for live demos and day-to-day ops — denser hierarchy, clearer surfaces, shared controls — without rewriting the product or abandoning the existing teal / dark-rail identity.

**Success criteria**

- Shell (rail, brand, nav, persona/vendor controls, toasts, page chrome) reads as a coherent design system, not a flat CSS dump.
- Overview, Import Monitor, Exception Manager, and Vendors & Mapping use the new primitives and look materially upgraded in a sales walkthrough.
- Existing FastAPI + Vite SPA + `build:demo` (single-file mock) paths keep working.
- Teal accent + dark rail DNA preserved; no purple/generic SaaS rebrand.
- Out-of-scope pages (Deliveries, Rules, Analytics, Governance) keep working via shared primitives / CSS compatibility; they are not redesigned in Phase 1.

**Non-goals**

- Migrating to Next.js / App Router / RSC in Phase 1.
- Replacing Cognito / auth / persona simulation.
- Changing backend APIs or demo-kit setup behaviour.
- Pixel-perfect redesign of every secondary page.
- Introducing a second visual brand or light-only theme drop.

## Decisions already locked

| Decision | Choice |
|---|---|
| Delivery strategy | **C** — phased: Vite design system first; Next.js only if later justified |
| Visual direction | **A + C** — enterprise BFSI density + keep teal / rail DNA |
| Phase 1 page scope | **C** — shell + Overview / Imports / Exceptions / Vendors & Mapping |
| Stack approach | **1** — Vite + Tailwind + shadcn/ui (keep FastAPI API) |

## Current state (facts)

- Frontend is a Vite React 18 SPA (`frontend/`), hash routing in `App.jsx`, no React Router.
- Styling is one hand-written `styles.css` (~270 lines) with CSS variables (teal `--accent`, dark `--rail`, Archivo + IBM Plex).
- Shared UI lives in `ui.jsx` (Panel, Kpis, Modal, Status, ToastHost, useApi, etc.) and `charts.jsx` (SVG charts).
- Nav label **Vendors & Mapping** → page id `sources` → `pages/Sources.jsx`, which composes `Vendors.jsx`, `FeedConfig.jsx`, `DeliveryProfile.jsx`.
- Dependencies today: `react`, `react-dom`, Vite, ESLint only — no Tailwind, no component library, no router.
- Builds: `npm run build` → `dist/` (API / CDN); `npm run build:demo` → single-file `dist-demo` via `vite-plugin-singlefile`.
- Demo setup UI already lands on Overview CTA → Governance; Governance stays out of Phase 1 visual rewrite but must remain reachable and functional.

## Design

### 1. Stack and tooling

Stay on **Vite + React 18**. Add:

- **Tailwind CSS** — default **v3** with the official Vite plugin (safest with `vite-plugin-singlefile`); use **v4** only if the install is one-line clean and `build:demo` still inlines CSS. Document the chosen major in `frontend/README` or root README when implemented.
- **shadcn/ui** pattern: copy Radix-backed components into `frontend/src/components/ui/` (not a runtime npm “shadcn package”).
- **class-variance-authority** + **clsx** / **tailwind-merge** as used by shadcn scaffolds.
- Keep **hash routing** and `PAGES` registry in `App.jsx` for Phase 1 (no React Router unless a plan task proves hash + shadcn conflicts — unlikely).

**Do not** add MUI, Chakra, or Ant Design.

`package.json` scripts (`dev`, `build`, `build:demo`, `preview`, `lint`) stay; Tailwind must work in both normal and demo single-file builds (verify CSS inlining for `build:demo`).

### 2. Design tokens

Map existing `:root` variables into Tailwind theme extension / CSS variables so both Tailwind utilities and any remaining legacy classes share one source of truth.

Preserve (names may alias, values stay in the same family):

| Token role | Keep |
|---|---|
| Accent | servicing teal (`#0b6e72` light / `#4fb8b8` dark) |
| Rail | dark slate (`#14262e` / `#0a1216`) |
| Surfaces | elevated white / dark panels with soft shadow |
| Semantic | pass / warn / fail + exception tiers T1–T5 |
| Type | Archivo (display), IBM Plex Sans (body), IBM Plex Mono |

Add (minimal):

- Clearer **type scale** (page title, section, body, caption) as Tailwind `text-*` or CSS vars.
- **Spacing rhythm** (4/8/12/16/24) used by shell and panels.
- **Surface elevation** steps (`surface`, `surface-2`, optional `elevated`) — fix “everything same flat grey.”
- Keep existing **light / dark** via `prefers-color-scheme` and `data-theme` (do not invent a third theme).

Explicitly **avoid**: purple/indigo gradients, cream+serif editorial look, broadsheet hairline newspaper layout, glow-heavy dark neon.

### 3. Shell

Rewrite the chrome in `App.jsx` (and extracted shell pieces if needed) using new primitives while keeping behaviour:

- Brand block: “Loan Boarding Console” + subtitle.
- Vendor scope select + All vendors.
- Nav with active inset accent bar; exception open-count badge.
- Rail foot: Cognito user or persona select; DEMO tag when `VITE_DEMO`.
- Main: vendor scope bar; `ErrorBoundary`; page slot.
- `ToastHost` — restyle to match system; API stays the same (`useToast`).

Mobile: existing “rail becomes top strip” behaviour must remain usable (Tailwind responsive classes replacing media queries in `styles.css`).

### 4. Shared primitives migration

**Strategy:** keep `ui.jsx` as the **public façade** pages import today (`Panel`, `Kpis`, `Modal`, `Status`, `Tier`, `Button`-via-class, etc.), but implement those façades with shadcn/Tailwind under the hood where Phase 1 touches them. Avoid a big-bang “every file imports `@/components/ui/button`” unless a page is already being rewritten.

Minimum Phase 1 component set (shadcn-based or thin wrappers):

- Button, Input, Select, Badge / Status pill, Card / Panel, Tabs, Dialog (Modal), Tooltip (optional), Separator, Toast.

**Modal:** current `ui.jsx` Modal has stacking, focus trap, Escape, body scroll lock, optional nav. Replacement must preserve those behaviours or keep the existing Modal implementation behind the same export until a dedicated follow-up — **do not regress dual-control / reason flows**. Prefer: restyle existing Modal first; full Radix Dialog swap only if behaviour parity is verified.

**Charts:** leave `charts.jsx` SVG implementation; only adjust surrounding Panel/KPI chrome and token colours (`var(--chart-*)`).

**Legacy CSS:** after shell + in-scope pages migrate, shrink `styles.css` to tokens + any page-specific leftovers still needed by out-of-scope pages. Do not delete classes still referenced by Deliveries / Rules / Analytics / Governance.

### 5. In-scope pages

| Nav label | File(s) | Upgrade focus |
|---|---|---|
| Overview | `Overview.jsx` | Page head, KPIs, panels, CTAs (incl. Demo setup → governance) |
| Import Monitor | `Imports.jsx` | Page head, tables/lists, batch modal chrome, actions |
| Exception Manager | `Exceptions.jsx` | Queue density, tier badges, filters, claim/resolve actions |
| Vendors & Mapping | `Sources.jsx` + `Vendors.jsx` (+ FeedConfig/DeliveryProfile chrome only as needed) | List/workspace hierarchy, mapping tables, status |

Behaviour and API calls stay the same; this is a **presentation** pass. No new product features in Phase 1.

Out of scope for redesign (must keep working): Deliveries, Rules, Analytics, Governance (demo setup stays on Governance), DeliveryProfile deep flows beyond shared chrome, mock API internals.

### 6. Data flow and boundaries

```text
Browser → Vite SPA (hash page)
       → api.js / auth.js (unchanged contracts)
       → FastAPI /api  OR  in-browser mock (DEMO)

Shell + pages → ui.jsx façade → components/ui/* (shadcn)
             → charts.jsx
             → styles.css tokens (shared with Tailwind)
```

No backend changes. No new env vars required beyond existing Vite modes.

### 7. Error handling and a11y

- Keep `ErrorBoundary` on the page slot; restyle to system Panel.
- `:focus-visible` accent rings retained.
- Buttons/links remain keyboard operable; Modal focus trap retained.
- Status / tier colours must not be the only signal (keep text labels).
- Do not remove `aria-label`s already present on icon-only controls.

### 8. Testing and verification

- `npm run lint` clean on touched files.
- Manual: login/persona switch, vendor scope, navigate all eight pages, smoke Overview/Imports/Exceptions/Sources happy paths against running API.
- `npm run build` and `npm run build:demo` both succeed; open `dist-demo` once and confirm shell + Overview render.
- One small **visual smoke** note in the plan (checklist), not a Playwright suite unless already present — YAGNI.

### 9. Phase 2 gate (explicit, not scheduled)

Consider Next.js only if one of these becomes a real requirement:

- SSR / SEO for a public marketing surface (this console is authenticated / demo).
- File-based routing and RSC for a much larger UI team.
- Need to abandon static/`dist-demo` single-file distribution.

Until then, stay on Vite.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `build:demo` single-file breaks with Tailwind | Prove CSS inline early in implementation; adjust Vite/Tailwind config before page rewrites |
| Modal regression on dual-control | Keep behaviour-compatible Modal export; parity checklist before Radix swap |
| Out-of-scope pages look broken after CSS shrink | Compatibility pass: grep class usage before deleting legacy rules |
| Scope creep into all pages | Hard stop at four pages + shell; shared façade only for the rest |

## Implementation shape (for writing-plans — not yet approved to code)

Suggested plan order (detail in plan doc after this spec is approved):

1. Tailwind + shadcn scaffold + token bridge from existing CSS vars.
2. Shell rewrite in `App.jsx`.
3. Façade updates in `ui.jsx` (Button/Panel/Kpis/Toast/Status).
4. Overview → Imports → Exceptions → Sources/Vendors presentation pass.
5. Legacy CSS trim + build:demo verification + lint.

## Open questions

None blocking. Tailwind major is decided by §1 default (v3) with an escape hatch to v4.
