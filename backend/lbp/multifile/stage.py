"""Join stage of a multi-file batch: the batch's file set is joined ONCE into a CSV that the pipeline reads in
place of the master file.

    materialize_join(batch_id, cfg)   per-role header check, join, exceptions, match-rate gate; returns
                                      {"status": "ok" | "blocked", ...}
    join_reconciliation(rec, summary) the join's source-row accounting added to a batch reconciliation
    joined_pii_cols(cfg, columns)     PII columns of the joined file (master profile + detail roles)

Joined file: always UTF-8 CSV with a header (JOINED_PARSE_OPTIONS), whatever the inputs' formats, at
`data_dir/joined/<batch_id>.csv` (persisted to the raw zone through `storage` in AWS). Its rows are the
master's rows in master file order minus the masters excluded by join exceptions, so checkpoints index it.

Resume: the joined file is never regenerated once recorded. Its sha256 is in `join_summary`; a missing or
changed file on resume is an error (StageError), never a silent re-join.

Absent optional roles (a set queued with load_master_only or an accepted partial set): the role joins
against an empty header-only CSV, so masters follow `on_missing_detail`. Its header is the layout file's
declared `columns` when given, else the columns the relation references (its `on` detail keys, aggregate
`col`s, `where` variables and `order_by` columns). A required role is absent only when a recorded
`accept_partial` override on the set names it among its missing roles; otherwise that is a StageError.

Pre-flight per role: every role's header must hold its declared `columns` and the columns the relation
references; a missing one blocks the batch and names the role (resumable through override_preflight).

Join exceptions become rows of `exceptions` (category "join", rule_id = the JOINxx code, `role` set, queue
"join"). The joiner's JSONL holds unmasked values: each `raw` is masked per role (profile, mapping and
column-name PII detection), each `key` is replaced by a fingerprint, and the JSONL is deleted afterwards.
Messages, summaries and logs carry roles, columns and counts only.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
from pathlib import Path

from sqlalchemy import delete, select

from ..config import get_settings
from ..ingestion.parser import ParseOptions
from ..ingestion.pii import TARGET_PII_TYPES, VALUE_PATTERNS, detect_column_pii, mask_value
from ..rules.jsonlogic import referenced_vars
from ..store import db
from . import joiner
from .layout import normalize_layout

log = logging.getLogger(__name__)

JOINED_PARSE_OPTIONS = {"format": "csv", "delimiter": ",", "encoding": "utf-8"}
_EMPTY_PARSE_OPTIONS = {"format": "csv", "delimiter": ",", "sheet": 0, "header_row": 0, "encoding": "utf-8"}
BLOCKING_CODES = frozenset({"JOIN02", "JOIN03", "JOIN04", "JOIN05", "JOIN06"})
RULE_NAMES = {
    "JOIN01": "Detail row has no master row",
    "JOIN02": "Required detail row missing",
    "JOIN03": "Duplicate master key",
    "JOIN04": "Too many detail rows for the master",
    "JOIN05": "Join key empty or null",
    "JOIN06": "Inner join dropped the master row",
    "JOIN07": "Aggregate value not numeric",
}
EXCEPTION_CHUNK = 1000
JOIN_QUEUE = "join"


class StageError(RuntimeError):
    """The join stage cannot run (missing required role, missing/changed joined file). Text names roles,
    batches and files only, never row values."""


# ------------------------------------------------------------------ layout helpers
def _files_by_role(lay: dict) -> dict[str, dict]:
    return {f.get("role"): f for f in lay.get("files") or [] if f.get("role")}


def _relation_columns(rel: dict) -> list[str]:
    """Detail columns a relation reads: `on` keys, aggregate cols, where variables, order_by cols."""
    out = [p["detail"] for p in rel.get("on") or [] if isinstance(p, dict) and p.get("detail")]
    for spec in (rel.get("aggregate") or {}).get("columns") or []:
        if spec.get("col"):
            out.append(spec["col"])
        if spec.get("where"):
            out.extend(sorted(referenced_vars(spec["where"])))
        out.extend(k["col"] for k in spec.get("order_by") or [] if isinstance(k, dict) and k.get("col"))
    return list(dict.fromkeys(out))


def _needed_columns(lay: dict) -> dict[str, list[str]]:
    """role -> columns its file must have: declared `columns` plus those the join reads."""
    files = _files_by_role(lay)
    need = {role: list(f.get("columns") or []) for role, f in files.items()}
    master_key = files.get("master", {}).get("key") or []
    need["master"] = list(dict.fromkeys(need.get("master", []) + list(master_key)))
    for r in lay.get("relations") or []:
        role = r.get("detail")
        need[role] = list(dict.fromkeys(need.get(role, []) + _relation_columns(r)))
        need[r.get("to")] = list(dict.fromkeys(need.get(r.get("to"), []) +
                                               [p["parent"] for p in r.get("on") or [] if isinstance(p, dict) and p.get("parent")]))
    return need


def _empty_columns(lay: dict, role: str) -> list[str]:
    declared = list(_files_by_role(lay).get(role, {}).get("columns") or [])
    if declared:
        return declared
    rel = next((r for r in lay.get("relations") or [] if r.get("detail") == role), {})
    return _relation_columns(rel)


def _parse_overrides(lay: dict, cfg) -> dict[str, dict]:
    """The master is read with the feed's parse options (the layout's master entry wins where it sets one)."""
    master = _files_by_role(lay).get("master", {})
    return {"master": {**(cfg.parse_options or {}), **(master.get("parse_options") or {})}}


def _header(role: str, path: Path, opts: ParseOptions) -> list[str]:
    columns, rows = joiner._open_rows(role, Path(path), opts)  # started iterator: close() releases the file
    rows.close()
    return columns


def _role_opts(lay: dict, role: str, overrides: dict[str, dict]) -> ParseOptions:
    spec = _files_by_role(lay).get(role, {})
    return ParseOptions(**{**(spec.get("parse_options") or {}), **(overrides.get(role) or {})})


def check_role_headers(lay: dict, inputs: dict[str, Path], overrides: dict[str, dict]) -> dict[str, dict]:
    """{role: {"missing": [...]}} for each role whose file lacks a declared or join-referenced column."""
    need = _needed_columns(lay)
    out = {}
    for role, path in inputs.items():
        try:
            header = set(_header(role, path, _role_opts(lay, role, overrides)))
        except Exception as e:  # noqa: BLE001 - an unreadable file is reported by the join itself
            log.warning("join pre-flight: %s header unreadable (%s)", role, e.__class__.__name__)
            continue
        missing = [c for c in need.get(role, []) if c not in header]
        if missing:
            out[role] = {"missing": missing}
    return out


def _roles_summary(problems: dict[str, dict]) -> str:
    parts = [f"{role} file is missing column(s) {p['missing']}" for role, p in sorted(problems.items())]
    return "Blocked: " + "; ".join(parts) + "."


# ------------------------------------------------------------------ PII
def _target_type(target: str) -> str | None:
    from ..schema.sse_target import BY_NAME

    if target in TARGET_PII_TYPES:
        return TARGET_PII_TYPES[target]
    attr = BY_NAME.get(target)
    return "OTHER" if attr is not None and attr.pii else None


def _pii_by_role(cfg, lay: dict) -> dict[str, dict[str, str]]:
    """role -> {column: pii type}: the master profile, the layout's optional per-file `pii` map, mapping fields
    (a source `role.col`, or an aggregate output, feeding a PII target), and joined-file profile columns."""
    out: dict[str, dict[str, str]] = {role: dict(f.get("pii") or {}) for role, f in _files_by_role(lay).items()}
    out.setdefault("master", {})
    roles = set(out)
    agg_src: dict[str, tuple[str, str]] = {}
    for r in lay.get("relations") or []:
        for spec in (r.get("aggregate") or {}).get("columns") or []:
            if spec.get("as") and spec.get("col"):
                agg_src[spec["as"]] = (r.get("detail"), spec["col"])

    def put(name: str, kind: str) -> None:
        role, sep, col = name.partition(".")
        if sep and role in roles:
            out[role].setdefault(col, kind)
        elif name in agg_src:
            role, col = agg_src[name]
            out.setdefault(role, {}).setdefault(col, kind)
        else:
            out["master"].setdefault(name, kind)

    for c in (cfg.profile or {}).get("columns", []):
        if c.get("pii_type"):
            put(c["name"], c["pii_type"])
    for f in cfg.fields or []:
        if f.get("status") == "rejected":
            continue
        kind = _target_type(f.get("target") or "")
        if kind:
            for s in f.get("sources") or ([f["source"]] if f.get("source") else []):
                put(s, kind)
    return out


def _value_pii(v: str) -> str | None:
    for kind in ("SSN", "EMAIL", "PHONE"):
        if VALUE_PATTERNS[kind].match(v.strip()):
            return kind
    return None


def _mask_row(raw: dict, pii: dict[str, str]) -> dict:
    """Mask known PII columns; any other column whose name or value looks like PII is masked too (detail roles
    are rarely profiled)."""
    out = {}
    for k, v in (raw or {}).items():
        if v in (None, ""):
            out[k] = v
            continue
        v = str(v)
        kind = pii.get(k) or detect_column_pii(str(k), [])[0] or _value_pii(v)
        out[k] = mask_value(v, kind) if kind else v
    return out


def fingerprint(key: str | None) -> str | None:
    """A join key in an exception row: the deterministic token used elsewhere for NPI, never the value."""
    return mask_value(key, "KEY", mode="hash") if key else None


def joined_pii_cols(cfg, columns: list[str]) -> dict[str, str]:
    """{joined column: pii type} for masking the staged raw rows of a joined batch."""
    lay = normalize_layout(cfg.layout or {})
    by_role = _pii_by_role(cfg, lay)
    out = dict(cfg.pii_cols)
    agg_src = {spec["as"]: (r.get("detail"), spec.get("col")) for r in lay.get("relations") or []
               for spec in (r.get("aggregate") or {}).get("columns") or [] if spec.get("as")}
    for col in columns:
        role, sep, name = col.partition(".")
        if sep and role in by_role and role != "master":
            kind = by_role[role].get(name) or detect_column_pii(name, [])[0]
        elif col in agg_src and agg_src[col][1]:
            kind = by_role.get(agg_src[col][0], {}).get(agg_src[col][1])
        else:
            kind = by_role["master"].get(col)
        if kind:
            out[col] = kind
    return out


# ------------------------------------------------------------------ files
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _joined_dir() -> Path:
    d = get_settings().data_dir / "joined"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_empty(path: Path, columns: list[str]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\n").writerow(columns)
    return path


def _key_field(lay: dict, role: str) -> str:
    if role == "master":
        cols = _files_by_role(lay).get("master", {}).get("key") or []
    else:
        rel = next((r for r in lay.get("relations") or [] if r.get("detail") == role), {})
        cols = [p["detail"] for p in rel.get("on") or [] if isinstance(p, dict)]
    return ",".join(cols)[:80] or role


def _insert_join_exceptions(batch_id: str, source_id: str, jsonl: Path, lay: dict, pii: dict[str, dict[str, str]]) -> int:
    """Stream the JSONL into `exceptions` in bounded chunks (one transaction each). Returns rows written."""
    from ..pipeline.batch import _insert_exceptions

    n = 0
    buf: list[dict] = []

    def flush() -> None:
        if buf:
            with db.get_engine().begin() as c:
                _insert_exceptions(c, buf)
            buf.clear()

    with jsonl.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            code, role = rec["code"], rec["role"]
            blocking = code in BLOCKING_CODES
            buf.append({"exception_id": db.new_id("ex"), "batch_id": batch_id, "source_id": source_id,
                        "loan_number": fingerprint(rec.get("key")), "staging_id": None, "rule_id": code, "rule_version": 1,
                        "rule_name": RULE_NAMES.get(code, code), "category": "join", "severity": "FAIL" if blocking else "WARN",
                        "blocking": blocking, "field": _key_field(lay, role),
                        "original_value": json.dumps(_mask_row(rec.get("raw") or {}, pii.get(role, {})), ensure_ascii=False),
                        "message": f"{role} row {rec.get('row_number')}: {rec.get('message')}", "risk": "medium",
                        "tier": "T3", "queue": JOIN_QUEUE, "status": "open", "proposal": None, "qa_sample": False, "role": role,
                        "resolved_at": None, "resolved_value": None, "maker": None})
            n += 1
            if len(buf) >= EXCEPTION_CHUNK:
                flush()
    flush()
    return n


# ------------------------------------------------------------------ stage
def _layout_sha(lay: dict) -> str:
    return hashlib.sha256(json.dumps(lay, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]


def _summary_of(res, sha: str, cfg, lay: dict, absent: list[str]) -> dict:
    return {
        "per_role": {r: {"rows_in": s.rows_in, "matched": s.matched, "orphaned": s.orphaned, "rejected": s.rejected}
                     for r, s in res.per_role.items()},
        "exception_counts": dict(res.exception_counts), "master_match_rate": round(res.master_match_rate, 6),
        "detail_match_rate": {r: round(v, 6) for r, v in res.detail_match_rate.items()},
        "master_rate_by_role": {r: round(v, 6) for r, v in res.master_rate_by_role.items()}, "rows_out": res.rows_out,
        "columns": list(res.columns), "layout_version": cfg.version, "layout_sha256": _layout_sha(lay),
        "config_sha256": (cfg.sha256 or "")[:16], "sha256": sha, "absent_roles": absent, "joined_at": db.now().isoformat(),
    }


def _members(c, set_id: str) -> dict[str, str]:
    bf = db.batch_files
    return {r.role: r.file_path for r in c.execute(select(bf.c.role, bf.c.file_path).where(bf.c.set_id == set_id))}


def _accepted_missing(c, set_id: str) -> set[str]:
    """Roles a recorded `accept_partial` override on the set accepted as missing (never the master)."""
    ov = c.execute(select(db.file_sets.c.override).where(db.file_sets.c.set_id == set_id)).scalar() or {}
    return {r for o in ov.get("overrides") or [] if o.get("action") == "accept_partial"
            for r in o.get("missing_roles") or [] if r != "master"}


def _record(batch_id: str, vals: dict, audits: list[tuple[str, dict]]) -> None:
    """Every join-stage state change is ONE write: the batch columns and its audit entries commit together."""
    with db.get_engine().begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(**vals))
        for action, detail in audits:
            db.audit(c, "pipeline", action, "batch", batch_id, detail)


def _block_values(b, summary: dict, stage: str, message: str, cfg, extra_pf: dict | None = None) -> tuple[dict, dict]:
    """(batch values, summary) of a join-stage block: join_summary.blocked, a blocking pre-flight and the batch
    `blocked` (any previous override is kept in its history, so a new override is needed for this block)."""
    pf = dict(b.preflight or {})
    old = pf.pop("override", None)
    pf.update({"decision": "block", "summary": message, "stage": f"join_{stage}", "mapping_id": cfg.mapping_id,
               "mapping_version": cfg.mapping_version, "config_version": cfg.version, "checked_at": db.now().isoformat(),
               **(extra_pf or {})})
    if old:
        pf["join_overrides"] = [*pf.get("join_overrides", []), old]
    summary = {**summary, "blocked": {"stage": stage, "message": message}}
    return {"preflight": pf, "join_summary": summary, "status": "blocked", "error": message, "worker_id": None}, summary


def _blocked_result(stage: str, message: str, summary: dict) -> dict:
    return {"status": "blocked", "stage": stage, "message": message, "joined_path": summary.get("joined_path"),
            "summary": summary}


def _block(batch_id: str, b, summary: dict, stage: str, message: str, cfg, extra_pf: dict | None = None) -> dict:
    vals, summary = _block_values(b, summary, stage, message, cfg, extra_pf)
    _record(batch_id, vals, [("batch.join_blocked", {"stage": stage, "summary": message})])
    return _blocked_result(stage, message, summary)


def _regate(lay: dict, summary: dict) -> str | None:
    """The match-rate gate re-applied to a recorded join (the joiner's own comparison). A summary without
    per-relation master rates falls back to the overall master match rate for every relation."""
    master = summary.get("master_rate_by_role")
    if master is None:
        master = {r.get("detail"): float(summary.get("master_match_rate", 0.0)) for r in lay.get("relations") or []}
    return joiner.match_rate_gate(lay.get("relations") or [], master, summary.get("detail_match_rate") or {},
                                  summary.get("absent_roles") or ())


def _accept(batch_id: str, b, summary: dict, stage: str) -> dict:
    """Consume the override given for this join-stage block: move it from the pre-flight into join_summary."""
    pf = dict(b.preflight or {})
    ov = pf.pop("override")
    rec = {"stage": stage, **ov}
    pf["join_overrides"] = [*pf.get("join_overrides", []), rec]
    summary = {**summary, "blocked": None, "overrides": [*summary.get("overrides", []), rec]}
    with db.get_engine().begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(preflight=pf, join_summary=summary))
        db.audit(c, "pipeline", "batch.join_override_applied", "batch", batch_id, {"stage": stage, "reason": ov.get("reason")})
    return summary


def _reuse(batch_id: str, b) -> tuple[Path, dict]:
    from ..storage import local_path

    summary = dict(b.join_summary or {})
    try:
        path = local_path(b.joined_path)
    except Exception as e:  # noqa: BLE001
        raise StageError(f"joined file of batch {batch_id} cannot be read ({e.__class__.__name__}); it is never "
                         "regenerated on resume") from None
    if not path.exists():
        raise StageError(f"joined file of batch {batch_id} is missing; it is never regenerated on resume")
    if _sha256(path) != summary.get("sha256"):
        raise StageError(f"joined file of batch {batch_id} changed since it was joined (sha256 mismatch); "
                         "it is never regenerated on resume")
    return path, summary


def replay_source(b, cfg) -> tuple[str, dict, dict[str, str], dict]:
    """(joined file uri, parse options, pii cols, join summary) for replaying a file-set batch's held rows: the
    recorded joined file, verified like a resume; StageError when it is missing or changed."""
    if not b.joined_path:
        raise StageError(f"batch {b.batch_id} has no joined file; held rows of a file-set batch replay only from it")
    _, summary = _reuse(b.batch_id, b)
    return b.joined_path, dict(JOINED_PARSE_OPTIONS), joined_pii_cols(cfg, summary.get("columns") or []), summary


def _join(batch_id: str, b, cfg, lay: dict, inputs: dict[str, Path], overrides: dict[str, dict], absent: list[str]) -> dict:
    """Join into data_dir/joined/<batch_id>.csv, record the exceptions, persist; return the join summary."""
    from ..storage import local_path, persist_upload

    if (b.checkpoint or 0) > 0:
        raise StageError(f"batch {batch_id} has loaded rows but no joined file; it is never regenerated on resume")
    d = _joined_dir()
    tmp = d / "tmp"
    tmp.mkdir(exist_ok=True)
    out = d / f"{batch_id}.csv"
    empties = []
    try:
        for role in absent:
            empties.append(_write_empty(d / f"{batch_id}.{role}.empty.csv", _empty_columns(lay, role)))
            inputs[role] = empties[-1]
            overrides[role] = dict(_EMPTY_PARSE_OPTIONS)
        with db.get_engine().begin() as c:  # rows left by an attempt that crashed before recording its file
            c.execute(delete(db.exceptions).where(db.exceptions.c.batch_id == batch_id, db.exceptions.c.category == "join"))
        res = joiner.join_files(lay, inputs, overrides, out, tmp, absent_roles=absent)
        try:
            n = _insert_join_exceptions(batch_id, b.source_id, res.exceptions_path, lay, _pii_by_role(cfg, lay))
        finally:
            res.exceptions_path.unlink(missing_ok=True)  # unmasked values: never left on disk
    finally:
        for p in empties:
            p.unlink(missing_ok=True)
    sha = _sha256(out)
    uri = persist_upload(out, f"joined/{b.source_id}", {"batch_id": batch_id, "sha256": sha})
    if _sha256(local_path(uri)) != sha:
        raise StageError(f"joined file of batch {batch_id} did not persist intact")
    summary = {**_summary_of(res, sha, cfg, lay, absent), "joined_path": uri, "exceptions_recorded": n,
               "blocked": None, "overrides": list((b.join_summary or {}).get("overrides") or [])}
    vals = {"joined_path": uri, "total_rows": res.rows_out}
    audits = [("batch.joined", {"rows_out": res.rows_out, "exception_counts": summary["exception_counts"], "sha256": sha,
                                "absent_roles": absent, "per_role": summary["per_role"]})]
    result = None
    if res.blocked:  # the block marker is written with joined_path: a crash can never leave an unblocked join behind
        msg = f"Blocked: {res.blocked}."
        block_vals, summary = _block_values(b, summary, "match_rate", msg, cfg)
        vals.update(block_vals)
        audits.append(("batch.join_blocked", {"stage": "match_rate", "summary": msg}))
        result = _blocked_result("match_rate", msg, summary)
    _record(batch_id, {**vals, "join_summary": summary}, audits)
    return result or summary


def materialize_join(batch_id: str, cfg) -> dict:
    """Join the batch's file set once; reuse the recorded joined file on every later run. Returns
    {"status": "ok", "joined_path", "sha256", "extra_columns", "summary"} or {"status": "blocked", "stage",
    "message", ...}. Raises StageError / LayoutError when the stage cannot run (the caller fails the batch)."""
    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
        if b is None or not b.file_set_id:
            raise StageError(f"batch {batch_id} is not a file-set batch")
        members = _members(c, b.file_set_id)
        accepted_missing = _accepted_missing(c, b.file_set_id)
    if not cfg.layout:
        raise StageError(f"batch {batch_id} belongs to a file set but feed {b.source_id} has no published layout")
    lay = normalize_layout(cfg.layout)
    files = _files_by_role(lay)
    summary = dict(b.join_summary or {})
    override = (b.preflight or {}).get("override")
    blocked = summary.get("blocked") or {}

    def accepted(stage: str) -> bool:
        return bool(override) and blocked.get("stage") == stage

    if b.joined_path:
        _, summary = _reuse(batch_id, b)
        gate = None if summary.get("blocked") else _regate(lay, summary)
        if gate and not any(o.get("stage") == "match_rate" for o in summary.get("overrides") or []):
            summary["blocked"] = {"stage": "match_rate", "message": f"Blocked: {gate}."}
            blocked = summary["blocked"]  # a fresh block: only an override given after it is accepted
            override = None
    else:
        required = [r for r, f in files.items() if r == "master" or f.get("required")]
        missing_req = [r for r in required if r not in members and r not in accepted_missing]
        if missing_req:
            raise StageError(f"file set {b.file_set_id} has no file for required role(s) {missing_req}; "
                             "the batch cannot run without them")
        from ..storage import local_path

        inputs = {r: local_path(p) for r, p in members.items() if r in files}
        absent = sorted(r for r in files if r not in inputs)
        overrides = _parse_overrides(lay, cfg)
        problems = check_role_headers(lay, inputs, overrides)
        if problems:
            msg = _roles_summary(problems)
            if not accepted("roles"):
                return _block(batch_id, b, summary, "roles", msg, cfg, {"roles": problems})
            summary = _accept(batch_id, b, summary, "roles")
            with db.get_engine().connect() as c:
                b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
        summary = _join(batch_id, b, cfg, lay, inputs, overrides, absent)
        if summary.get("status") == "blocked":
            return summary
    if summary.get("blocked"):
        stage = summary["blocked"]["stage"]
        if not accepted(stage):
            return _block(batch_id, b, summary, stage, summary["blocked"]["message"], cfg)
        summary = _accept(batch_id, b, summary, stage)
    return {"status": "ok", "joined_path": summary["joined_path"], "sha256": summary["sha256"],
            "extra_columns": _detail_columns(summary.get("columns") or [], lay), "summary": summary}


def _detail_columns(columns: list[str], lay: dict) -> list[str]:
    """Joined columns that did not come from the master: detail `role.col` columns and aggregate outputs."""
    detail_roles = {r.get("detail") for r in lay.get("relations") or []}
    agg = {spec.get("as") for r in lay.get("relations") or [] for spec in (r.get("aggregate") or {}).get("columns") or []}
    return [c for c in columns if (c.partition(".")[0] in detail_roles and "." in c) or c in agg]


def join_reconciliation(rec: dict, summary: dict) -> dict:
    """Add the join's accounting to a reconciliation: per role rows read / matched / orphaned / rejected, and
    master rows read = rows reconciled by the pipeline (the joined rows) + rows excluded by join exceptions."""
    per = {r: {"rows_read": s["rows_in"], "matched": s["matched"], "orphaned": s["orphaned"], "rejected": s["rejected"]}
           for r, s in (summary.get("per_role") or {}).items()}
    m = per.get("master", {"rows_read": 0, "rejected": 0})
    joined = summary.get("rows_out", 0)
    j = {"per_role": per, "master_rows_read": m["rows_read"], "master_rows_excluded_by_join": m["rejected"],
         "joined_rows": joined, "exceptions": dict(summary.get("exception_counts") or {}),
         "absent_roles": list(summary.get("absent_roles") or []), "overrides": len(summary.get("overrides") or [])}
    j["balanced"] = (m["rows_read"] == joined + m["rejected"]) and rec.get("source_rows") == joined
    return {**rec, "join": j, "balanced": bool(rec.get("balanced")) and j["balanced"]}
