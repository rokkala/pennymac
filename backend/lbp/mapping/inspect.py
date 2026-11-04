"""Field-level inspection for the Mapping UI.

For one SSE target attribute in a mapping, shows:
  * transformation rules - every step in plain English, plus a step-by-step trace of real
    sample rows (source value -> after each step -> SSE value), with errors where a step fails
  * DQ checks - schema-derived checks (required, type, length, code list) and every
    registered business rule that reads this field, each with pass/fail counts on the sample
  * mapping-level DQ - every runtime rule with its fail count and whether its fields are mapped

Sample values for PII columns/targets are masked before they leave the server.
"""
from __future__ import annotations

from sqlalchemy import select

from ..ingestion.parser import ParseOptions, read_sample
from ..ingestion.pii import TARGET_PII_TYPES, mask_value
from ..rules.jsonlogic import compile_logic, referenced_vars
from ..rules.registry import RuleRegistry
from ..schema.sse_target import BY_NAME
from ..store import db
from .transforms import MULTI_SOURCE_OPS, OPS, TransformError, _empty, compile_mapping


def describe_step(s: dict) -> str:
    op = s.get("op")
    d = {
        "trim": "Trim surrounding whitespace",
        "upper": "Convert to upper case",
        "lower": "Convert to lower case",
        "title": "Convert to title case",
        "digits_only": "Keep digits only",
        "to_decimal": "Cast to decimal (strips $ , %)",
        "to_int": "Cast to integer",
        "to_bool": "Cast to Yes/No flag",
        "to_date": f"Parse date{(' as ' + s['format']) if s.get('format') else ' (auto-detect format)'} → ISO yyyy-mm-dd",
        "normalize_rate": "Normalise rate to percent (0.065 → 6.5)",
        "cents_to_dollars": "Convert cents to dollars (÷100)",
        "scale": f"Multiply by {s.get('factor')}",
        "divide": f"Divide by {s.get('divisor')}",
        "lookup": f"Translate via lookup table '{s.get('table')}'" if s.get("table") else "Translate via inline lookup map",
        "default": f"Default to '{s.get('value')}' when blank",
        "constant": f"Set constant '{s.get('value')}'",
        "substr": f"Take characters {s.get('start', 0)}–{(s.get('start', 0) or 0) + (s.get('length') or 0)}",
        "pad_left": f"Left-pad to {s.get('width')} with '{s.get('char', '0')}'",
        "truncate": f"Truncate to {s.get('length')} characters (SSE column length)",
        "split": f"Split on '{s.get('delimiter', ',')}' and take part {s.get('index', 0)}",
        "parse_address": f"Parse single-line address → {s.get('part', 'line1')}",
        "regex_extract": f"Extract pattern {s.get('pattern')}",
        "concat": f"Join source columns with '{s.get('separator', ' ')}' (N:1)",
        "template": f"Fill template {s.get('template')} (N:1)",
    }.get(op)
    return d or op


def _schema_checks(target: str):
    a = BY_NAME[target]
    checks = []
    if a.required:
        checks.append({"id": "required", "label": "Required: must be populated", "test": lambda v: not _empty(v)})
    checks.append({"id": "type", "label": f"Type: must cast to {a.dtype}", "test": None})  # = transform succeeded
    if a.length and a.dtype in ("string", "code"):
        checks.append({"id": "length", "label": f"Length: at most {a.length} characters", "test": lambda v, n=a.length: _empty(v) or len(str(v)) <= n})
    if a.codes:
        codes = set(a.codes)
        label = f"Code list: one of {', '.join(a.codes)}" if len(codes) <= 8 else f"Code list: one of {len(codes)} SSE codes"
        checks.append({"id": "codes", "label": label, "test": lambda v, cs=codes: _empty(v) or str(v) in cs})
    return checks


def _load(mapping_id: str, n: int):
    with db.get_engine().connect() as c:
        m = c.execute(select(db.mappings).where(db.mappings.c.mapping_id == mapping_id)).first()
        if not m:
            raise ValueError("mapping not found")
        src = c.execute(select(db.sources).where(db.sources.c.source_id == m.source_id)).first()
    from ..storage import local_path

    _, rows = read_sample(local_path(src.sample_file), n, ParseOptions(**(src.parse_options or {})))
    pii_cols = {col["name"]: col["pii_type"] for col in (src.profile or {}).get("columns", []) if col.get("pii_type")}
    return m, rows, pii_cols


def _runtime_rules():
    reg = RuleRegistry()
    rs = reg.runtime_set()
    drafts = [r for r in reg.list() if r["status"] in ("draft", "in_review", "approved")]
    return [*rs["active"], *rs["canary"], *rs["shadow"], *drafts]


def _trace_row(spec: dict, row: dict, pii_src: dict, pii_tgt: str | None):
    sources = spec.get("sources") or ([spec["source"]] if spec.get("source") else [])
    src_vals = [row.get(s) for s in sources]
    value = src_vals[0] if src_vals else None
    mask = lambda v, kind: mask_value(str(v), kind) if kind and v not in (None, "") else v  # noqa: E731
    steps, error = [], None
    for st in spec.get("transform", []):
        fn = OPS.get(st.get("op"))
        try:
            if fn is None:
                raise TransformError(f"unknown op {st.get('op')}")
            value = fn(value, st, src_vals)
            if st.get("op") in MULTI_SOURCE_OPS:
                src_vals = [value]
            steps.append({"op": st.get("op"), "value": mask(value, pii_tgt)})
        except TransformError as e:
            error = {"op": st.get("op"), "message": str(e)}
            value = None
            break
    if _empty(value) and "default" in spec:
        value = spec["default"]
    return {"inputs": {s: mask(row.get(s), pii_src.get(s)) for s in sources}, "steps": steps, "output": mask(value, pii_tgt),
            "raw_output": value, "error": error}


def field_inspect(mapping_id: str, target: str, n: int = 500, sources: list[str] | None = None,
                  transform: list[dict] | None = None, examples: int = 8) -> dict:
    if target not in BY_NAME:
        raise ValueError(f"unknown SSE attribute {target}")
    m, rows, pii_src = _load(mapping_id, n)
    fields = [{**f, "status": "accepted" if f["status"] in ("suggested", "needs_review") else f["status"]} for f in m.fields]
    spec = next((f for f in fields if f["target"] == target), None) or {"target": target, "sources": [], "transform": []}
    spec = dict(spec)
    if sources is not None:
        spec["sources"], spec["source"] = sources, (sources[0] if sources else None)
    if transform is not None:
        spec["transform"] = transform
    spec["status"] = "accepted"
    pii_tgt = TARGET_PII_TYPES.get(target)

    traces = [_trace_row(spec, r, pii_src, pii_tgt) for r in rows]
    # full mapped records (with this field's edited spec) for rule evaluation
    fields = [f for f in fields if f["target"] != target] + [spec]
    mapper = compile_mapping(fields)
    records = [mapper(r) for r in rows]

    checks = []
    for ch in _schema_checks(target):
        if ch["id"] == "type":
            fails = [i for i, t in enumerate(traces) if t["error"]]
        else:
            fails = [i for i, t in enumerate(traces) if not t["error"] and not ch["test"](t["raw_output"])]
        checks.append({"id": ch["id"], "label": ch["label"], "kind": "schema", "evaluated": len(traces), "failed": len(fails),
                       "examples": list({str(traces[i]["output"] if not traces[i]["error"] else traces[i]["error"]["message"]) for i in fails[:20]})[:4]})

    rules = []
    for r in _runtime_rules():
        vars_ = referenced_vars(r["expression"])
        if target not in vars_ and r.get("field") != target:
            continue
        fn = compile_logic(r["expression"])
        fails = []
        for i, (rec, _) in enumerate(records):
            try:
                ok = bool(fn(rec))
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                fails.append(i)
        rules.append({
            "rule_id": r["rule_id"], "version": r["version"], "name": r["name"], "description": r.get("description"),
            "status": r["status"], "severity": r.get("severity"), "category": r.get("category"), "regulatory_tag": r.get("regulatory_tag"),
            "primary_field": r.get("field"), "reads_fields": sorted(vars_), "expression": r["expression"],
            "evaluated": len(records), "failed": len(fails),
            "examples": list({str(traces[i]["output"]) for i in fails[:20]})[:4],
        })
    rules.sort(key=lambda x: (x["primary_field"] != target, x["rule_id"], x["version"]))

    # choose illustrative examples: distinct inputs, failures first
    picked, seen = [], set()
    order = sorted(range(len(traces)), key=lambda i: (traces[i]["error"] is None, str(traces[i]["inputs"])))
    for i in order:
        key = str(traces[i]["inputs"])
        if key in seen:
            continue
        seen.add(key)
        picked.append(i)
        if len(picked) >= examples:
            break
    outs = [t["raw_output"] for t in traces if not t["error"]]
    a = BY_NAME[target]
    return {
        "mapping_id": mapping_id, "target": target,
        "attribute": {"name": a.name, "module": a.module, "dtype": a.dtype, "length": a.length, "required": a.required, "risk": a.risk,
                      "codes": list(a.codes), "pii": a.pii, "description": a.description},
        "sources": spec.get("sources") or [], "transform": spec.get("transform") or [],
        "steps": [{"op": s.get("op"), "params": {k: v for k, v in s.items() if k != "op"}, "description": describe_step(s)} for s in spec.get("transform") or []],
        "examples": [{k: v for k, v in traces[i].items() if k != "raw_output"} for i in picked],
        "stats": {"rows": len(traces), "transform_errors": sum(1 for t in traces if t["error"]),
                  "blank_outputs": sum(1 for v in outs if _empty(v)), "distinct_outputs": len({str(v) for v in outs})},
        "schema_checks": checks, "dq_rules": rules,
    }


def mapping_dq(mapping_id: str, n: int = 500) -> dict:
    """Every rule in the registry against this mapping's sample: fail counts and field coverage."""
    m, rows, _ = _load(mapping_id, n)
    fields = [{**f, "status": "accepted" if f["status"] in ("suggested", "needs_review") else f["status"]} for f in m.fields]
    mapped = {f["target"] for f in fields if f["status"] != "rejected"}
    mapper = compile_mapping(fields)
    records = [mapper(r)[0] for r in rows]
    out = []
    for r in _runtime_rules():
        vars_ = referenced_vars(r["expression"])
        fn = compile_logic(r["expression"])
        failed = 0
        for rec in records:
            try:
                failed += 0 if fn(rec) else 1
            except Exception:  # noqa: BLE001
                failed += 1
        unmapped = sorted(v for v in vars_ if v not in mapped)
        out.append({"rule_id": r["rule_id"], "version": r["version"], "name": r["name"], "status": r["status"], "severity": r.get("severity"),
                    "category": r.get("category"), "regulatory_tag": r.get("regulatory_tag"), "primary_field": r.get("field"),
                    "reads_fields": sorted(vars_), "unmapped_fields": unmapped, "evaluated": len(records), "failed": failed,
                    "fail_rate_pct": round(failed / len(records) * 100, 2) if records else 0})
    out.sort(key=lambda x: (-x["failed"], x["rule_id"]))
    return {"mapping_id": mapping_id, "rows": len(records), "rules": out}


def value_coverage(mapping_id: str, target: str, sources: list[str] | None = None, transform: list[dict] | None = None,
                   n: int = 2000, top: int = 60) -> dict:
    """Every distinct source value for a field, what it becomes in SSE and whether that is valid.

    Drives the value-translation editor: untranslated codes ('Owner', 'Cash-Out Refi', 'C A') are
    listed with their row counts so an analyst can map them once instead of fixing loans one by one.
    """
    from collections import Counter

    if target not in BY_NAME:
        raise ValueError(f"unknown SSE attribute {target}")
    m, rows, pii_src = _load(mapping_id, n)
    spec = next((f for f in m.fields if f["target"] == target), None) or {"target": target, "sources": [], "transform": []}
    spec = dict(spec)
    if sources is not None:
        spec["sources"], spec["source"] = sources, (sources[0] if sources else None)
    if transform is not None:
        spec["transform"] = transform
    srcs = spec.get("sources") or ([spec["source"]] if spec.get("source") else [])
    a = BY_NAME[target]
    pii = TARGET_PII_TYPES.get(target) or any(pii_src.get(s) for s in srcs)
    counts = Counter(tuple(r.get(s, "") for s in srcs) for r in rows)
    checks = {c["id"]: c for c in _schema_checks(target)}
    values = []
    for key, cnt in counts.most_common():
        row = dict(zip(srcs, key, strict=True))
        t = _trace_row(spec, row, {}, None)
        out, err = t["raw_output"], t["error"]
        problems = []
        if err:
            problems.append(err["message"])
        else:
            for cid in ("required", "codes", "length"):
                ch = checks.get(cid)
                if ch and not ch["test"](out):
                    problems.append(ch["label"])
        values.append({"source": " + ".join(str(k) for k in key), "count": cnt, "output": out, "valid": not problems, "problems": problems})
    invalid = [v for v in values if not v["valid"]]
    shown = (invalid + [v for v in values if v["valid"]])[:top]
    if pii:  # never list raw NPI values
        shown = [{**v, "source": "(masked)", "output": "(masked)" if v["output"] not in (None, "") else v["output"]} for v in shown]
    lookup = next((s for s in spec.get("transform") or [] if s.get("op") == "lookup"), None)
    return {
        "target": target, "sources": srcs, "codes": list(a.codes), "dtype": a.dtype, "rows": len(rows), "distinct": len(values),
        "invalid_distinct": len(invalid), "invalid_rows": sum(v["count"] for v in invalid),
        "coverage_pct": round((1 - sum(v["count"] for v in invalid) / max(len(rows), 1)) * 100, 1),
        "values": shown, "value_map": (lookup or {}).get("map") or {}, "lookup_table": (lookup or {}).get("table"),
        "editable": not pii and len(values) <= 200,
    }


def with_value_map(transform: list[dict], value_map: dict[str, str], table: str | None = None) -> list[dict]:
    """Insert or update the lookup step carrying a source-specific value map (before the final cast)."""
    steps = [dict(s) for s in transform or []]
    vm = {str(k).strip().lower(): v for k, v in value_map.items() if v not in (None, "")}
    for st in steps:
        if st.get("op") == "lookup":
            st["map"] = vm
            return steps
    step = {"op": "lookup", "map": vm, **({"table": table} if table else {})}
    casts = {"upper", "to_decimal", "to_int", "to_date", "to_bool", "truncate"}
    i = len(steps)
    while i > 0 and steps[i - 1].get("op") in casts:
        i -= 1
    steps.insert(i, step)
    return steps
