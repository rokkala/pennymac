"""Stateless rule executor (runs in-process, in worker processes, on Lambda or ECS Fargate).

Build once per micro-batch from a runtime rule set snapshot, then evaluate records.
Canary versions take over for a deterministic slice of loans (hash of loan_number), shadow
versions are evaluated alongside the active rule and only their disagreements are reported.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field

from .jsonlogic import compile_logic


@dataclass
class RuleResult:
    rule_id: str
    version: int
    name: str
    field: str
    category: str
    severity: str
    passed: bool
    message: str
    regulatory_tag: str | None = None
    error: str | None = None


@dataclass
class Evaluation:
    status: str  # PASS | WARN | FAIL
    failures: list[RuleResult] = field(default_factory=list)
    shadow_diffs: list[dict] = field(default_factory=list)
    canary_rules: list[str] = field(default_factory=list)


def _bucket(key: str) -> int:
    return zlib.crc32(key.encode()) % 100


class RuleExecutor:
    def __init__(self, runtime_set: dict[str, list[dict]]):
        def comp(rules):
            return [(r, compile_logic(r["expression"])) for r in rules]

        self.active = comp(runtime_set.get("active", []))
        self.canary = {r["rule_id"]: (r, f) for r, f in comp(runtime_set.get("canary", []))}
        self.shadow = {r["rule_id"]: (r, f) for r, f in comp(runtime_set.get("shadow", []))}
        active_ids = {r["rule_id"] for r, _ in self.active}
        # canary rules with no active counterpart (brand-new rules) still run for their slice
        self.new_canaries = [v for k, v in self.canary.items() if k not in active_ids]

    @property
    def rule_count(self) -> int:
        return len(self.active)

    def _eval(self, rule, fn, rec) -> RuleResult:
        try:
            ok = bool(fn(rec))
            err = None
        except Exception as e:  # noqa: BLE001 - a broken rule must never crash a batch
            ok, err = False, f"rule error: {e}"
        return RuleResult(rule["rule_id"], rule["version"], rule["name"], rule.get("field") or "", rule.get("category", ""),
                          rule.get("severity", "FAIL"), ok, rule.get("message") or rule["name"], rule.get("regulatory_tag"), err)

    def evaluate(self, rec: dict) -> Evaluation:
        loan_key = str(rec.get("loan_number") or "")
        bucket = _bucket(loan_key)
        failures, shadow_diffs, canaries = [], [], []
        for rule, fn in self.active:
            rid = rule["rule_id"]
            use_rule, use_fn = rule, fn
            c = self.canary.get(rid)
            if c and bucket < int(c[0].get("canary_pct") or 0):
                use_rule, use_fn = c
                canaries.append(rid)
            res = self._eval(use_rule, use_fn, rec)
            if rid in self.shadow:
                s_rule, s_fn = self.shadow[rid]
                s_res = self._eval(s_rule, s_fn, rec)
                if s_res.passed != res.passed:
                    shadow_diffs.append({"rule_id": rid, "active_version": use_rule["version"], "shadow_version": s_rule["version"],
                                         "active_passed": res.passed, "shadow_passed": s_res.passed})
            if not res.passed:
                failures.append(res)
        for rule, fn in self.new_canaries:
            if bucket < int(rule.get("canary_pct") or 0):
                canaries.append(rule["rule_id"])
                res = self._eval(rule, fn, rec)
                if not res.passed:
                    failures.append(res)
        for rid, (rule, fn) in self.shadow.items():
            if rid not in {r["rule_id"] for r, _ in self.active}:
                s_res = self._eval(rule, fn, rec)
                if not s_res.passed:
                    shadow_diffs.append({"rule_id": rid, "shadow_version": rule["version"], "active_passed": None, "shadow_passed": False})
        if any(f.severity == "FAIL" for f in failures):
            status = "FAIL"
        elif failures:
            status = "WARN"
        else:
            status = "PASS"
        return Evaluation(status, failures, shadow_diffs, canaries)
