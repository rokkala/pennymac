"""Feed layout and readiness: the shape of a multi-file feed and its validation.

A layout declares a master file plus detail files and how each detail joins the master:

    files        one master (`role: master`) and any number of detail roles; each has `name_pattern`
                 (regex on the filename), `required`, `parse_options`; the master also has `entity`, `key`
    relations    detail -> parent role, `on` key parts, `normalize`, `cardinality`, `mode`, `join`,
                 orphan / missing / duplicate-master policies, `min_match_rate`, mode options
    readiness    when a set of files is complete (see DEFAULT_READINESS)

Pure functions over plain dicts: no database, no file access.
"""
from __future__ import annotations

import copy
import re

SUPPORTED_MODES = frozenset({"merge", "aggregate"})
KNOWN_MODES = frozenset({"merge", "flatten", "aggregate", "child"})
NORMALIZERS = ("trim", "strip_leading_zeros", "upper")
AGG_OPS = ("sum", "count", "min", "max", "first", "last", "any", "concat_distinct")

DEFAULT_RELATION = {
    "join": "left",
    "cardinality": "many",
    "on_orphan_detail": "exception",
    "on_missing_detail": "allow",
    "on_duplicate_master": "reject_all",
    "min_match_rate": 0.0,
    "normalize": ["trim"],
}
DEFAULT_READINESS = {
    "require": "all_required",
    "pairing": "business_date",
    "wait_timeout_minutes": 240,
    "on_timeout": "alert_only",
}

PAIRINGS = ("sequence", "business_date", "filename_token", "window_minutes")
NAMED_GROUP_PAIRINGS = ("sequence", "business_date", "filename_token")


class LayoutError(ValueError):
    pass


def normalize_layout(layout: dict) -> dict:
    """Layout with relation defaults filled in. The input is never mutated."""
    out = copy.deepcopy(layout) if isinstance(layout, dict) else {}
    out["files"] = out.get("files") or []
    rels = out.get("relations") or []
    out["relations"] = [
        {**copy.deepcopy(DEFAULT_RELATION), **{k: v for k, v in r.items() if v is not None}}
        for r in rels if isinstance(r, dict)
    ]
    return out


def validate_layout(layout: dict, readiness: dict | None, columns: dict[str, list[str]] | None = None) -> list[str]:
    """Error strings for a layout and its readiness policy (empty = valid).

    `columns` maps role -> known column names, when available (sample or hand-entered)."""
    errs: list[str] = []
    raw = layout if isinstance(layout, dict) else {}
    if not isinstance(layout, dict):
        errs.append("layout must be an object")
    for key in ("files", "relations"):
        if raw.get(key) is not None and not isinstance(raw[key], list):
            errs.append(f"layout.{key} must be a list")
            raw = {**raw, key: []}
    raw = {**raw, "files": [f for f in (raw.get("files") or []) if isinstance(f, dict)]}
    n_bad = len(layout.get("files") or []) - len(raw["files"]) if isinstance(layout, dict) and isinstance(layout.get("files"), list) else 0
    if n_bad:
        errs.append("every entry in files must be an object")
    if any(not isinstance(r, dict) for r in (raw.get("relations") or [])):
        errs.append("every entry in relations must be an object")
    lay = normalize_layout(raw)
    ready = {**DEFAULT_READINESS, **{k: v for k, v in (readiness if isinstance(readiness, dict) else {}).items() if v is not None}}
    files = lay["files"]
    roles = [f.get("role") for f in files]

    masters = [f for f in files if f.get("role") == "master"]
    if len(masters) != 1:
        errs.append(f"layout needs exactly one master file (role: master), found {len(masters)}")
    for role in sorted({r for r in roles if roles.count(r) > 1}):
        errs.append(f"role {role!r} is declared more than once")
    by_role = {f.get("role"): f for f in files}

    for f in files:
        role = f.get("role")
        if not role:
            errs.append("every file needs a role")
        try:
            re.compile(f.get("name_pattern") or "")
        except re.error as e:
            errs.append(f"name_pattern for {role} is not a valid regex: {e}")
        if not f.get("name_pattern"):
            errs.append(f"name_pattern is required for {role}")
    if masters:
        mk = masters[0].get("key")
        if not isinstance(mk, list) or not mk or not all(isinstance(k, str) and k for k in mk):
            errs.append("master key must be a non-empty list of column names")

    details_seen: set[str] = set()
    outputs: dict[str, str] = {}
    master_cols = set((columns or {}).get("master") or [])
    for r in lay["relations"]:
        detail, parent = r.get("detail"), r.get("to")
        tag = f"relation {detail}->{parent}"
        if detail not in by_role:
            errs.append(f"{tag}: detail role {detail!r} is not declared in files")
        if parent not in by_role:
            errs.append(f"{tag}: parent role {parent!r} is not declared in files")
        if detail == "master":
            errs.append(f"{tag}: the master cannot be a detail")
        if detail in details_seen:
            errs.append(f"{tag}: detail role {detail!r} has more than one relation")
        details_seen.add(detail)
        on = r.get("on") if isinstance(r.get("on"), list) else []
        if not on or any(not (isinstance(p, dict) and p.get("parent") and p.get("detail")) for p in on):
            errs.append(f"{tag}: on needs at least one key part with parent and detail columns")
        parent_key = (by_role.get(parent) or {}).get("key")
        if on and isinstance(parent_key, list) and parent_key and len(on) != len(parent_key):
            errs.append(f"{tag}: key parts ({len(on)}) must match the parent key ({len(parent_key)})")
        norm = r["normalize"] if isinstance(r["normalize"], list) else [r["normalize"]]
        bad = [n for n in norm if n not in NORMALIZERS]
        if bad:
            errs.append(f"{tag}: unknown normalizer {bad}; use {NORMALIZERS}")
        mode = r.get("mode")
        if mode not in KNOWN_MODES:
            errs.append(f"{tag}: mode must be one of {sorted(KNOWN_MODES)}")
        elif mode not in SUPPORTED_MODES:
            errs.append(f"{tag}: mode {mode} is not yet supported (use {sorted(SUPPORTED_MODES)})")
        for key, allowed in (("join", ("left", "inner")), ("cardinality", ("one", "many")),
                             ("on_orphan_detail", ("exception", "drop")), ("on_missing_detail", ("exception", "allow")),
                             ("on_duplicate_master", ("reject_all", "first", "last"))):
            if r[key] not in allowed:
                errs.append(f"{tag}: {key} must be one of {allowed}")
        try:
            if not 0 <= float(r["min_match_rate"]) <= 1:
                errs.append(f"{tag}: min_match_rate must be between 0 and 1")
        except (TypeError, ValueError):
            errs.append(f"{tag}: min_match_rate must be a number")
        if mode == "aggregate":
            agg = r.get("aggregate") if isinstance(r.get("aggregate"), dict) else {}
            cols = agg.get("columns") if isinstance(agg.get("columns"), list) else []
            if not cols:
                errs.append(f"{tag}: aggregate needs at least one column")
            for c in cols:
                if not isinstance(c, dict):
                    errs.append(f"{tag}: every aggregate column must be an object")
                    continue
                name = c.get("as")
                if not name:
                    errs.append(f"{tag}: every aggregate column needs an 'as' name")
                    continue
                if c.get("op") not in AGG_OPS:
                    errs.append(f"{tag}: unknown aggregate op {c.get('op')!r} for {name}; use {AGG_OPS}")
                elif c["op"] != "count" and not c.get("col"):
                    errs.append(f"{tag}: aggregate column {name} needs a source col")
                if name in outputs:
                    errs.append(f"output column {name!r} is produced by both {outputs[name]} and {detail}")
                elif name in master_cols:
                    errs.append(f"output column {name!r} from {detail} clashes with a master column")
                outputs.setdefault(name, str(detail))

    if ready["require"] not in ("all_required", "master_only"):
        errs.append("readiness.require must be all_required or master_only")
    if ready["pairing"] not in PAIRINGS:
        errs.append(f"readiness.pairing must be one of {PAIRINGS}")
    try:
        if int(ready["wait_timeout_minutes"]) < 0:
            errs.append("readiness.wait_timeout_minutes must be 0 or more")
    except (TypeError, ValueError):
        errs.append("readiness.wait_timeout_minutes must be a number")
    if ready["on_timeout"] not in ("fail", "load_master_only", "alert_only"):
        errs.append("readiness.on_timeout must be fail, load_master_only or alert_only")
    elif ready["on_timeout"] == "load_master_only":
        req = [f.get("role") for f in files if f.get("role") != "master" and f.get("required")]
        if req:
            errs.append(f"readiness.on_timeout load_master_only is invalid while detail files are required: {req}")
    if ready["pairing"] == "window_minutes":
        try:
            if int(ready.get("window_minutes")) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errs.append("readiness.window_minutes must be a positive number for pairing=window_minutes")
    elif ready["pairing"] in NAMED_GROUP_PAIRINGS:
        for f in files:
            try:
                has_group = bool(re.compile(f.get("name_pattern") or "").groupindex)
            except re.error:
                continue
            if not has_group:
                errs.append(f"name_pattern for {f.get('role')} needs a named group such as (?P<date>...) for pairing={ready['pairing']}")
    return errs
