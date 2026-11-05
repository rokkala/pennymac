r"""Versioned, signed Rule Registry with HITL lifecycle gates.

    draft -> in_review -> approved -> shadow | canary | active -> retired
                       \-> rejected

Gates enforced here (not in the UI):
  * a rule cannot leave draft unless its expression validates and every embedded test passes
  * approval requires a reviewer distinct from the author; rules with a regulatory_tag also
    require an approver holding the 'compliance' role
  * activating a version retires the previously active version (one active per rule_id)
  * every transition is written to the audit log (CloudTrail + EventBridge in AWS)

Backends: SqlRuleStore (default) and DynamoRuleStore (AWS, table pk=rule_id, sk=version).
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Protocol

from sqlalchemy import and_, delete, select

from ..store import db
from .jsonlogic import compile_logic, validate

LIFECYCLE = {
    "draft": {"in_review"},
    "in_review": {"approved", "rejected", "draft"},
    "approved": {"shadow", "canary", "active"},
    "shadow": {"canary", "active", "retired"},
    "canary": {"active", "retired", "shadow"},
    "active": {"retired"},
    "rejected": {"draft"},
    "retired": set(),
}


class RuleError(ValueError):
    pass


def signature(body: dict) -> str:
    canon = json.dumps({"rule_id": body["rule_id"], "version": body["version"], "expression": body["expression"],
                        "severity": body.get("severity"), "field": body.get("field")}, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()


def run_tests(body: dict) -> list[dict]:
    fn = compile_logic(body["expression"])
    out = []
    for i, tc in enumerate(body.get("tests") or []):
        try:
            got = bool(fn(tc["record"]))
            out.append({"case": i, "expect": tc["expect"], "got": got, "passed": got == bool(tc["expect"])})
        except Exception as e:  # noqa: BLE001
            out.append({"case": i, "expect": tc["expect"], "got": None, "passed": False, "error": str(e)})
    return out


class RuleStore(Protocol):
    def put(self, body: dict, status: str) -> None: ...
    def get(self, rule_id: str, version: int | None = None) -> dict | None: ...
    def list(self, status: str | None = None) -> list[dict]: ...
    def versions(self, rule_id: str) -> list[dict]: ...
    def delete_all(self, rule_id: str) -> int: ...


class SqlRuleStore:
    def put(self, body, status):
        body = {**body, "status": status}
        with db.get_engine().begin() as c:
            exists = c.execute(select(db.rules.c.rule_id).where(and_(db.rules.c.rule_id == body["rule_id"],
                                                                        db.rules.c.version == body["version"]))).first()
            if exists:
                c.execute(db.rules.update().where(and_(db.rules.c.rule_id == body["rule_id"], db.rules.c.version == body["version"]))
                          .values(status=status, body=body, updated_at=db.now()))
            else:
                c.execute(db.rules.insert().values(rule_id=body["rule_id"], version=body["version"], status=status, body=body))

    def get(self, rule_id, version=None):
        q = select(db.rules.c.body).where(db.rules.c.rule_id == rule_id)
        q = q.where(db.rules.c.version == version) if version else q.order_by(db.rules.c.version.desc())
        with db.get_engine().connect() as c:
            r = c.execute(q).first()
        return copy.deepcopy(r[0]) if r else None

    def list(self, status=None):
        q = select(db.rules.c.body)
        if status:
            q = q.where(db.rules.c.status == status)
        with db.get_engine().connect() as c:
            return [r[0] for r in c.execute(q.order_by(db.rules.c.rule_id, db.rules.c.version))]

    def versions(self, rule_id):
        with db.get_engine().connect() as c:
            return [r[0] for r in c.execute(select(db.rules.c.body).where(db.rules.c.rule_id == rule_id).order_by(db.rules.c.version))]

    def delete_all(self, rule_id):
        with db.get_engine().begin() as c:
            res = c.execute(delete(db.rules).where(db.rules.c.rule_id == rule_id))
            return res.rowcount or 0


class DynamoRuleStore:
    """AWS backend. Table: pk rule_id (S), sk version (N), GSI 'status-index' on status."""

    def __init__(self, table_name: str):
        import boto3

        self.table = boto3.resource("dynamodb").Table(table_name)

    def put(self, body, status):
        self.table.put_item(Item=json.loads(json.dumps({**body, "status": status}), parse_float=str))

    def get(self, rule_id, version=None):
        from boto3.dynamodb.conditions import Key

        if version:
            item = self.table.get_item(Key={"rule_id": rule_id, "version": version}).get("Item")
        else:
            items = self.table.query(KeyConditionExpression=Key("rule_id").eq(rule_id), ScanIndexForward=False, Limit=1)["Items"]
            item = items[0] if items else None
        return _undecimal(item) if item else None

    def list(self, status=None):
        from boto3.dynamodb.conditions import Key

        if status:
            items = self.table.query(IndexName="status-index", KeyConditionExpression=Key("status").eq(status))["Items"]
        else:
            items = self.table.scan()["Items"]
        return [_undecimal(i) for i in items]

    def versions(self, rule_id):
        from boto3.dynamodb.conditions import Key

        return [_undecimal(i) for i in self.table.query(KeyConditionExpression=Key("rule_id").eq(rule_id))["Items"]]

    def delete_all(self, rule_id):
        from boto3.dynamodb.conditions import Key

        items = self.table.query(KeyConditionExpression=Key("rule_id").eq(rule_id))["Items"]
        n = 0
        with self.table.batch_writer() as batch:
            for it in items:
                batch.delete_item(Key={"rule_id": it["rule_id"], "version": it["version"]})
                n += 1
        return n


def _undecimal(o):
    from decimal import Decimal

    if isinstance(o, list):
        return [_undecimal(x) for x in o]
    if isinstance(o, dict):
        return {k: _undecimal(v) for k, v in o.items()}
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    return o


class RuleRegistry:
    def __init__(self, store: RuleStore | None = None):
        if store is None:
            from ..config import get_settings

            s = get_settings()
            store = DynamoRuleStore(s.rules_table) if s.env == "aws" and s.rules_table else SqlRuleStore()
        self.store = store

    # ------------------------------------------------------------- authoring
    def create_draft(self, body: dict, actor: str) -> dict:
        problems = validate(body.get("expression"))
        if problems:
            raise RuleError("; ".join(problems))
        existing = self.store.versions(body["rule_id"]) if body.get("rule_id") else []
        if not body.get("rule_id"):
            nums = [int(r["rule_id"][1:]) for r in self.store.list() if r["rule_id"][1:].isdigit()]
            body["rule_id"] = f"R{(max(nums) + 1) if nums else 1:03d}"
        body = {
            "severity": "FAIL", "category": "custom", "fields": [body.get("field")] if body.get("field") else [],
            "owner": actor, "effective_from": db.now().date().isoformat(), "regulatory_tag": None, "tests": [],
            "canary_pct": 0, **body,
            "version": (max(r["version"] for r in existing) + 1) if existing else 1,
            "author": actor, "approvals": [], "history": [{"ts": db.now().isoformat(), "actor": actor, "to": "draft"}],
        }
        body["signature"] = signature(body)
        self.store.put(body, "draft")
        self._audit(actor, "rule.draft", body)
        return body

    def update_draft(self, rule_id: str, version: int, changes: dict, actor: str) -> dict:
        body = self._require(rule_id, version)
        if body["status"] != "draft":
            raise RuleError("only drafts can be edited; create a new version instead")
        body.update({k: v for k, v in changes.items() if k not in ("rule_id", "version", "status", "approvals", "history")})
        if validate(body["expression"]):
            raise RuleError("; ".join(validate(body["expression"])))
        body["signature"] = signature(body)
        self.store.put(body, "draft")
        self._audit(actor, "rule.edit", body)
        return body

    # ------------------------------------------------------------- lifecycle
    def transition(self, rule_id: str, version: int, to: str, actor: str, roles: list[str] | None = None,
                   comment: str | None = None, canary_pct: int | None = None) -> dict:
        roles = roles or []
        body = self._require(rule_id, version)
        cur = body["status"]
        if to not in LIFECYCLE.get(cur, set()):
            raise RuleError(f"cannot move {rule_id} v{version} from {cur} to {to}")
        if to == "in_review":
            results = run_tests(body)
            if not results:
                raise RuleError("rule has no test cases; add at least one passing and one failing case")
            failed = [r for r in results if not r["passed"]]
            if failed:
                raise RuleError(f"{len(failed)} test case(s) failing: {failed}")
            body["test_results"] = results
        if to == "approved":
            author = body.get("author") or body.get("owner")
            if not author:
                raise RuleError("maker-checker: rule has no author recorded; cannot approve")
            if actor == author:
                raise RuleError("maker-checker: the author cannot approve their own rule")
            submitted_by = next(
                (h.get("actor") for h in reversed(body.get("history") or []) if h.get("to") == "in_review"),
                None,
            )
            if submitted_by and actor == submitted_by:
                raise RuleError("maker-checker: the submitter cannot approve their own submission")
            body["approvals"] = [*body.get("approvals", []), {"actor": actor, "roles": roles, "ts": db.now().isoformat(), "comment": comment}]
            approver_roles = {r for a in body["approvals"] for r in a.get("roles", [])}
            if body.get("regulatory_tag") and "compliance" not in approver_roles:
                self.store.put(body, cur)
                self._audit(actor, "rule.peer_approved", body)
                out = {**body, "status": cur, "pending": "compliance approval required"}
                try:
                    from ..notifications import on_rule_transition

                    on_rule_transition(body, to, actor, pending=out["pending"])
                except Exception:  # noqa: BLE001 - notifications must not block governance
                    pass
                return out
        if to == "canary":
            body["canary_pct"] = int(canary_pct if canary_pct is not None else body.get("canary_pct") or 1)
        if to == "active":
            for other in self.store.versions(rule_id):
                if other["version"] != version and other["status"] in ("active", "canary", "shadow"):
                    other.setdefault("history", []).append({"ts": db.now().isoformat(), "actor": actor, "to": "retired", "reason": f"superseded by v{version}"})
                    self.store.put(other, "retired")
        body.setdefault("history", []).append({"ts": db.now().isoformat(), "actor": actor, "from": cur, "to": to, "comment": comment})
        body["status"] = to
        self.store.put(body, to)
        self._audit(actor, f"rule.{to}", body)
        if to in ("active", "canary", "shadow", "retired") or cur in ("active", "canary", "shadow"):
            from ..config_store import publish_all

            publish_all(actor, f"rule {rule_id} v{version} {to}")  # every feed's bundle carries the runtime rule set
        try:
            from ..notifications import on_rule_transition

            on_rule_transition(body, to, actor)
        except Exception:  # noqa: BLE001
            pass
        return body

    # ------------------------------------------------------------- queries
    def runtime_set(self) -> dict[str, list[dict]]:
        """Rules the executor needs: active, plus canary and shadow candidates."""
        allr = self.store.list()
        return {s: [r for r in allr if r["status"] == s] for s in ("active", "canary", "shadow")}

    def list(self, status: str | None = None) -> list[dict]:
        return self.store.list(status)

    def get(self, rule_id: str, version: int | None = None) -> dict | None:
        return self.store.get(rule_id, version)

    def versions(self, rule_id: str) -> list[dict]:
        return self.store.versions(rule_id)

    def delete_rule(self, rule_id: str, actor: str, reason: str | None = None) -> dict:
        """Hard-delete every version of a rule. Republishes live feeds if any version was running."""
        vs = self.store.versions(rule_id)
        if not vs:
            raise RuleError(f"rule {rule_id} not found")
        was_live = any(v.get("status") in ("active", "canary", "shadow") for v in vs)
        n = self.store.delete_all(rule_id)
        with db.get_engine().begin() as c:
            db.audit(c, actor, "rule.delete", "rule", rule_id, {
                "versions_removed": n,
                "reason": reason,
                "statuses": [v.get("status") for v in vs],
            })
        if was_live:
            from ..config_store import publish_all

            publish_all(actor, f"rule {rule_id} deleted")
        return {"ok": True, "rule_id": rule_id, "versions_removed": n, "republished": was_live}

    def seed_defaults(self, actor: str = "system") -> int:
        from .default_rules import DEFAULT_RULES

        if self.store.list():
            return 0
        for r in DEFAULT_RULES:
            body = {**r, "version": 1, "author": "migration:hangfire-sp", "approvals": [{"actor": "seed", "roles": ["compliance"]}],
                    "history": [{"ts": db.now().isoformat(), "actor": actor, "to": "active", "comment": "migrated from stored procedure"}],
                    "canary_pct": 0}
            body["signature"] = signature(body)
            self.store.put(body, "active")
        return len(DEFAULT_RULES)

    def _require(self, rule_id, version):
        body = self.store.get(rule_id, version)
        if not body:
            raise RuleError(f"rule {rule_id} v{version} not found")
        return body

    def _audit(self, actor, action, body):
        with db.get_engine().begin() as c:
            db.audit(c, actor, action, "rule", f"{body['rule_id']}:v{body['version']}", {"signature": body.get("signature")})
