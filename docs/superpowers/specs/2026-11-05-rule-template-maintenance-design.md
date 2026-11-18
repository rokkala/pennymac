# Rule Template Maintenance — Design Spec

**Date:** 2026-11-05  
**Status:** Approved (conversational §§1–3); implementation authorized  
**Placement:** Maintenance (CRUD) + Rules Author (consume)

## Intent

SMEs/admins create and edit rule starter templates in the product without a code deploy. Authoring uses the live catalog.

## Persistence

Table `rule_templates`: `id`, `name`, `description`, `tree` (JSON), `builtin`, `hidden`, `version`, `updated_by`, `updated_at`.

Seed from `shapes.templates()` on migrate / idempotent startup. Built-ins cannot hard-delete; hide/unhide instead. Custom templates can be deleted.

Writes always run `compile_tree` before save.

## APIs

- `GET /api/rules/templates` — active (`hidden=false`) for Author
- `GET|POST /api/maintenance/rule-templates` — list all / create
- `PUT /api/maintenance/rule-templates/{id}` — update
- `POST .../hide` | `.../unhide`
- `DELETE .../{id}` — custom only

Roles: SME/admin (same as Maintenance + editRules). Audit events `rule_template.*`.

## UI

- Maintenance tabs: Jobs & code | Rule templates (list + tree editor + Preview/Save)
- Rules Author templates tab reads DB; optional link to Maintenance

## Out of scope

Publishing templates into Glue signed feed bundles.
