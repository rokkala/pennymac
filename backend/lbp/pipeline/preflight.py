"""Schema-drift pre-flight: compare an incoming file with the source's approved mapping before
any row is processed.

Sellers change tapes without notice: a renamed header, a new date format, an extra column, a
field that is suddenly blank. Without a guard the pipeline "succeeds" and fills SSE with
nulls or thousands of exceptions. This check runs on the header plus a sample and returns:

  missing_columns   mapped source columns absent from the file, with the SSE fields they feed
                    and a best-guess rename among the new columns
  new_columns       columns not seen when the source was profiled (possible new data)
  type_drift        a mapped column whose inferred type or date format changed
  null_spikes       a mapped column whose blank rate rose by 20+ points
  decision          pass | warn | block

Block when a missing or type-drifted column feeds a required or high/critical-risk SSE field,
because loading would corrupt regulated data. Everything else warns and proceeds.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

from ..ingestion.parser import ParseOptions, read_sample
from ..ingestion.profiler import profile_rows
from ..mapping.engine import normalize
from ..schema.sse_target import BY_NAME

NULL_SPIKE_POINTS = 20.0


def _active_fields(fields: list[dict]) -> list[dict]:
    return [f for f in fields if f.get("status") not in ("rejected",)]


def _feeds(fields: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in _active_fields(fields):
        for s in f.get("sources") or ([f["source"]] if f.get("source") else []):
            out.setdefault(s, []).append(f["target"])
    return out


def _critical(targets: list[str]) -> bool:
    return any(BY_NAME[t].required or BY_NAME[t].risk in ("high", "critical") for t in targets if t in BY_NAME)


def _rename_guess(missing: str, candidates: list[str], old_prof: dict | None, new_prof: dict) -> dict | None:
    best, best_s = None, 0.0
    nm = normalize(missing)
    for c in candidates:
        s = SequenceMatcher(None, nm, normalize(c)).ratio()
        tok = set(nm.split()) & set(normalize(c).split())
        s = max(s, len(tok) / max(len(set(nm.split())), 1))
        np_ = new_prof.get(c)
        if old_prof and np_ and old_prof.get("inferred_type") == np_.get("inferred_type"):
            s += 0.15
        if s > best_s:
            best, best_s = c, s
    return {"column": best, "score": round(min(best_s, 1.0), 2)} if best and best_s >= 0.55 else None


def check_file(file_path: Path, parse_options: dict | None, source_profile: dict | None, fields: list[dict], n: int = 500,
               sparse: bool = False, delivery: dict | None = None) -> dict:
    """sparse=True for incremental change files: vendors may send only the loan number plus changed
    columns, so a missing non-key column is informational and blank rates are expected to be high.
    The loan-number column (and the action column, when actions come from a column) still block."""
    meta, rows = read_sample(Path(file_path), n, ParseOptions(**(parse_options or {})))
    new_profile = profile_rows(meta.columns, rows) if rows else {"columns": []}
    new_cols = {c["name"]: c for c in new_profile["columns"]}
    old_cols = {c["name"]: c for c in (source_profile or {}).get("columns", [])}
    feeds = _feeds(fields)
    actual = set(meta.columns)

    unknown_new = [c for c in meta.columns if c not in old_cols]
    missing = []
    for col, targets in feeds.items():
        if col in actual:
            continue
        guess = _rename_guess(col, unknown_new, old_cols.get(col), new_cols)
        blocking = ("loan_number" in targets) if sparse else _critical(targets)
        missing.append({"column": col, "feeds": targets, "blocking": blocking, "rename_to": guess, **({"sparse_ok": True} if sparse and not blocking else {})})
    if sparse:
        from .delivery import profile_of

        act = profile_of(delivery)["action"]
        if act.get("mode") == "column" and act.get("column") and act["column"] not in actual:
            missing.append({"column": act["column"], "feeds": ["(action code)"], "blocking": True, "rename_to":
                            _rename_guess(act["column"], unknown_new, None, new_cols)})

    # Effective drift: run the approved transforms on the new sample. A format change that the
    # mapping still parses is harmless; one that makes casts fail is not.
    from ..mapping.transforms import compile_mapping

    act = [{**f, "status": "accepted"} for f in _active_fields(fields)
           if all(s in actual for s in (f.get("sources") or ([f["source"]] if f.get("source") else [])))]
    mapper = compile_mapping(act)
    err_by_target: dict[str, int] = {}
    for r in rows:
        _, errs = mapper(r)
        for t in errs:
            err_by_target[t] = err_by_target.get(t, 0) + 1
    type_drift, null_spikes = [], []
    for col, targets in feeds.items():
        if col not in actual or col not in old_cols:
            continue
        o, nw = old_cols[col], new_cols.get(col, {})
        broken = [t for t in targets if err_by_target.get(t, 0) / max(len(rows), 1) > 0.05]
        fam = {"string": "text", "code": "text", "int": "number", "decimal": "number"}
        changed = (fam.get(o.get("inferred_type"), o.get("inferred_type")) != fam.get(nw.get("inferred_type"), nw.get("inferred_type"))
                   or (o.get("date_format") or None) != (nw.get("date_format") or None))
        if broken or (changed and not sparse):  # sparse columns are mostly blank: only real cast failures count
            type_drift.append({"column": col, "feeds": targets, "breaks": broken,
                               "was": {"type": o.get("inferred_type"), "date_format": o.get("date_format")},
                               "now": {"type": nw.get("inferred_type"), "date_format": nw.get("date_format")},
                               "error_rate_pct": round(max((err_by_target.get(t, 0) for t in targets), default=0) / max(len(rows), 1) * 100, 1),
                               "blocking": bool(broken) and _critical(broken), "suggested_date_format": nw.get("date_format"),
                               "samples": nw.get("samples", [])[:3] if not nw.get("pii_type") else []})
        if not sparse and (nw.get("null_pct", 0) - o.get("null_pct", 0)) >= NULL_SPIKE_POINTS:
            null_spikes.append({"column": col, "feeds": targets, "was_pct": o.get("null_pct"), "now_pct": nw.get("null_pct"),
                                "blocking": False})
    renamed_targets = {m["rename_to"]["column"] for m in missing if m["rename_to"]}
    new_columns = [{"column": c, "type": new_cols.get(c, {}).get("inferred_type"), "possible_rename_of": next((m["column"] for m in missing if m["rename_to"] and m["rename_to"]["column"] == c), None)}
                   for c in unknown_new]
    blocking = [x for x in missing + type_drift if x["blocking"]]
    if sparse:
        unknown_new = [c for c in unknown_new if c != profile_of(delivery)["action"].get("column")]
        new_columns = [nc for nc in new_columns if nc["column"] in unknown_new]
    issues = len([m for m in missing if not m.get("sparse_ok")]) + len(type_drift) + len(null_spikes) + len([c for c in unknown_new if c not in renamed_targets])
    decision = "block" if blocking else ("warn" if issues else "pass")
    return {
        "decision": decision, "rows_sampled": len(rows), "columns_in_file": len(meta.columns), "columns_expected": len(feeds),
        "missing_columns": missing, "new_columns": new_columns, "type_drift": type_drift, "null_spikes": null_spikes,
        "summary": _summary(decision, missing, type_drift, null_spikes, new_columns),
    }


def _summary(decision, missing, type_drift, null_spikes, new_columns) -> str:
    parts = []
    sparse_n = len([m for m in missing if m.get("sparse_ok")])
    missing = [m for m in missing if not m.get("sparse_ok")]
    if missing:
        parts.append(f"{len(missing)} mapped column(s) missing")
    if type_drift:
        parts.append(f"{len(type_drift)} column(s) changed type or date format")
    if null_spikes:
        parts.append(f"{len(null_spikes)} column(s) suddenly blank")
    if new_columns:
        parts.append(f"{len(new_columns)} new column(s)")
    if not parts:
        return "File matches the approved mapping." + (f" Sparse change file: {sparse_n} mapped column(s) not sent." if sparse_n else "")
    lead = {"block": "Blocked: ", "warn": "Proceeding with warnings: ", "pass": ""}[decision]
    return lead + "; ".join(parts) + "."


def remap_fields(fields: list[dict], renames: dict[str, str], date_formats: dict[str, str] | None = None) -> list[dict]:
    """Apply column renames (old -> new) and date-format fixes to a copy of mapping fields."""
    out = []
    for f in fields:
        f = {**f, "transform": [dict(s) for s in f.get("transform") or []]}
        srcs = f.get("sources") or ([f["source"]] if f.get("source") else [])
        if any(s in renames for s in srcs):
            f["sources"] = [renames.get(s, s) for s in srcs]
            f["source"] = f["sources"][0]
            f["status"] = "overridden"
            f["rationale"] = f"Column renamed in source file: {', '.join(f'{k} → {v}' for k, v in renames.items() if k in srcs)}"
        for s in f["sources"] if f.get("sources") else []:
            if date_formats and s in date_formats:
                for st in f["transform"]:
                    if st.get("op") == "to_date":
                        st["format"] = date_formats[s]
                f["status"] = "overridden"
        out.append(f)
    return out
