# Rule review workflow + in-app notifications

**Date:** 2026-11-05  
**Status:** Approved (peer pool)  
**Scope:** v1 in-app only (SNS/email later)

## Roles

| Role | Who (demo) | Can |
|------|------------|-----|
| Author / editor | Dan · SME (or Ana if she authored) | Draft, edit draft, submit for review, send-back receive |
| Peer reviewer | Another SME | Approve / send back (not the author) |
| Compliance | Ana · Compliance | Required when `regulatory_tag` is set; may also peer-approve |

Maker-checker: `actor != author` on Approve (server). UI hides Approve for the author.

## Peer pool (v1)

No named assignee. On Submit for review, notify every eligible peer except the author:

- Users with role `sme` or `compliance`
- If regulatory: Compliance recipients are required for final approval (existing gate)

## Notifications

Table `notifications`: id, user_id, kind, title, body, entity_type, entity_id, read_at, created_at.

Kinds: `rule.in_review`, `rule.approved`, `rule.sent_back`, `rule.peer_approved` (regulatory pending Compliance).

APIs: `GET /api/notifications`, `POST /api/notifications/{id}/read`, `POST /api/notifications/read-all`.

## UI

- Rail badge unread count; click → Rules with filter **Needs my review**
- Rules list filter: All | Needs my review | My drafts
- Rule detail: author sees “Waiting for another SME/Compliance”; peer sees Approve primary

## Out of scope

Email/SNS fan-out, named assignee picker, Slack.
