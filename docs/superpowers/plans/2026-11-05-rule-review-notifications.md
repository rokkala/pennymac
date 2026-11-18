# Plan: Rule review notifications (v1)

Spec: `docs/superpowers/specs/2026-11-05-rule-review-notifications-design.md`

## Files

- `backend/lbp/store/db.py` — `notifications` table
- `backend/migrations/versions/0006_notifications.py`
- `backend/lbp/notifications.py` — create/list/mark-read + peer recipients
- `backend/lbp/rules/registry.py` — emit on transition
- `backend/lbp/api/main.py` — routes + roles
- `backend/tests/test_notifications.py`
- `frontend/src/pages/Rules.jsx` — filters + author/peer CTA
- `frontend/src/App.jsx` — badge
- `frontend/src/mock/mockApi.js` — demo parity

## Tasks

1. DB + `notifications` module + tests (list/read + emit on in_review/approved/draft)
2. Wire registry transitions + API
3. Frontend badge, filters, hide Approve for author
4. Mock API + build verify
