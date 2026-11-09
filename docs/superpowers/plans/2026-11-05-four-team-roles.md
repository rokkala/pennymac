# Four-team roles Implementation Plan

> **For agentic workers:** Native execution on `feature/app-ux-phase-a`.

**Goal:** Replace legacy Cognito roles with seven team groups (member + reviewer + admin).

**Spec:** `docs/superpowers/specs/2026-11-05-four-team-roles-design.md`

## Tasks

- [x] `security.ROLES` + `expand_roles` / aliases
- [x] `ROUTE_ROLES` / CAPS / DEFAULT_ACCESS / DEMO_CAST
- [x] Business-layer role checks + demo_setup / notifications
- [x] Terraform Cognito groups
- [x] Frontend cast, mockApi, HowItWorks, Personas
- [x] Tests green for personas / security / notifications / demo_setup / mapping
