# Guided Rule Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let SMEs author any supported validation rule via templates, a typed form, and an AND/OR condition tree — without editing JSON Logic.

**Architecture:** Server-side shape/tree compiler produces JSON Logic + tests; registry stores `tree` + `expression`; console uses compose APIs; approval model B; new jsonlogic ops as needed.

**Tech Stack:** Python (`lbp.rules`), FastAPI, React (`Rules.jsx`), existing JSON Logic executor.

**Spec:** `docs/superpowers/specs/2026-11-04-guided-rule-authoring-design.md`

## Global Constraints

- SMEs never required to edit raw JSON Logic
- Glue continues to evaluate `expression` only; HMAC publish unchanged
- Tree depth ≤ 3; leaves are catalog shapes only
- Non-reg: one peer approve; reg: peer + Compliance; no self-approve

## Review Focus

- Wrong SSE field / dtype accepted
- Empty AND/OR group compiles
- Regulatory gate accidentally skipped
- Decompile failure leaves SME stuck with no Rebuild path
- New ops diverge between validate() and compile_logic()

## File map

| File | Role |
|---|---|
| `backend/lbp/rules/shapes.py` | Shape catalog, compile/decompile/summarize/autotest |
| `backend/lbp/rules/jsonlogic.py` | Add `xor`, `all_present`, `date_before`, `date_after` |
| `backend/lbp/rules/authoring.py` | English → tree AST |
| `backend/lbp/rules/registry.py` | Persist `tree`; approval model B already mostly correct |
| `backend/lbp/api/main.py` | fields/shapes/templates/compose endpoints; create/update accept tree |
| `backend/tests/test_shapes.py` | Shape/tree unit tests |
| `backend/tests/test_transforms_jsonlogic.py` | New ops |
| `backend/tests/test_rules.py` | Create-from-tree + approval |
| `frontend/src/pages/Rules.jsx` | Guided author/edit UI + SME lifecycle copy |

---

### Task 1: JSON Logic new operators

- [x] Write failing tests for `xor`, `all_present`, `date_before`, `date_after` in `test_transforms_jsonlogic.py`
- [x] Implement ops + validate allow-list
- [x] Run tests green

### Task 2: shapes compiler

- [x] Write failing tests in `test_shapes.py` for each leaf + and/or/xor tree + summarize + autotest
- [x] Implement `shapes.py`
- [x] Run tests green

### Task 3: API + registry

- [x] Write/extend API tests for compose, fields, shapes, templates, create with tree
- [x] Wire endpoints; create/update compile tree → expression
- [x] Run `test_rules.py` + API subset green

### Task 4: Authoring → tree

- [x] Update `draft_from_text` / author endpoint to return `tree` + compose preview
- [x] Tests for heuristic → tree

### Task 5: Frontend guided authoring

- [x] Replace AuthorModal/EditRuleModal with template → tree builder → preview → save
- [x] SME lifecycle labels from §4
- [x] Labels on all inputs; compose feedback on save

### Task 6: Verify

- [x] Full relevant pytest suite
- [x] `graphify update .`
