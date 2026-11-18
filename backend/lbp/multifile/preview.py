"""Join preview: what a layout would produce from sample files, before anyone proposes it.

    preview_join(layout, readiness, samples, parse_options, n=10) -> dict

Read-only by construction: no database access, no publish, no audit row. Capped copies of the samples are
written to a private temp directory that is removed in `finally`; nothing else is written anywhere.

Sampling: the first MASTER_SAMPLE_ROWS master rows; each detail keeps the rows whose normalized key is among
the sampled masters' keys (per relation, with the relation's `normalize` ops) plus up to ORPHAN_SAMPLE_ROWS
non-matching rows, so orphans stay visible. The match rates, per-role counts and exception row numbers are
those of the sample (`sampled` says when the sample dropped rows; `rows_read` is what each file held). When
the master was cut, details of masters beyond the cut count as orphans.

Everything returned is masked like the join stage masks it: PII values in `rows` and in each exception's
`raw`, a fingerprint instead of the exception's `key`. Errors name roles and columns, never row values.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import tempfile
from itertools import islice
from pathlib import Path
from types import SimpleNamespace

from ..ingestion.parser import iter_rows
from . import joiner, stage
from .keys import normalize_key
from .layout import LayoutError, normalize_layout, role_name_error, validate_layout

MASTER_SAMPLE_ROWS = 2000
ORPHAN_SAMPLE_ROWS = 2000
EXCEPTION_EXAMPLES = 20
_SAMPLE_OPTIONS = {"format": "csv", "delimiter": ",", "encoding": "utf-8", "sheet": 0, "header_row": 0}


def _write(path: Path, columns: list[str], rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(columns)
        for r in rows:
            w.writerow([r.get(c, "") if r.get(c) is not None else "" for c in columns])


def safe_suffix(filename: str | None) -> str:
    """The file's extension when it is a plain one (the readers go by it), else .csv. Never part of a path."""
    suf = Path(filename or "x.csv").suffix.lower()
    return suf if re.fullmatch(r"\.[a-z0-9]{1,8}", suf) else ".csv"


def missing_samples(lay: dict, inputs) -> list[str]:
    """Layout roles that have no sample file (a role added to the layout without a file for it)."""
    return [f.get("role") for f in lay.get("files") or [] if isinstance(f, dict) and f.get("role") not in inputs]


def _opts(lay: dict, role: str, parse_options: dict[str, dict]):
    spec = {f.get("role"): f for f in lay["files"]}.get(role, {})
    return joiner._parse_options(role, spec, parse_options or {})


def _sample_files(lay: dict, inputs: dict[str, Path], parse_options: dict[str, dict], out_dir: Path):
    """(capped files by role, rows read by role, whether any row was dropped)."""
    rels = {r["detail"]: r for r in lay["relations"]}
    meta, it = iter_rows(inputs["master"], _opts(lay, "master", parse_options))
    master_cols = list(meta.columns)
    if not master_cols:
        raise LayoutError("master file is an empty file (no header row)")
    mrows = list(islice(it, MASTER_SAMPLE_ROWS + 1))
    dropped = len(mrows) > MASTER_SAMPLE_ROWS
    read = {"master": len(mrows) + (sum(1 for _ in it) if dropped else 0)}  # exact count; rows not held
    mrows = mrows[:MASTER_SAMPLE_ROWS]
    for rel in rels.values():
        joiner._require_columns("master", master_cols, [p["parent"] for p in rel["on"]])
    joiner._require_columns("master", master_cols, list(next(f for f in lay["files"] if f["role"] == "master").get("key") or []))
    out = {"master": out_dir / "r0.csv"}  # temp files are named by position, never by role
    _write(out["master"], master_cols, mrows)

    for i, (role, rel) in enumerate(rels.items(), start=1):
        ops = rel["normalize"] if isinstance(rel["normalize"], list) else [rel["normalize"]]
        keys = set()
        for r in mrows:
            k = normalize_key([r.get(p["parent"]) for p in rel["on"]], ops)
            if k is not None:
                keys.add(k)
        dmeta, dit = iter_rows(inputs[role], _opts(lay, role, parse_options))
        dcols = list(dmeta.columns)
        if not dcols:
            raise LayoutError(f"{role} file is an empty file (no header row)")
        joiner._require_columns(role, dcols, [p["detail"] for p in rel["on"]])
        kept, orphans, seen = [], 0, 0
        for r in dit:
            seen += 1
            k = normalize_key([r.get(p["detail"]) for p in rel["on"]], ops)
            if k is not None and k in keys:
                kept.append(r)
            elif orphans < ORPHAN_SAMPLE_ROWS:
                orphans += 1
                kept.append(r)
            else:
                dropped = True
        read[role] = seen
        out[role] = out_dir / f"r{i}.csv"
        _write(out[role], dcols, kept)
    return out, read, dropped


def _first_exceptions(path: Path, lay: dict, cfg) -> list[dict]:
    pii = stage._pii_by_role(cfg, lay)
    out = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            out.append({"code": rec["code"], "role": rec["role"], "row_number": rec.get("row_number"),
                        "message": rec.get("message"), "raw": stage._mask_row(rec.get("raw") or {}, pii.get(rec["role"], {})),
                        "key": stage.fingerprint(rec.get("key"))})
            if len(out) >= EXCEPTION_EXAMPLES:
                break
    return out


def build_joined_sample(layout: dict, readiness: dict | None, inputs: dict[str, Path], parse_options: dict[str, dict],
                        out_dir: Path) -> tuple[Path, dict]:
    """Cap the sample files, join them, and return (joined CSV path, summary). Same sampling and join as
    `preview_join`. Raises LayoutError for an invalid layout or files that cannot be joined; data problems
    are counted in the summary (`blocked` lists relations under their match-rate floor)."""
    errs = validate_layout(layout, readiness)
    if errs:
        raise LayoutError("; ".join(errs))
    lay = normalize_layout(layout)
    if "master" not in inputs:
        raise LayoutError("no input file for role master")
    gaps = missing_samples(lay, inputs)
    if gaps:
        raise LayoutError(f"no sample file was sent for the {gaps[0]} role; add its sample file or remove the role from the layout")
    out_dir = Path(out_dir)
    cap_dir, work = out_dir / "cap", out_dir / "work"
    for d in (cap_dir, work):
        d.mkdir(parents=True, exist_ok=True)
    capped, read, dropped = _sample_files(lay, inputs, parse_options, cap_dir)
    res = joiner.join_files(lay, capped, {r: dict(_SAMPLE_OPTIONS) for r in capped}, work / "joined.csv", work)
    summary = {
        "columns": list(res.columns),
        "per_role": {r: {"rows_in": s.rows_in, "matched": s.matched, "orphaned": s.orphaned, "rejected": s.rejected}
                     for r, s in res.per_role.items()},
        "exception_counts": dict(res.exception_counts),
        "master_match_rate": round(res.master_match_rate, 6),
        "detail_match_rate": {r: round(v, 6) for r, v in res.detail_match_rate.items()},
        "blocked": res.blocked, "sampled": dropped, "rows_read": read,
        "exceptions_path": res.exceptions_path, "layout": lay,
    }
    return work / "joined.csv", summary


def preview_join(layout: dict, readiness: dict | None, samples: dict[str, tuple[bytes, str]],
                 parse_options: dict[str, dict], n: int = 10, cfg=None) -> dict:
    """Join capped copies of `samples` (role -> (bytes, filename)). `cfg` (a feed config, optional) supplies the
    PII profile and mapping used for masking; the previewed layout replaces its layout."""
    errs = validate_layout(layout, readiness)
    if errs:
        return {"errors": errs}
    lay = normalize_layout(layout)
    profile = (getattr(cfg, "profile", None) or {}) if cfg is not None else {}
    cfg = SimpleNamespace(layout=lay, profile=profile, fields=list(getattr(cfg, "fields", None) or []), version=0,
                          pii_cols={c["name"]: c["pii_type"] for c in profile.get("columns", []) if c.get("pii_type")})
    tmp = Path(tempfile.mkdtemp(prefix="lbp_preview_"))
    try:
        raw_dir, cap_dir, work = tmp / "raw", tmp / "cap", tmp / "work"
        for d in (raw_dir, cap_dir, work):
            d.mkdir()
        bad = next((role_name_error(r) for r in samples if role_name_error(r)), None)
        if bad:
            return {"errors": [bad]}
        inputs = {}
        for i, (role, (data, filename)) in enumerate(samples.items()):
            p = raw_dir / f"s{i}{safe_suffix(filename)}"  # named by position, never by role
            p.write_bytes(data)
            inputs[role] = p
        if "master" not in inputs:
            return {"errors": ["no input file for role master"]}
        try:
            joined, sm = build_joined_sample(layout, readiness, inputs, parse_options, tmp / "out")
        except LayoutError as e:
            return {"errors": [str(e)]}
        except ValueError as e:  # an unreadable or unsupported file: a safe class-level message
            return {"errors": [f"a sample file could not be read ({e.__class__.__name__})"]}
        pii = stage.joined_pii_cols(cfg, sm["columns"])
        rows = []
        with joined.open(encoding="utf-8", newline="") as f:
            for r in islice(csv.DictReader(f), max(0, n)):
                rows.append(stage._mask_row(r, pii))
        return {
            "columns": sm["columns"], "rows": rows, "per_role": sm["per_role"],
            "exception_counts": sm["exception_counts"],
            "exceptions": _first_exceptions(sm["exceptions_path"], lay, cfg),
            "master_match_rate": sm["master_match_rate"], "detail_match_rate": sm["detail_match_rate"],
            "blocked": sm["blocked"], "sampled": sm["sampled"], "rows_read": sm["rows_read"], "errors": [],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
