"""Create a multi-file feed from sample files: profile each role's file, join capped samples, register the feed
from the JOINED sample (so the draft mapping covers aggregate outputs and `role.column` merge columns), then
propose the layout (maker-checker applies as for any layout).

Everything that can be wrong with the files or the layout is checked before the first database write, so a
refused onboarding leaves no source, mapping or vendor behind; a failure after the feed is created removes it.
"""
from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import func, select

from ..ingestion.parser import ParseOptions, read_sample
from .layout import LayoutError, normalize_layout, validate_layout
from .preview import build_joined_sample
from .service import LayoutServiceError, _roles, propose_layout

SAMPLE_ROWS = 2000


class OnboardError(ValueError):
    pass


def _read(role: str, path: Path, opts: ParseOptions | None = None) -> tuple[list[str], int, str, str | None]:
    try:
        meta, rows = read_sample(path, SAMPLE_ROWS, opts)
    except Exception as e:  # noqa: BLE001 - unreadable file: a class-level message, never row values
        raise OnboardError(f"the {role} file could not be read ({e.__class__.__name__}); use a CSV, text or Excel file") from None
    if not meta.columns:
        raise OnboardError(f"the {role} file is empty (no header row)")
    if not rows:
        raise OnboardError(f"the {role} file has a header but no data rows")
    return list(meta.columns), len(rows), meta.format, meta.delimiter


def inspect_files(files: dict[str, tuple[bytes, str]]) -> dict[str, dict]:
    """{role: {columns, rows_sampled, format}} for sample files given as role -> (bytes, filename). No database."""
    out = {}
    tmp = Path(tempfile.mkdtemp(prefix="lbp_inspect_"))
    try:
        for role, (data, filename) in files.items():
            p = tmp / f"{role}{Path(filename or 'x.csv').suffix.lower() or '.csv'}"
            p.write_bytes(data)
            cols, n, fmt, _ = _read(role, p)
            out[role] = {"columns": cols, "rows_sampled": n, "format": fmt}
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def register_multifile_source(name: str, files: dict[str, Path], layout: dict, readiness: dict, actor: str, roles: list[str],
                              description: str = "", vendor_id: str | None = None) -> dict:
    from ..mapping import service as mapping_svc
    from ..config import get_settings
    from ..storage import persist_upload
    from ..store import db

    if not _roles(roles) & {"onboarding", "onboarding_reviewer", "admin"}:
        raise LayoutServiceError("Analyst or SME role required")
    if not (name or "").strip():
        raise OnboardError("give the feed a name")
    if not isinstance(layout, dict) or not layout:
        raise OnboardError("send a layout")
    readiness = readiness or {}

    spec_roles = [f.get("role") for f in layout.get("files") or [] if isinstance(f, dict)]
    dupes = sorted({r for r in spec_roles if spec_roles.count(r) > 1})
    if dupes:
        raise OnboardError(f"the layout lists the {dupes[0]} role more than once")
    if "master" not in files:
        raise OnboardError("a master file is required")
    extra = sorted(set(files) - set(spec_roles))
    if extra:
        raise OnboardError(f"the layout has no role named {extra[0]}; send one file per layout role ({sorted(spec_roles)})")
    missing = sorted(set(spec_roles) - set(files))
    if missing:
        raise OnboardError(f"no sample file was sent for the {missing[0]} role")

    cols_by_role: dict[str, list[str]] = {}
    master_meta = None
    for role, path in files.items():
        spec = next(f for f in layout["files"] if f.get("role") == role)
        opts = ParseOptions(**{k: v for k, v in (spec.get("parse_options") or {}).items() if k in ParseOptions.__dataclass_fields__})
        cols, _n, fmt, delim = _read(role, Path(path), opts)
        cols_by_role[role] = cols
        if role == "master":
            master_meta = {"format": fmt, "delimiter": delim}
    errs = validate_layout(layout, readiness, cols_by_role)
    if errs:
        raise OnboardError("; ".join(errs))

    tmp = Path(tempfile.mkdtemp(prefix="lbp_onboard_"))
    try:
        try:
            joined, sm = build_joined_sample(layout, readiness, {r: Path(p) for r, p in files.items()}, {}, tmp)
        except LayoutError as e:
            raise OnboardError(str(e)) from None
        except ValueError as e:
            raise OnboardError(f"a sample file could not be read ({e.__class__.__name__})") from None
        for role, st in sm["per_role"].items():
            if role != "master" and st["rows_in"] and not st["matched"]:
                raise OnboardError(f"no rows of the {role} file matched a master row on the join key; check the key columns")
        if sm["blocked"]:
            raise OnboardError(f"the sample files do not join well enough: {sm['blocked']}")
        keep = get_settings().data_dir / "samples"
        keep.mkdir(parents=True, exist_ok=True)
        dest = keep / f"{uuid.uuid4().hex[:12]}_{Path(name).name[:40].replace('/', '_') or 'feed'}_joined.csv"
        shutil.copyfile(joined, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    uri = persist_upload(dest, "samples")

    with db.get_engine().connect() as c:
        vendor_existed = bool(vendor_id) or bool(c.execute(select(db.vendors.c.vendor_id).where(
            func.lower(db.vendors.c.name) == name.strip().lower())).first())
    reg = mapping_svc.register_source(name.strip(), uri, actor, description, vendor_id=vendor_id)
    sid = reg["source_id"]
    try:
        profile = {**(reg["profile"] or {}), "role_columns": cols_by_role}
        with db.get_engine().begin() as c:
            c.execute(db.sources.update().where(db.sources.c.source_id == sid).values(
                profile=profile, parse_options={**master_meta, "format": master_meta["format"]}))
        proposed = propose_layout(sid, layout, readiness, actor, roles)
    except Exception:
        _compensate(sid, None if vendor_existed else reg["vendor_id"], actor)
        raise
    return {**reg, "profile": profile, "layout_draft": proposed["layout_draft"], "readiness_draft": proposed["readiness_draft"],
            "role_columns": cols_by_role, "join_summary": {k: sm[k] for k in ("per_role", "master_match_rate", "detail_match_rate",
                                                                               "exception_counts", "sampled")}}


def _compensate(source_id: str, created_vendor: str | None, actor: str) -> None:
    from ..store import db

    with db.get_engine().begin() as c:
        c.execute(db.mappings.delete().where(db.mappings.c.source_id == source_id))
        c.execute(db.sources.delete().where(db.sources.c.source_id == source_id))
        if created_vendor and not c.execute(select(func.count()).select_from(db.sources).where(db.sources.c.vendor_id == created_vendor)).scalar():
            c.execute(db.vendors.delete().where(db.vendors.c.vendor_id == created_vendor))
        db.audit(c, actor, "source.onboard_rollback", "source", source_id, {"reason": "multi-file onboarding failed after the feed was created"})
