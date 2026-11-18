# Four teams + in-team reviewers

**Date:** 2026-11-05  
**Status:** approved (chat) — implementing on `feature/app-ux-phase-a`  
**Classification:** architectural  

## Intent

Simplify the product around **four teams**. Within each team (except platform admin), a **reviewer** can review and accept. Cognito uses **seven groups** (not a flag).

## Cognito / `ROLES`

| Group | Powers |
|---|---|
| `onboarding` | Draft mapping, draft rules, propose schedules / delivery profiles |
| `onboarding_reviewer` | All onboarding + approve mapping, peer-approve rules, approve schedules |
| `monitoring` | Boarding desk, upload, pause/resume, pull/waive, T2–T3, T4 maker |
| `monitoring_reviewer` | All monitoring + T4 checker (≠ maker) |
| `compliance` | Read/investigate compliance queues (narrow) |
| `compliance_reviewer` | T5 clear, policy / kill switch, regulated-rule gate, audit |
| `admin` | Users, maintenance, demo; bypasses role checks |

**Rule:** reviewer ⊇ member for that team (expanded when building `Principal` / frontend `can()`).

## Ownership

- Rule **setup** → onboarding · peer **accept** → onboarding_reviewer · **regulated** gate → compliance_reviewer  
- Loads / desk → monitoring · T4 checker → monitoring_reviewer  
- T5 / policy / audit → compliance_reviewer  

## Demo cast (6)

1. Onboarding  
2. Onboarding reviewer  
3. Monitoring  
4. Monitoring reviewer  
5. Compliance reviewer  
6. Platform admin  

## Legacy aliases (dev / old headers / leftover data)

`analyst`→`onboarding`, `sme`→`onboarding_reviewer`, `ops`→`monitoring`, `reviewer`→`monitoring`, `checker`→`monitoring_reviewer`, `compliance`→`compliance_reviewer`.

## Non-goals

- Renaming every page  
- Flag-based reviewer encoding  
- Keeping Priya/Dan/Maria/Lee/Ana as product truth  
