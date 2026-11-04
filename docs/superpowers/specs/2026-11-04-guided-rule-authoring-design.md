# Guided Rule Authoring — Design Spec

**Date:** 2026-11-04  
**Status:** Approved (conversational §§1–5); implementation authorized

## Intent

SMEs and Compliance author validation rules without writing JSON Logic or relying on English-only generation. Tech does not set up day-to-day rules.

## Architecture

Typed **tree AST** (AND/OR groups of leaf **shapes**) compiles server-side to JSON Logic + auto-tests. Optional AI assist fills the tree; SME confirms. Glue still evaluates `expression` from signed feed bundles.

## In scope

1. Template catalog + guided form + nested condition tree (depth ≤ 3)
2. Structured shapes API + persistence of `tree` alongside `expression`
3. New executor ops as needed: `xor`, `all_present`, `date_before`, `date_after`
4. Approval model B: friendlier console copy; non-regulatory = one peer SME; regulatory = peer + Compliance; HMAC publish unchanged
5. English → tree (not opaque DSL) as optional assist tab

## Shapes

`required`, `between`, `compare_num`, `compare_field`, `one_of`, `equals`, `digits`, `date_order`, `if_then`

## APIs

- `GET /api/rules/fields`, `/shapes`, `/templates`
- `POST /api/rules/compose` (preview)
- `POST /api/rules/author` → tree + compose preview
- `POST|PUT /api/rules` accept `tree` (preferred) or legacy `expression`

## Persistence

Rule version body stores `tree` + compiled `expression` + `tests`. Bundles still publish `expression`; `tree` optional console metadata.

## Approval

- Author cannot self-approve
- No `regulatory_tag` → one peer SME → `approved`
- With `regulatory_tag` → peer + Compliance
- Adding regulatory tag after peer approval re-opens Compliance gate before deploy
- SME-facing lifecycle labels (see plan)

## Testing

Unit (shapes round-trip, new ops), API compose/create, registry approval matrix, existing rules/executor regression.

## Out of scope (explicit)

Changing how Glue verifies HMAC signatures; free expression editor as the default SME path.
