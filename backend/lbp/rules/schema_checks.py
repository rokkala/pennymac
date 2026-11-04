"""SSE column constraints enforced in the pipeline, before anything reaches the database.

A loan that violates the SSE physical schema (too long for its column, a code outside the SSE
code list, a number the column cannot hold) must become an exception, not a crashed batch or a
silently truncated value. Code lists already covered by a business rule (e.g. R005 state) are
left to that rule so reviewers see one exception, not two.
"""
from __future__ import annotations

from ..schema.sse_target import ATTRIBUTES

MAX_ABS = 10 ** 13  # Numeric(20, 6) headroom
_CHECKS = [(a.name, a.dtype, a.length, frozenset(a.codes)) for a in ATTRIBUTES]


def covered_by_rules(runtime_set: dict) -> set[str]:
    return {r.get("field") for rs in runtime_set.values() for r in rs if r.get("field")}


def schema_violations(rec: dict, covered: set[str]) -> list[dict]:
    out = []
    for name, dtype, length, codes in _CHECKS:
        v = rec.get(name)
        if v is None or v == "":
            continue
        if dtype in ("string", "code") and length and len(str(v)) > length:
            out.append({"field": name, "message": f"{len(str(v))} characters; SSE column {name} holds {length}"})
        elif codes and name not in covered and str(v) not in codes:
            out.append({"field": name, "message": f"'{v}' is not an SSE code for {name} ({', '.join(sorted(codes)[:8])}{'…' if len(codes) > 8 else ''})"})
        elif dtype in ("decimal", "int") and isinstance(v, (int, float)) and abs(v) >= MAX_ABS:
            out.append({"field": name, "message": f"value {v} exceeds the SSE numeric range"})
    return out
