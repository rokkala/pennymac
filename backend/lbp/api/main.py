"""Loan Boarding Platform API (FastAPI).

Runs as one service locally and on ECS Fargate behind API Gateway in AWS. The stateless
routes (upload presign, batch status, exception CRUD, ai-map) are also exposed as Lambda
handlers in aws/lambdas via Mangum.

Security model
  * Authentication: lbp.security (Cognito JWT verified in-process; dev headers only locally).
  * Authorization: ROUTE_ROLES below is the single, reviewable matrix of which Cognito groups
    may call each write endpoint. Any write endpoint missing from the matrix is admin-only
    (deny by default); tests fail if a new write route is added without an entry.
  * Business guardrails (maker-checker, Compliance-only T5, SME approval) are additionally
    enforced inside the services, so they hold for Lambda and batch callers too.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select, text

from .. import samples
from ..analytics import service as analytics
from ..config import get_settings
from ..dispatch import aws_mode, dispatch, start_glue
from ..exceptions.manager import ExceptionActionError, ExceptionManager
from ..exceptions.policy import DEFAULT_POLICY, TIER_LABELS, PolicyError, get_policy, set_policy
from ..ingestion.parser import read_sample
from ..ingestion.profiler import profile_rows
from ..mapping import service as mapping_svc
from ..mapping.engine import suggest_mappings
from ..mapping.inspect import field_inspect, mapping_dq, value_coverage, with_value_map
from ..mapping.transforms import LOOKUP_TABLES, OP_CATALOG
from ..pipeline import batch as pipeline
from ..rules.authoring import draft_from_text
from ..rules.jsonlogic import apply as jl_apply
from ..rules.jsonlogic import validate as jl_validate
from ..rules.registry import RuleError, RuleRegistry, run_tests
from ..rules.shapes import ShapeError, catalog as shape_catalog
from ..rules.shapes import compile_tree, decompile, fields_payload, pattern_presets
from ..rules import template_store as rule_tpl
from ..schema.sse_target import as_dicts
from ..security import Principal, current_principal
from ..store import db

log = logging.getLogger("lbp.api")

PUBLIC = {("GET", "/api/health"), ("GET", "/api/ready"), ("GET", "/api/config")}
# Member roles; *_reviewer principals also carry the member role via expand_roles().
EDIT_MAPPING = ("onboarding",)
WORK_EXCEPTIONS = ("monitoring", "compliance")
ONBOARDING_REVIEW = ("onboarding_reviewer",)
MONITORING_REVIEW = ("monitoring_reviewer",)
COMPLIANCE_REVIEW = ("compliance_reviewer",)
ROUTE_ROLES: dict[tuple[str, str], tuple[str, ...]] = {
    ("POST", "/api/ai-map"): EDIT_MAPPING,
    ("POST", "/api/sources"): EDIT_MAPPING,
    ("POST", "/api/sources/{source_id}/mappings/new-version"): EDIT_MAPPING,
    ("POST", "/api/mappings/{mapping_id}/fields/{target}"): EDIT_MAPPING,
    ("POST", "/api/mappings/{mapping_id}/fields"): EDIT_MAPPING,
    ("POST", "/api/mappings/{mapping_id}/fields/{target}/retarget"): EDIT_MAPPING,
    ("POST", "/api/mappings/{mapping_id}/suggest"): EDIT_MAPPING,
    ("POST", "/api/mappings/{mapping_id}/fields/{target}/values"): EDIT_MAPPING,
    ("POST", "/api/mappings/{mapping_id}/fields/{target}/inspect"): EDIT_MAPPING,
    ("POST", "/api/mappings/{mapping_id}/accept-all"): EDIT_MAPPING,
    ("POST", "/api/mappings/{mapping_id}/submit"): EDIT_MAPPING,
    ("POST", "/api/mappings/{mapping_id}/approve"): ONBOARDING_REVIEW,
    ("POST", "/api/upload"): ("monitoring",),
    ("POST", "/api/upload/presign"): ("monitoring",),
    ("POST", "/api/batches/{batch_id}/pause"): ("monitoring",),
    ("POST", "/api/batches/{batch_id}/resume"): ("monitoring", "onboarding_reviewer"),
    ("POST", "/api/batches/{batch_id}/override-preflight"): ("onboarding_reviewer", "compliance_reviewer"),
    ("POST", "/api/batches/{batch_id}/remap"): EDIT_MAPPING,
    ("POST", "/api/batches/{batch_id}/replay"): ("monitoring", "onboarding_reviewer"),
    ("POST", "/api/exceptions/{exception_id}/resolve"): WORK_EXCEPTIONS,
    ("POST", "/api/exceptions/{exception_id}/checker"): MONITORING_REVIEW,
    ("POST", "/api/exceptions/{exception_id}/reject"): WORK_EXCEPTIONS,
    ("POST", "/api/exceptions/{exception_id}/escalate"): WORK_EXCEPTIONS,
    ("POST", "/api/exceptions/{exception_id}/compliance-clear"): COMPLIANCE_REVIEW,
    ("POST", "/api/exceptions/{exception_id}/rollback"): ("monitoring", "monitoring_reviewer"),
    ("POST", "/api/exceptions/{exception_id}/qa"): WORK_EXCEPTIONS,
    ("POST", "/api/exceptions/{exception_id}/ai-suggest"): WORK_EXCEPTIONS,
    ("POST", "/api/exceptions/bulk-resolve"): ("monitoring", "monitoring_reviewer"),
    ("POST", "/api/rules"): ("onboarding", "compliance_reviewer"),
    ("PUT", "/api/rules/{rule_id}/{version}"): ("onboarding", "compliance_reviewer"),
    ("POST", "/api/rules/{rule_id}/{version}/transition"): ("onboarding_reviewer", "compliance_reviewer"),
    ("DELETE", "/api/rules/{rule_id}"): ("onboarding_reviewer", "compliance_reviewer"),
    ("POST", "/api/rules/author"): EDIT_MAPPING,
    ("POST", "/api/rules/compose"): EDIT_MAPPING,
    ("POST", "/api/rules/test"): EDIT_MAPPING,
    ("GET", "/api/rules/fields"): ("onboarding", "monitoring", "compliance"),
    ("GET", "/api/rules/shapes"): ("onboarding", "monitoring", "compliance"),
    ("GET", "/api/rules/templates"): ("onboarding", "monitoring", "compliance"),
    ("POST", "/api/maintenance/rule-templates"): ("onboarding_reviewer", "admin"),
    ("PUT", "/api/maintenance/rule-templates/{template_id}"): ("onboarding_reviewer", "admin"),
    ("POST", "/api/maintenance/rule-templates/{template_id}/hide"): ("onboarding_reviewer", "admin"),
    ("POST", "/api/maintenance/rule-templates/{template_id}/unhide"): ("onboarding_reviewer", "admin"),
    ("DELETE", "/api/maintenance/rule-templates/{template_id}"): ("onboarding_reviewer", "admin"),
    ("PUT", "/api/policy"): COMPLIANCE_REVIEW,
    ("POST", "/api/analytics/ask"): ("onboarding", "monitoring", "compliance"),
    ("POST", "/api/demo/seed"): ("admin",),
    ("POST", "/api/demo/setup"): ("admin",),
    ("POST", "/api/admin/retention/purge"): COMPLIANCE_REVIEW,
    # vendors
    ("POST", "/api/vendors"): EDIT_MAPPING,
    ("PUT", "/api/vendors/{vendor_id}"): EDIT_MAPPING + COMPLIANCE_REVIEW,
    ("POST", "/api/sources/{source_id}/vendor"): ONBOARDING_REVIEW,
    ("POST", "/api/sources/{source_id}/publish"): ONBOARDING_REVIEW,
    # incremental loads, sequencing, delivery scheduler
    ("PUT", "/api/sources/{source_id}/delivery"): EDIT_MAPPING,
    ("POST", "/api/sources/{source_id}/delivery/approve"): ONBOARDING_REVIEW,
    ("POST", "/api/batches/{batch_id}/skip-gap"): ("monitoring", "onboarding_reviewer"),
    ("POST", "/api/batches/{batch_id}/apply-out-of-order"): ("onboarding_reviewer", "compliance_reviewer"),
    ("POST", "/api/batches/{batch_id}/discard"): ("monitoring", "onboarding_reviewer"),
    ("POST", "/api/batches/{batch_id}/snapshot-reviews"): ONBOARDING_REVIEW,
    ("POST", "/api/schedules"): ("monitoring", "onboarding"),
    ("PUT", "/api/schedules/{schedule_id}"): ("monitoring", "onboarding"),
    ("POST", "/api/schedules/{schedule_id}/approve"): ("onboarding_reviewer", "compliance_reviewer"),
    ("POST", "/api/schedules/{schedule_id}/status"): ("monitoring", "onboarding_reviewer"),
    ("POST", "/api/schedules/{schedule_id}/pull-now"): ("monitoring", "onboarding_reviewer"),
    ("POST", "/api/deliveries/{delivery_id}/waive"): ("monitoring", "onboarding_reviewer"),
    ("POST", "/api/scheduler/tick"): ("monitoring",),
    # personas (Cognito-native user admin + screen matrix; matrix writes are admin-only)
    ("PUT", "/api/personas/screens"): ("admin",),
    ("POST", "/api/personas/users"): ("admin",),
    ("PUT", "/api/personas/users/{username}"): ("admin",),
    ("POST", "/api/personas/users/{username}/reset-password"): ("admin",),
    # any authenticated user (empty need → authorize skips role check)
    ("POST", "/api/notifications/{notif_id}/read"): (),
    ("POST", "/api/notifications/read-all"): (),
}
READ_RESTRICTED: dict[str, tuple[str, ...]] = {
    "/api/audit": ("compliance_reviewer", "onboarding_reviewer"),
    "/api/audit/verify": COMPLIANCE_REVIEW,
    "/api/maintenance/artifacts": ("onboarding_reviewer", "admin"),
    "/api/maintenance/artifacts/{artifact_id}": ("onboarding_reviewer", "admin"),
    "/api/maintenance/rule-templates": ("onboarding_reviewer", "admin"),
    "/api/maintenance/rule-templates/{template_id}": ("onboarding_reviewer", "admin"),
    "/api/personas/screens": ("admin",),
    "/api/personas/users": ("admin",),
    # /api/personas/me/screens is any authenticated user (not listed → open to all roles)
}


async def authorize(request: Request) -> None:
    """Global dependency: authenticate every /api call and apply ROUTE_ROLES."""
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    method = request.method
    if not path.startswith("/api") or (method, path) in PUBLIC or method == "OPTIONS":
        return
    p = current_principal(request.headers.get("authorization"), request.headers.get("x-user"), request.headers.get("x-roles"))
    request.state.principal = p
    if method == "GET":
        need = READ_RESTRICTED.get(path)
    else:
        need = ROUTE_ROLES.get((method, path), ("admin",))
    if need and not p.has(*need):
        raise HTTPException(403, f"requires one of: {', '.join(need)}")


@asynccontextmanager
async def lifespan(_app):
    s = get_settings()
    problems = s.validate_for_production()
    if problems:
        raise RuntimeError("Refusing to start with an unsafe configuration: " + "; ".join(problems))
    if s.auto_create_schema:
        db.get_engine()
    else:
        db.check_schema_current()
    n = RuleRegistry().seed_defaults()
    if n:
        log.info("seeded %d default rules", n)
    nt = rule_tpl.seed_builtins()
    if nt:
        log.info("seeded %d rule templates", nt)
    if s.env == "local":
        try:
            from ..personas import ensure_demo_cast

            ensure_demo_cast(actor="system")
        except Exception:  # noqa: BLE001 - local cast seed is best-effort
            log.exception("demo cast seed failed")
    stop = None
    if s.scheduler_enabled and s.env == "local":
        stop = _start_local_scheduler()
    yield
    if stop:
        stop.set()


def _start_local_scheduler():
    """Local single-process mode: tick the delivery scheduler every minute and start what it releases.
    (AWS: EventBridge Scheduler invokes the scheduler_tick Lambda; ECS workers pick up queued batches.)"""
    import threading

    from ..scheduling import service as sched

    stop = threading.Event()

    def loop():
        while not stop.wait(60):
            try:
                for bid in sched.tick().get("batches", []):
                    dispatch(bid)
            except Exception:  # noqa: BLE001 - keep ticking
                log.exception("scheduler tick failed")

    threading.Thread(target=loop, daemon=True, name="scheduler").start()
    return stop


app = FastAPI(title="PennyMac Loan Boarding Platform", version="1.0.0", lifespan=lifespan, dependencies=[Depends(authorize)],
              description="Mapping, validation, exception management and analytics for SSE loan boarding.")
_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["authorization", "content-type", "x-user", "x-roles", "x-request-id"])

access_log = logging.getLogger("lbp.access")


@app.middleware("http")
async def hardening(request: Request, call_next):
    """Request id, security headers, no-store caching for API data, structured access log (no bodies)."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    t0 = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 - never leak internals (or NPI in SQL errors) to the client
        log.error("unhandled error rid=%s path=%s", rid, request.url.path, exc_info=False)
        response = JSONResponse({"detail": "internal error", "request_id": rid}, status_code=500)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self' https://*.amazoncognito.com; frame-ancestors 'none'")
    p = getattr(request.state, "principal", None)
    access_log.info(json.dumps({"rid": rid, "method": request.method, "path": request.url.path, "status": response.status_code,
                                "ms": round((time.monotonic() - t0) * 1000, 1), "user": p.name if p else None}))
    return response


registry = RuleRegistry()
exceptions_mgr = ExceptionManager()


class User(BaseModel):
    name: str
    roles: list[str]


def current_user(request: Request) -> User:
    p: Principal | None = getattr(request.state, "principal", None)
    if p is None:
        raise HTTPException(401, "not authenticated")
    return User(name=p.name, roles=list(p.roles))


def _scope(vendor_id: str | None) -> list[str] | None:
    """Feed ids for a vendor filter (None = all vendors)."""
    from ..vendors import VendorError, source_ids

    try:
        return source_ids(vendor_id)
    except VendorError as e:
        raise HTTPException(404, str(e)) from None


def _err(e: Exception, code: int = 400):
    raise HTTPException(status_code=code, detail=str(e))


def upload_dir() -> Path:
    p = get_settings().data_dir / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


ALLOWED_UPLOADS = {".csv", ".txt", ".dat", ".psv", ".xlsx", ".xlsm"}


def _save_upload(f: UploadFile) -> Path:
    """Stream an upload to disk with size, extension and content-type checks (no executables, no zip bombs)."""
    safe = Path(f.filename or "upload").name.replace("..", "_")
    ext = Path(safe).suffix.lower()
    if ext not in ALLOWED_UPLOADS:
        raise HTTPException(415, f"unsupported file type {ext or '(none)'}; allowed: {', '.join(sorted(ALLOWED_UPLOADS))}")
    limit = get_settings().max_upload_mb * 1024 * 1024
    dest = upload_dir() / f"{uuid.uuid4().hex[:12]}_{safe}"
    size = 0
    with dest.open("wb") as out:
        while chunk := f.file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"file exceeds the {get_settings().max_upload_mb} MB limit")
            out.write(chunk)
    head = dest.open("rb").read(8192)
    if ext in (".xlsx", ".xlsm"):
        if head[:2] != b"PK":
            dest.unlink(missing_ok=True)
            raise HTTPException(415, "not a valid Excel workbook")
        import zipfile

        try:
            with zipfile.ZipFile(dest) as z:
                if sum(i.file_size for i in z.infolist()) > limit * 20:
                    raise HTTPException(413, "workbook expands beyond the allowed size")
        except zipfile.BadZipFile:
            dest.unlink(missing_ok=True)
            raise HTTPException(415, "corrupt Excel workbook") from None
    elif b"\x00" in head or head[:2] in (b"MZ", b"\x7fE"):
        dest.unlink(missing_ok=True)
        raise HTTPException(415, "binary content is not a delimited text file")
    return dest


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health():
    """Liveness: the process is up. No dependencies, no configuration details."""
    return {"status": "ok"}


@app.get("/api/ready")
def ready():
    """Readiness for the load balancer: database reachable and schema current, rule set loaded."""
    checks = {}
    try:
        with db.get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["database"] = f"error: {e.__class__.__name__}"
    try:
        checks["active_rules"] = len(registry.runtime_set()["active"])
    except Exception as e:  # noqa: BLE001
        checks["active_rules"] = f"error: {e.__class__.__name__}"
    ok = checks["database"] == "ok" and isinstance(checks["active_rules"], int) and checks["active_rules"] > 0
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)


@app.get("/api/config")
def web_config():
    """Public settings the web app needs to sign users in (no secrets)."""
    s = get_settings()
    out = {"auth": "cognito" if s.auth_mode == "jwt" else "dev", "cognito_domain": s.cognito_domain,
           "client_id": s.cognito_client_id, "region": s.cognito_region, "demo": s.enable_demo}
    if s.enable_demo:
        out["demo_setup"] = {"available": True, "scales": ["compact", "full"], "default_scale": "compact"}
    return out


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {**user.model_dump(), "auth": get_settings().auth_mode}


@app.get("/api/schema/target")
def target_schema():
    return {"attributes": as_dicts()}


@app.get("/api/meta/transforms")
def transforms_catalog():
    return {"ops": OP_CATALOG, "lookup_tables": {k: len(v) for k, v in LOOKUP_TABLES.items()}}


# ------------------------------------------------------------------ AI map (stateless)
@app.post("/api/ai-map")
def ai_map(file: UploadFile = File(...)):
    p = _save_upload(file)
    try:
        meta, rows = read_sample(p, 1000)
        prof = profile_rows(meta.columns, rows)
        return {"format": meta.format, "profile": prof, **suggest_mappings(prof, rows)}
    finally:
        p.unlink(missing_ok=True)


# ------------------------------------------------------------------ vendors
class VendorIn(BaseModel):
    name: str | None = None
    vendor_type: str | None = None
    legal_name: str | None = None
    external_ref: str | None = None
    contact: dict | None = None
    notes: str | None = None
    status: str | None = None
    reason: str | None = None


def _vendor_call(fn, *a):
    from ..vendors import VendorError

    try:
        return fn(*a)
    except VendorError as e:
        raise HTTPException(404 if "not found" in str(e) else 400, str(e)) from None


@app.get("/api/vendors")
def vendors_list():
    from .. import vendors as vendor_svc

    return {"vendors": vendor_svc.list_vendors()}


@app.post("/api/vendors")
def vendors_create(body: VendorIn, user: User = Depends(current_user)):
    from .. import vendors as vendor_svc

    return _vendor_call(vendor_svc.create_vendor, body.model_dump(exclude_none=True), user.name, user.roles)


@app.get("/api/vendors/{vendor_id}")
def vendors_get(vendor_id: str):
    from .. import vendors as vendor_svc

    return _vendor_call(vendor_svc.get_vendor, vendor_id)


@app.put("/api/vendors/{vendor_id}")
def vendors_update(vendor_id: str, body: VendorIn, user: User = Depends(current_user)):
    from .. import vendors as vendor_svc

    return _vendor_call(vendor_svc.update_vendor, vendor_id, body.model_dump(exclude_none=True), user.name, user.roles)


class MoveFeed(BaseModel):
    vendor_id: str
    reason: str


@app.post("/api/sources/{source_id}/vendor")
def move_feed(source_id: str, body: MoveFeed, user: User = Depends(current_user)):
    from .. import vendors as vendor_svc

    return _vendor_call(vendor_svc.move_feed, source_id, body.vendor_id, user.name, user.roles, body.reason)


# ------------------------------------------------------------------ sources & mappings (Workflow 1)
@app.post("/api/sources")
def create_source(name: str = Form(...), description: str = Form(""), file: UploadFile = File(...), vendor_id: str | None = Form(None),
                  user: User = Depends(current_user)):
    """Add a feed (a file layout from a vendor) from a sample file; the AI drafts its mapping."""
    from ..storage import persist_upload

    p = persist_upload(_save_upload(file), "samples")
    try:
        return mapping_svc.register_source(name, p, user.name, description, vendor_id=vendor_id or None)
    except mapping_svc.MappingError as e:
        _err(e)


@app.get("/api/sources")
def list_sources(vendor_id: str | None = None):
    ids = _scope(vendor_id)
    with db.get_engine().connect() as c:
        rows = c.execute(select(db.sources.c.source_id, db.sources.c.name, db.sources.c.format, db.sources.c.status,
                                db.sources.c.active_mapping_id, db.sources.c.created_by, db.sources.c.created_at, db.sources.c.delivery,
                                db.sources.c.delivery_draft, db.sources.c.last_sequence, db.sources.c.vendor_id)
                         .order_by(db.sources.c.created_at.desc())).all()
        vnames = dict(c.execute(select(db.vendors.c.vendor_id, db.vendors.c.name)).all())
        nsched = dict(c.execute(select(db.delivery_schedules.c.source_id, func.count()).where(
            db.delivery_schedules.c.status.in_(("active", "paused", "pending_approval"))).group_by(db.delivery_schedules.c.source_id)).all())
        maps = c.execute(select(db.mappings.c.mapping_id, db.mappings.c.source_id, db.mappings.c.version, db.mappings.c.status,
                                db.mappings.c.stats)).all()
    by_src: dict[str, list] = {}
    for m in maps:
        by_src.setdefault(m.source_id, []).append({"mapping_id": m.mapping_id, "version": m.version, "status": m.status,
                                                   "auto_mapped_pct": (m.stats or {}).get("auto_mapped_pct")})
    from ..pipeline.delivery import display_sequence, profile_of

    out = []
    for r in rows:
        if ids is not None and r.source_id not in ids:
            continue
        d = {k: v for k, v in db.row_to_dict(r).items() if k not in ("delivery", "delivery_draft", "last_sequence")}
        d["vendor_name"] = vnames.get(r.vendor_id)
        d.update(load_type=profile_of(r.delivery)["load_type"], delivery_pending=bool(r.delivery_draft),
                 last_sequence=display_sequence(r.last_sequence), schedules=nsched.get(r.source_id, 0),
                 mappings=sorted(by_src.get(r.source_id, []), key=lambda x: x["version"]))
        out.append(d)
    return {"sources": out}


@app.get("/api/sources/{source_id}")
def get_source(source_id: str):
    with db.get_engine().connect() as c:
        r = c.execute(select(db.sources).where(db.sources.c.source_id == source_id)).first()
    if not r:
        raise HTTPException(404, "source not found")
    return db.row_to_dict(r)


@app.post("/api/sources/{source_id}/mappings/new-version")
def new_mapping_version(source_id: str, user: User = Depends(current_user)):
    try:
        return mapping_svc.new_version(source_id, user.name)
    except mapping_svc.MappingError as e:
        _err(e)


@app.get("/api/mappings/{mapping_id}")
def get_mapping(mapping_id: str):
    try:
        return mapping_svc.get_mapping(mapping_id)
    except mapping_svc.MappingError as e:
        _err(e, 404)


class FieldAction(BaseModel):
    action: str
    source: str | None = None
    sources: list[str] | None = None
    transform: list[dict] | None = None
    default: Any = None


@app.post("/api/mappings/{mapping_id}/fields/{target}")
def update_mapping_field(mapping_id: str, target: str, body: FieldAction, user: User = Depends(current_user)):
    try:
        return mapping_svc.update_field(mapping_id, target, body.action, user.name, body.source, body.sources, body.transform, body.default)
    except mapping_svc.MappingError as e:
        _err(e)


class NewField(BaseModel):
    target: str
    sources: list[str] | None = None
    transform: list[dict] = []
    default: Any = None


@app.post("/api/mappings/{mapping_id}/fields")
def add_mapping_field(mapping_id: str, body: NewField, user: User = Depends(current_user)):
    try:
        return mapping_svc.add_field(mapping_id, body.target, user.name, body.sources, body.transform, body.default)
    except mapping_svc.MappingError as e:
        _err(e)


class Retarget(BaseModel):
    new_target: str


@app.post("/api/mappings/{mapping_id}/fields/{target}/retarget")
def retarget_mapping_field(mapping_id: str, target: str, body: Retarget, user: User = Depends(current_user)):
    try:
        return mapping_svc.retarget_field(mapping_id, target, body.new_target, user.name)
    except mapping_svc.MappingError as e:
        _err(e)


class SuggestReq(BaseModel):
    sources: list[str]
    target: str


@app.post("/api/mappings/{mapping_id}/suggest")
def suggest_mapping_pair(mapping_id: str, body: SuggestReq):
    """Confidence and a proposed transform for an analyst-chosen source -> target pair."""
    try:
        return mapping_svc.suggest_for(mapping_id, body.sources, body.target)
    except mapping_svc.MappingError as e:
        _err(e)


@app.get("/api/mappings/{mapping_id}/fields/{target}/values")
def field_values(mapping_id: str, target: str):
    """Distinct source values, what each becomes in SSE, and which are invalid (value-translation editor)."""
    try:
        return value_coverage(mapping_id, target)
    except ValueError as e:
        _err(e, 404)


class ValuesReq(BaseModel):
    value_map: dict[str, Any] = {}
    save: bool = False


@app.post("/api/mappings/{mapping_id}/fields/{target}/values")
def field_values_edit(mapping_id: str, target: str, body: ValuesReq, user: User = Depends(current_user)):
    """Preview (save=false) or save (save=true) a source-specific value map for this field."""
    try:
        m = mapping_svc.get_mapping(mapping_id)
    except mapping_svc.MappingError as e:
        _err(e, 404)
    f = next((x for x in m["fields"] if x["target"] == target), None)
    if not f:
        raise HTTPException(404, f"{target} is not mapped")
    from ..mapping.engine import LOOKUP_FOR_TARGET

    steps = with_value_map(f["transform"], body.value_map, LOOKUP_FOR_TARGET.get(target))
    if body.save:
        try:
            mapping_svc.update_field(mapping_id, target, "override", user.name, transform=steps)
        except mapping_svc.MappingError as e:
            _err(e)
    return {**value_coverage(mapping_id, target, transform=steps), "transform": steps, "saved": body.save}


@app.get("/api/mappings/{mapping_id}/diff")
def mapping_diff(mapping_id: str, against: str | None = None):
    try:
        return mapping_svc.diff_versions(mapping_id, against)
    except mapping_svc.MappingError as e:
        _err(e, 404)


@app.get("/api/mapping-memory")
def mapping_memory():
    return mapping_svc.memory_stats()


@app.post("/api/mappings/{mapping_id}/accept-all")
def accept_all(mapping_id: str, min_confidence: float = 0.8, user: User = Depends(current_user)):
    try:
        return {"accepted": mapping_svc.accept_all(mapping_id, user.name, min_confidence)}
    except mapping_svc.MappingError as e:
        _err(e)


@app.get("/api/mappings/{mapping_id}/preview")
def preview_mapping(mapping_id: str, n: int = 500):
    return mapping_svc.preview(mapping_id, n)


class TraceReq(BaseModel):
    sources: list[str] | None = None
    transform: list[dict] | None = None


@app.get("/api/mappings/{mapping_id}/fields/{target}/inspect")
def inspect_field(mapping_id: str, target: str, n: int = 500):
    """Transformation steps traced on sample rows + schema DQ checks + business rules reading this field."""
    try:
        return field_inspect(mapping_id, target, n)
    except ValueError as e:
        _err(e, 404)


@app.post("/api/mappings/{mapping_id}/fields/{target}/inspect")
def inspect_field_draft(mapping_id: str, target: str, body: TraceReq, n: int = 500):
    """Same, for an unsaved edit: test a transform chain before saving it."""
    try:
        return field_inspect(mapping_id, target, n, body.sources, body.transform)
    except ValueError as e:
        _err(e, 404)


@app.get("/api/mappings/{mapping_id}/dq")
def mapping_dq_rules(mapping_id: str, n: int = 500):
    return mapping_dq(mapping_id, n)


@app.post("/api/mappings/{mapping_id}/submit")
def submit_mapping(mapping_id: str, user: User = Depends(current_user)):
    try:
        return mapping_svc.submit(mapping_id, user.name)
    except mapping_svc.MappingError as e:
        _err(e)


class Decision(BaseModel):
    approve: bool = True
    comment: str | None = None


@app.post("/api/mappings/{mapping_id}/approve")
def approve_mapping(mapping_id: str, body: Decision, user: User = Depends(current_user)):
    try:
        return mapping_svc.approve(mapping_id, user.name, user.roles, body.approve, body.comment)
    except mapping_svc.MappingError as e:
        _err(e)


# ------------------------------------------------------------------ upload & batches (Workflow 2)
@app.post("/api/upload")
def upload(source_id: str = Form(...), file: UploadFile = File(...), auto_start: bool = Form(True),
           allow_duplicate: bool = Form(False), reason: str | None = Form(None), load_type: str | None = Form(None),
           user: User = Depends(current_user)):
    from ..storage import persist_upload

    local = _save_upload(file)
    try:
        digest = pipeline.file_sha256(local)
        # uploads/ (not incoming/): the API registers this batch itself, so the S3 arrival rule must not register it twice
        uri = persist_upload(local, f"{'uploads' if aws_mode() else 'incoming'}/{source_id}/{digest[:12]}")
        bid = pipeline.create_batch(source_id, uri, file.filename or local.name, user.name, allow_duplicate, reason, load_type or None)
    except pipeline.DuplicateFileError as e:
        raise HTTPException(409, {"message": str(e), "duplicate_of": e.batch_id}) from None
    except ValueError as e:
        _err(e)
    if auto_start:
        dispatch(bid)
    return {"batch_id": bid, "status": "submitted" if auto_start else "queued"}


@app.post("/api/upload/presign")
def presign(source_id: str, filename: str, user: User = Depends(current_user)):
    """AWS: browser PUTs straight to the raw S3 zone; EventBridge starts the Step Functions pipeline."""
    s = get_settings()
    if s.env != "aws" or not s.raw_bucket:
        raise HTTPException(400, "presigned upload is only available in AWS mode; use POST /api/upload locally")
    import boto3

    key = f"incoming/{source_id}/{uuid.uuid4().hex[:8]}_{Path(filename).name}"
    url = boto3.client("s3").generate_presigned_url("put_object", Params={"Bucket": s.raw_bucket, "Key": key,
                                                                         "Metadata": {"source-id": source_id, "submitted-by": user.name}},
                                                    ExpiresIn=900)
    return {"url": url, "bucket": s.raw_bucket, "key": key}


def _parse_batch_instant(raw: str, label: str):
    from datetime import UTC, datetime

    try:
        text = raw.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt  # treat bare naive as already-UTC platform time
        return dt.astimezone(UTC).replace(tzinfo=None)
    except ValueError as e:
        raise HTTPException(400, f"invalid {label}: {raw}") from e


@app.get("/api/batches")
def list_batches(limit: int = Query(50, ge=1, le=200), vendor_id: str | None = None,
                 status: str | None = None, days: int | None = None,
                 since: str | None = None, until: str | None = None, q: str | None = None):
    from datetime import timedelta

    statuses = [s.strip() for s in (status or "").split(",") if s.strip()] or None
    since_dt = until_dt = None
    if days is not None:
        if days not in (1, 7, 30):
            raise HTTPException(400, "days must be 1, 7, or 30")
        since_dt = db.now() - timedelta(days=days)
    if since:
        since_dt = _parse_batch_instant(since, "since")
    if until:
        until_dt = _parse_batch_instant(until, "until")
    if since_dt is not None and until_dt is not None and since_dt > until_dt:
        raise HTTPException(400, "since must be before until")
    return analytics.import_status(limit, _scope(vendor_id), statuses=statuses,
                                   since=since_dt, until=until_dt, q=q or None)


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str):
    items = [b for b in analytics.import_status(500)["batches"] if b["batch_id"] == batch_id]
    if not items:
        raise HTTPException(404, "batch not found")
    b = items[0]
    with db.get_engine().connect() as c:
        row = c.execute(select(db.batches.c.micro_batches).where(db.batches.c.batch_id == batch_id)).first()
    b["micro_batch_log"] = row[0] if row else []
    # List endpoint skips SF traces for terminal batches; detail always loads the one execution.
    if "pipeline" not in b:
        from ..pipeline.trace import fetch_traces

        trace = fetch_traces([batch_id]).get(batch_id)
        if trace:
            b["pipeline"] = trace
    return b


@app.post("/api/batches/{batch_id}/pause")
def pause_batch(batch_id: str, user: User = Depends(current_user)):
    pipeline.request_pause(batch_id, user.name)
    return {"batch_id": batch_id, "status": "pausing"}


@app.post("/api/batches/{batch_id}/resume")
def resume_batch(batch_id: str, user: User = Depends(current_user)):
    with db.get_engine().begin() as c:
        st = c.execute(select(db.batches.c.status).where(db.batches.c.batch_id == batch_id)).scalar()
        if st not in ("paused", "failed", "queued", "blocked", "waiting"):
            raise HTTPException(400, f"cannot resume a batch in status {st}")
        db.audit(c, user.name, "batch.resume", "batch", batch_id)
    dispatch(batch_id)
    return {"batch_id": batch_id, "status": "running"}


class Override(BaseModel):
    reason: str


@app.post("/api/batches/{batch_id}/override-preflight")
def override_preflight(batch_id: str, body: Override, user: User = Depends(current_user)):
    try:
        pipeline.override_preflight(batch_id, user.name, user.roles, body.reason)
    except ValueError as e:
        _err(e)
    dispatch(batch_id)
    return {"batch_id": batch_id, "status": "running"}


class Remap(BaseModel):
    renames: dict[str, str] = {}
    date_formats: dict[str, str] = {}


@app.post("/api/batches/{batch_id}/remap")
def remap_batch(batch_id: str, body: Remap, user: User = Depends(current_user)):
    """Turn the drift report into a draft mapping version (renames + date formats) for SME approval."""
    with db.get_engine().connect() as c:
        sid = c.execute(select(db.batches.c.source_id).where(db.batches.c.batch_id == batch_id)).scalar()
    if not sid:
        raise HTTPException(404, "batch not found")
    try:
        return mapping_svc.remap_from_drift(sid, body.renames, body.date_formats, user.name)
    except mapping_svc.MappingError as e:
        _err(e)


@app.post("/api/batches/{batch_id}/replay")
def replay(batch_id: str, dry_run: bool = True, user: User = Depends(current_user)):
    """Re-run held loans through the source's current mapping and rules (dry_run previews the outcome)."""
    from ..pipeline.replay import replay_batch

    if not dry_run and not set(user.roles) & {"monitoring", "onboarding_reviewer", "admin"}:
        raise HTTPException(403, "Monitoring or Onboarding reviewer role required to replay a batch")
    if not dry_run and aws_mode():
        run_id = start_glue(get_settings().glue_feed_job, {"mode": "replay", "batch_id": batch_id, "actor": user.name})
        with db.get_engine().begin() as c:
            db.audit(c, user.name, "batch.replay_submitted", "batch", batch_id, {"glue_run_id": run_id})
        return {"batch_id": batch_id, "dry_run": False, "submitted": True, "glue_run_id": run_id,
                "message": "Replay is running as a Glue job; the batch updates when it finishes."}
    try:
        return replay_batch(batch_id, user.name, dry_run)
    except ValueError as e:
        _err(e)


@app.get("/api/batches/{batch_id}/loans")
def batch_loans(batch_id: str, status: str | None = None, limit: int = 100, offset: int = 0):
    from ..ingestion.pii import TARGET_PII_TYPES, mask_record

    st = db.loans_staging
    q = select(st.c.id, st.c.row_number, st.c.loan_number, st.c.status, st.c.boarded, st.c.record).where(st.c.batch_id == batch_id)
    if status:
        q = q.where(st.c.status == status)
    with db.get_engine().connect() as c:
        rows = c.execute(q.order_by(st.c.row_number).limit(limit).offset(offset)).all()
    return {"items": [{"id": r.id, "row": r.row_number, "loan_number": r.loan_number, "status": r.status, "boarded": r.boarded,
                       "record": mask_record(r.record or {}, TARGET_PII_TYPES)} for r in rows]}


# ------------------------------------------------------------------ incremental loads & sequencing
class DeliveryProfileIn(BaseModel):
    load_type: str = "full"
    action: dict = {}
    blank_means: str = "no_change"
    clear_token: str | None = None
    sequence: dict = {}
    protected_fields: list[str] | None = None
    set_once_fields: list[str] | None = None
    snapshot: dict = {}


@app.get("/api/sources/{source_id}/delivery")
def get_delivery(source_id: str):
    from ..pipeline.delivery import DEFAULT_PROFILE, display_sequence, profile_of

    with db.get_engine().connect() as c:
        src = c.execute(select(db.sources).where(db.sources.c.source_id == source_id)).first()
    if not src:
        raise HTTPException(404, "source not found")
    return {"source_id": source_id, "delivery": profile_of(src.delivery), "configured": bool(src.delivery),
            "draft": src.delivery_draft, "proposed_by": src.delivery_proposed_by, "last_sequence": display_sequence(src.last_sequence),
            "defaults": DEFAULT_PROFILE, "columns": [col["name"] for col in (src.profile or {}).get("columns", [])],
            "action_values_seen": {col["name"]: col.get("top_values") or col.get("samples") or []
                                   for col in (src.profile or {}).get("columns", []) if not col.get("pii_type")}}


@app.put("/api/sources/{source_id}/delivery")
def put_delivery(source_id: str, body: DeliveryProfileIn, user: User = Depends(current_user)):
    from ..pipeline.delivery import DeliveryError, propose_profile

    prof = {k: v for k, v in body.model_dump().items() if v not in (None, {}, [])}
    try:
        return propose_profile(source_id, prof, user.name, user.roles)
    except DeliveryError as e:
        _err(e)


@app.post("/api/sources/{source_id}/delivery/approve")
def approve_delivery(source_id: str, body: Decision, user: User = Depends(current_user)):
    from ..pipeline.delivery import DeliveryError, decide_profile

    try:
        return decide_profile(source_id, user.name, user.roles, body.approve, body.comment)
    except DeliveryError as e:
        _err(e)


@app.get("/api/sources/{source_id}/delivery/test")
def test_filename(source_id: str, filename: str, draft: bool = False):
    """How a file named like this would be treated: load type, file-level action, sequence."""
    from ..pipeline.delivery import DeliveryError, display_sequence, extract_sequence, file_action, profile_of

    with db.get_engine().connect() as c:
        src = c.execute(select(db.sources).where(db.sources.c.source_id == source_id)).first()
    if not src:
        raise HTTPException(404, "source not found")
    prof = profile_of(src.delivery_draft if draft and src.delivery_draft else src.delivery)
    out = {"filename": filename, "load_type": prof["load_type"], "file_action": file_action(prof, filename)}
    try:
        seq = extract_sequence(prof, filename, None) if prof["sequence"].get("source") == "filename" else None
        out["sequence"] = display_sequence(seq)
        out["ok"] = True
        if prof["load_type"] == "incremental" and prof["action"].get("mode") == "filename" and not out["file_action"]:
            out.update(ok=False, error="no add/update/close pattern matches this name")
    except DeliveryError as e:
        out.update(ok=False, error=str(e))
    return out


class ReasonIn(BaseModel):
    reason: str


@app.get("/api/sources/{source_id}/config")
def feed_config(source_id: str):
    """What the data plane (Glue) will run for this feed: the current signed publication and its history."""
    from .. import config_store

    try:
        cur = config_store.load(source_id)
        current = {"version": cur.version, "sha256": cur.sha256, "published_at": cur.published_at, "mapping_id": cur.mapping_id,
                   "mapping_version": cur.mapping_version, "fields": len([f for f in cur.fields if f.get("status") != "rejected"]),
                   "rules": {k: len(v) for k, v in cur.runtime_set.items()}, "load_type": (cur.delivery or {}).get("load_type"),
                   "vendor_feeds": len(cur.vendor_feeds), "verified": True}
    except config_store.ConfigError as e:
        current = {"error": str(e), "verified": False}
    with db.get_engine().connect() as c:
        active = c.execute(select(db.sources.c.active_mapping_id).where(db.sources.c.source_id == source_id)).scalar()
    current["in_sync"] = current.get("mapping_id") == active if active else None
    return {"source_id": source_id, "current": current, "history": config_store.history(source_id)}


@app.post("/api/sources/{source_id}/publish")
def feed_publish(source_id: str, body: ReasonIn, user: User = Depends(current_user)):
    """Re-publish a feed's approved configuration (e.g. after a failed publication). Never publishes drafts."""
    from .. import config_store

    try:
        return config_store.publish(source_id, user.name, body.reason or "manual republish")
    except config_store.ConfigError as e:
        _err(e)


@app.post("/api/batches/{batch_id}/skip-gap")
def batch_skip_gap(batch_id: str, body: ReasonIn, user: User = Depends(current_user)):
    from ..pipeline import sequencing

    try:
        sequencing.skip_gap(batch_id, user.name, user.roles, body.reason)
    except sequencing.SequenceActionError as e:
        _err(e)
    dispatch(batch_id)
    return {"batch_id": batch_id, "status": "queued"}


@app.post("/api/batches/{batch_id}/apply-out-of-order")
def batch_apply_ooo(batch_id: str, body: ReasonIn, user: User = Depends(current_user)):
    from ..pipeline import sequencing

    try:
        sequencing.apply_out_of_order(batch_id, user.name, user.roles, body.reason)
    except sequencing.SequenceActionError as e:
        _err(e)
    dispatch(batch_id)
    return {"batch_id": batch_id, "status": "queued", "note": "every change in this file is held for dual control"}


@app.post("/api/batches/{batch_id}/discard")
def batch_discard(batch_id: str, body: ReasonIn, user: User = Depends(current_user)):
    from ..pipeline import sequencing

    try:
        released = sequencing.discard(batch_id, user.name, user.roles, body.reason)
    except sequencing.SequenceActionError as e:
        _err(e)
    for b in released:
        dispatch(b)
    return {"batch_id": batch_id, "status": "discarded", "released": released}


@app.post("/api/batches/{batch_id}/snapshot-reviews")
def batch_snapshot_reviews(batch_id: str, user: User = Depends(current_user)):
    """A snapshot flagged as truncated: after checking with the vendor, an SME raises the close reviews anyway."""
    from ..exceptions.manager import Triage
    from ..pipeline.delivery import profile_of

    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
        src = c.execute(select(db.sources).where(db.sources.c.source_id == b.source_id)).first() if b else None
    if not b or b.load_type != "snapshot" or b.status != "completed":
        raise HTTPException(400, "only a completed snapshot batch can raise close reviews")
    if not ((b.change_summary or {}).get("snapshot") or {}).get("truncation_suspected"):
        raise HTTPException(400, "close reviews were already raised for this snapshot")
    prof = profile_of(src.delivery)
    prof["snapshot"] = {**prof["snapshot"], "max_missing_pct": 100.0}
    out = pipeline.snapshot_missing(batch_id, b.source_id, prof, Triage())
    with db.get_engine().begin() as c:
        cs = {**(b.change_summary or {}), "snapshot": {**out, "raised_by": user.name}}
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(change_summary=cs))
        db.audit(c, user.name, "batch.snapshot_reviews_forced", "batch", batch_id, out)
    return out


@app.get("/api/batches/{batch_id}/changes")
def batch_changes(batch_id: str, action: str | None = None, limit: int = Query(200, le=1000), offset: int = 0):
    """What this file changed (applied) and what it is still holding (pending review)."""
    from ..pipeline.changes import masked_changes

    lc, st = db.loan_changes, db.loans_staging
    q = select(lc).where(lc.c.batch_id == batch_id)
    if action:
        q = q.where(lc.c.action == action)
    with db.get_engine().connect() as c:
        applied = c.execute(q.order_by(lc.c.id).limit(limit).offset(offset)).all()
        total = c.execute(select(func.count()).select_from(lc).where(lc.c.batch_id == batch_id)).scalar()
        held = c.execute(select(st.c.id, st.c.loan_number, st.c.action, st.c.changes, st.c.status).where(
            st.c.batch_id == batch_id, st.c.boarded.is_(False), st.c.action.in_(("update", "close", "close_inferred")),
            st.c.status.not_in(("REJECTED", "UNCHANGED"))).limit(limit)).all()
        by_action = dict(c.execute(select(lc.c.action, func.count()).where(lc.c.batch_id == batch_id).group_by(lc.c.action)).all())
    return {"total_applied": total, "by_action": by_action,
            "applied": [{**db.row_to_dict(r)} for r in applied],
            "held": [{"staging_id": h.id, "loan_number": h.loan_number, "action": h.action, "status": h.status,
                      "changes": masked_changes({k: v for k, v in (h.changes or {}).items() if isinstance(v, dict)})} for h in held]}


@app.get("/api/loans/{loan_number}/history")
def loan_history(loan_number: str):
    lc = db.loan_changes
    with db.get_engine().connect() as c:
        cur = c.execute(select(db.sse_loans.c.loan_number, db.sse_loans.c.lbp_status, db.sse_loans.c.lbp_version,
                               db.sse_loans.c.lbp_source_id, db.sse_loans.c.lbp_batch_id, db.sse_loans.c.lbp_boarded_at,
                               db.sse_loans.c.lbp_updated_at, db.sse_loans.c.lbp_closed_at, db.sse_loans.c.lbp_close_reason)
                        .where(db.sse_loans.c.loan_number == loan_number)).first()
        rows = c.execute(select(lc).where(lc.c.loan_number == loan_number).order_by(lc.c.id.desc()).limit(500)).all()
    if not cur and not rows:
        raise HTTPException(404, "loan not found")
    return {"loan": db.row_to_dict(cur) if cur else None, "history": [db.row_to_dict(r) for r in rows]}


# ------------------------------------------------------------------ vendor delivery scheduler
class ScheduleIn(BaseModel):
    source_id: str | None = None
    name: str = "Delivery"
    config: dict


class StatusIn(BaseModel):
    status: str
    reason: str | None = None


def _sched_call(fn, *a, **kw):
    from ..scheduling.service import ScheduleError

    try:
        return fn(*a, **kw)
    except ScheduleError as e:
        _err(e)


@app.get("/api/schedules")
def schedules_list(source_id: str | None = None, vendor_id: str | None = None):
    from ..scheduling import service as sched

    return {"schedules": sched.list_schedules(source_id, _scope(vendor_id))}


@app.post("/api/schedules")
def schedules_create(body: ScheduleIn, user: User = Depends(current_user)):
    from ..scheduling import service as sched

    if not body.source_id:
        raise HTTPException(400, "source_id is required")
    return _sched_call(sched.create_schedule, body.source_id, body.name, body.config, user.name, user.roles)


@app.put("/api/schedules/{schedule_id}")
def schedules_update(schedule_id: str, body: ScheduleIn, user: User = Depends(current_user)):
    from ..scheduling import service as sched

    return _sched_call(sched.propose_change, schedule_id, body.config, user.name, user.roles, body.name)


@app.post("/api/schedules/{schedule_id}/approve")
def schedules_approve(schedule_id: str, body: Decision, user: User = Depends(current_user)):
    from ..scheduling import service as sched

    return _sched_call(sched.decide, schedule_id, user.name, user.roles, body.approve, body.comment)


@app.post("/api/schedules/{schedule_id}/status")
def schedules_status(schedule_id: str, body: StatusIn, user: User = Depends(current_user)):
    from ..scheduling import service as sched

    return _sched_call(sched.set_status, schedule_id, user.name, user.roles, body.status, body.reason)


@app.post("/api/schedules/{schedule_id}/pull-now")
def schedules_pull(schedule_id: str, user: User = Depends(current_user)):
    from ..scheduling import service as sched

    if aws_mode():
        if not set(user.roles) & {"monitoring", "onboarding_reviewer", "admin"}:
            raise HTTPException(403, "requires one of: monitoring, onboarding_reviewer")
        run_id = start_glue(get_settings().glue_pull_job, {"schedule_id": schedule_id})
        with db.get_engine().begin() as c:
            db.audit(c, user.name, "schedule.pull_submitted", "schedule", schedule_id, {"glue_run_id": run_id})
        return {"schedule_id": schedule_id, "submitted": True, "glue_run_id": run_id, "fetched": [], "batches": []}
    out = _sched_call(sched.pull_now, schedule_id, user.name, user.roles)
    for bid in out.get("batches", []):
        dispatch(bid)
    return out


@app.get("/api/schedules/preview")
def schedules_preview(cron: str, timezone: str = "America/New_York", calendar: str = "us_federal", holiday_rule: str = "skip",
                      n: int = Query(8, le=30)):
    from ..scheduling import service as sched

    return sched.preview({"cron": cron, "timezone": timezone, "calendar": calendar, "holiday_rule": holiday_rule}, n)


@app.get("/api/deliveries")
def deliveries_list(days_back: int = Query(7, le=90), days_ahead: int = Query(2, le=30), source_id: str | None = None,
                    status: str | None = None, vendor_id: str | None = None):
    from datetime import timedelta

    from ..scheduling import service as sched

    now = db.now()
    return {"now": now.isoformat() + "Z", "deliveries": sched.list_deliveries(now - timedelta(days=days_back), now + timedelta(days=days_ahead),
                                                                              source_id, status, source_ids=_scope(vendor_id))}


@app.post("/api/deliveries/{delivery_id}/waive")
def deliveries_waive(delivery_id: str, body: ReasonIn, user: User = Depends(current_user)):
    from ..scheduling import service as sched

    return _sched_call(sched.waive, delivery_id, user.name, user.roles, body.reason)


@app.post("/api/scheduler/tick")
def scheduler_tick(user: User = Depends(current_user)):
    from ..scheduling import service as sched

    out = sched.tick()
    for bid in out.get("batches", []):
        dispatch(bid)
    return out


@app.get("/api/analytics/vendors")
def analytics_vendors(vendor_id: str | None = None):
    """Feeds (with their vendor) for delivery freshness, plus a per-vendor roll-up."""
    from .. import vendors as vendor_svc
    from ..scheduling import service as sched

    rolled = [v for v in vendor_svc.list_vendors() if not vendor_id or v["vendor_id"] == vendor_id]
    return {"vendors": sched.vendor_freshness(_scope(vendor_id)), "by_vendor": rolled}


# ------------------------------------------------------------------ exceptions (Pillar 3.B)
@app.get("/api/exceptions")
def list_exceptions(status: str | None = "open", tier: str | None = None, queue: str | None = None, batch_id: str | None = None,
                    rule_id: str | None = None, source_id: str | None = None, q: str | None = None,
                    loaded_on: str | None = None, limit: int = Query(100, le=1000), offset: int = 0, vendor_id: str | None = None):
    return exceptions_mgr.list(status, tier, queue, batch_id, rule_id, source_id, q, limit, offset, _scope(vendor_id), loaded_on)


@app.get("/api/exceptions/loads")
def exceptions_loads(status: str | None = "open", vendor_id: str | None = None):
    """File loads that have exceptions — for vendor / file / date filters."""
    return exceptions_mgr.loads(status, _scope(vendor_id), vendor_id)


@app.get("/api/exceptions/summary")
def exceptions_summary(vendor_id: str | None = None):
    e = db.exceptions
    ids = _scope(vendor_id)
    with db.get_engine().connect() as c:
        q = select(e.c.tier, e.c.status, func.count())
        if ids is not None:
            q = q.where(e.c.source_id.in_(ids or ["-"]))
        rows = c.execute(q.group_by(e.c.tier, e.c.status)).all()
    out = {t: {"label": TIER_LABELS[t], "open": 0, "pending_checker": 0, "resolved": 0, "auto_applied": 0, "escalated": 0, "total": 0}
           for t in TIER_LABELS}
    for tier, status, n in rows:
        if tier in out:
            out[tier]["total"] += n
            key = "open" if status in ("open", "pending_review") else status
            out[tier][key] = out[tier].get(key, 0) + n
    return {"tiers": out}


@app.get("/api/exceptions/{exception_id}")
def get_exception(exception_id: str, user: User = Depends(current_user)):
    try:
        return exceptions_mgr.get(exception_id, user.roles)
    except ExceptionActionError as e:
        _err(e, 404)


class Resolve(BaseModel):
    value: Any = None
    use_proposal: bool = False
    comment: str | None = None


@app.post("/api/exceptions/{exception_id}/resolve")
def resolve_exception(exception_id: str, body: Resolve, user: User = Depends(current_user)):
    try:
        return exceptions_mgr.resolve(exception_id, user.name, user.roles, body.value, body.use_proposal, body.comment)
    except ExceptionActionError as e:
        _err(e)


@app.post("/api/exceptions/{exception_id}/checker")
def checker(exception_id: str, body: Decision, user: User = Depends(current_user)):
    try:
        return exceptions_mgr.checker_decision(exception_id, user.name, user.roles, body.approve, body.comment)
    except ExceptionActionError as e:
        _err(e)


class Reason(BaseModel):
    reason: str = ""
    value: Any = None


@app.post("/api/exceptions/{exception_id}/reject")
def reject(exception_id: str, body: Reason, user: User = Depends(current_user)):
    try:
        return exceptions_mgr.reject_loan(exception_id, user.name, user.roles, body.reason)
    except ExceptionActionError as e:
        _err(e)


@app.post("/api/exceptions/{exception_id}/escalate")
def escalate(exception_id: str, body: Reason, user: User = Depends(current_user)):
    return exceptions_mgr.escalate(exception_id, user.name, user.roles, body.reason)


@app.post("/api/exceptions/{exception_id}/compliance-clear")
def compliance_clear(exception_id: str, body: Reason, user: User = Depends(current_user)):
    try:
        return exceptions_mgr.compliance_clear(exception_id, user.name, user.roles, body.value, body.reason)
    except ExceptionActionError as e:
        _err(e)


@app.post("/api/exceptions/{exception_id}/rollback")
def rollback(exception_id: str, body: Reason, user: User = Depends(current_user)):
    try:
        return exceptions_mgr.rollback(exception_id, user.name, user.roles, body.reason)
    except ExceptionActionError as e:
        _err(e)


class QA(BaseModel):
    correct: bool
    comment: str | None = None


@app.post("/api/exceptions/{exception_id}/qa")
def qa(exception_id: str, body: QA, user: User = Depends(current_user)):
    try:
        return exceptions_mgr.qa_review(exception_id, user.name, user.roles, body.correct, body.comment)
    except ExceptionActionError as e:
        _err(e)


@app.post("/api/exceptions/{exception_id}/ai-suggest")
def ai_suggest(exception_id: str):
    try:
        return exceptions_mgr.ai_suggest(exception_id)
    except ExceptionActionError as e:
        _err(e)


class Bulk(BaseModel):
    rule_id: str
    original_value: Any = None
    value: Any = None
    use_proposal: bool = False
    batch_id: str | None = None


@app.post("/api/exceptions/bulk-resolve")
def bulk_resolve(body: Bulk, user: User = Depends(current_user)):
    return exceptions_mgr.bulk_resolve(user.name, user.roles, body.rule_id, body.original_value, body.value, body.use_proposal, body.batch_id)


# ------------------------------------------------------------------ notifications (in-app review inbox)
@app.get("/api/notifications")
def list_notifications(unread: bool = False, user: User = Depends(current_user)):
    from .. import notifications as ntf

    items = ntf.list_for(user.name, unread_only=unread)
    return {"notifications": items, "unread": ntf.unread_count(user.name)}


@app.post("/api/notifications/{notif_id}/read")
def read_notification(notif_id: str, user: User = Depends(current_user)):
    from .. import notifications as ntf

    row = ntf.mark_read(notif_id, user.name)
    if not row:
        raise HTTPException(404, "notification not found")
    return row


@app.post("/api/notifications/read-all")
def read_all_notifications(user: User = Depends(current_user)):
    from .. import notifications as ntf

    return {"ok": True, "updated": ntf.mark_all_read(user.name)}


# ------------------------------------------------------------------ rules (Pillar 3.A)
@app.get("/api/rules")
def list_rules(status: str | None = None, queue: str | None = None, user: User = Depends(current_user)):
    """queue=awaiting_review → in_review where caller is not the author; queue=my_drafts → drafts by caller."""
    rules = registry.list(status)
    if queue == "awaiting_review":
        rules = [r for r in rules if r.get("status") == "in_review" and r.get("author") != user.name]
    elif queue == "my_drafts":
        rules = [r for r in rules if r.get("status") == "draft" and r.get("author") == user.name]
    latest: dict[str, dict] = {}
    for r in rules:
        cur = latest.get(r["rule_id"])
        if cur is None or r["status"] in ("active",) or (cur["status"] not in ("active",) and r["version"] > cur["version"]):
            latest[r["rule_id"]] = r
    e = db.exceptions
    with db.get_engine().connect() as c:
        counts = dict(c.execute(select(e.c.rule_id, func.count()).group_by(e.c.rule_id)).all())
    return {"rules": [{**r, "exception_count": counts.get(r["rule_id"], 0),
                       "versions": sorted({x["version"]: x["status"] for x in rules if x["rule_id"] == r["rule_id"]}.items())}
                      for r in sorted(latest.values(), key=lambda x: x["rule_id"])]}


@app.get("/api/rules/fields")
def list_rule_fields():
    return {"fields": fields_payload()}


@app.get("/api/rules/shapes")
def list_rule_shapes():
    return {"shapes": shape_catalog(), "pattern_presets": pattern_presets()}


@app.get("/api/rules/templates")
def list_rule_templates():
    return {"templates": rule_tpl.list_templates(include_hidden=False)}


class ComposeReq(BaseModel):
    tree: Any
    name: str | None = None
    severity: str = "FAIL"
    regulatory_tag: str | None = None


@app.post("/api/rules/compose")
def compose_rule(body: ComposeReq):
    try:
        compiled = compile_tree(body.tree)
    except ShapeError as e:
        raise HTTPException(400, str(e)) from e
    results = run_tests({"expression": compiled["expression"], "tests": compiled["tests"]})
    return {
        "draft": {
            **compiled,
            "name": body.name or compiled["summary"],
            "description": compiled["summary"],
            "severity": body.severity,
            "regulatory_tag": body.regulatory_tag,
        },
        "test_results": results,
        "problems": [f"test {r['case']} failed" for r in results if not r["passed"]],
        "summary": compiled["summary"],
    }


def _materialize_rule(data: dict) -> dict:
    """Prefer tree → expression; keep legacy expression path."""
    if data.get("tree"):
        try:
            compiled = compile_tree(data["tree"])
        except ShapeError as e:
            raise HTTPException(400, str(e)) from e
        data = {
            **data,
            **compiled,
            "description": data.get("description") or compiled.get("summary") or "",
            "name": data.get("name") or compiled.get("summary") or "Rule",
            "category": data.get("category") or compiled.get("category") or "custom",
        }
    elif data.get("expression") is None:
        raise HTTPException(400, "Provide a guided rule (tree) or an expression")
    if not data.get("field") and data.get("expression"):
        raise HTTPException(400, "field is required when expression is provided without a tree")
    return data


@app.get("/api/rules/{rule_id}")
def get_rule(rule_id: str):
    vs = registry.versions(rule_id)
    if not vs:
        raise HTTPException(404, "rule not found")
    return {"rule_id": rule_id, "versions": vs}


class RuleBody(BaseModel):
    rule_id: str | None = None
    name: str
    description: str = ""
    expression: Any | None = None
    tree: Any | None = None
    field: str | None = None
    severity: str = "FAIL"
    category: str = "custom"
    regulatory_tag: str | None = None
    tests: list[dict] = []
    message: str | None = None


@app.post("/api/rules")
def create_rule(body: RuleBody, user: User = Depends(current_user)):
    try:
        data = _materialize_rule(body.model_dump(exclude_none=True))
        return registry.create_draft(data, user.name)
    except RuleError as e:
        _err(e)


@app.put("/api/rules/{rule_id}/{version}")
def edit_rule(rule_id: str, version: int, changes: dict, user: User = Depends(current_user)):
    try:
        if changes.get("tree"):
            changes = _materialize_rule({**changes, "name": changes.get("name") or "Rule"})
        return registry.update_draft(rule_id, version, changes, user.name)
    except RuleError as e:
        _err(e)


class Transition(BaseModel):
    to: str
    comment: str | None = None
    canary_pct: int | None = None


@app.post("/api/rules/{rule_id}/{version}/transition")
def transition_rule(rule_id: str, version: int, body: Transition, user: User = Depends(current_user)):
    try:
        return registry.transition(rule_id, version, body.to, user.name, user.roles, body.comment, body.canary_pct)
    except RuleError as e:
        _err(e)


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: str, reason: str | None = None, user: User = Depends(current_user)):
    try:
        return registry.delete_rule(rule_id, user.name, reason)
    except RuleError as e:
        _err(e, 404 if "not found" in str(e).lower() else 400)


class AuthorReq(BaseModel):
    text: str


@app.post("/api/rules/author")
def author_rule(body: AuthorReq):
    out = draft_from_text(body.text)
    draft = out.get("draft")
    if draft and draft.get("expression") and not draft.get("tree"):
        tree = decompile(draft["expression"])
        if tree:
            draft["tree"] = tree
            draft["summary"] = draft.get("description") or draft.get("name")
    return out


class TestReq(BaseModel):
    expression: Any | None = None
    tree: Any | None = None
    record: dict | None = None
    tests: list[dict] | None = None


@app.post("/api/rules/test")
def test_rule(body: TestReq):
    expression = body.expression
    if body.tree is not None:
        try:
            expression = compile_tree(body.tree)["expression"]
        except ShapeError as e:
            return {"valid": False, "problems": [str(e)]}
    if expression is None:
        return {"valid": False, "problems": ["tree or expression required"]}
    problems = jl_validate(expression)
    if problems:
        return {"valid": False, "problems": problems}
    out: dict = {"valid": True, "expression": expression}
    if body.record is not None:
        out["result"] = bool(jl_apply(expression, body.record))
    if body.tests:
        out["tests"] = run_tests({"expression": expression, "tests": body.tests})
    return out


@app.get("/api/rules/{rule_id}/impact")
def rule_impact(rule_id: str, version: int | None = None, sample: int = 5000):
    """Shadow-style impact estimate: how many recently staged loans would this version fail?"""
    from ..rules.jsonlogic import compile_logic

    body = registry.get(rule_id, version)
    if not body:
        raise HTTPException(404, "rule not found")
    fn = compile_logic(body["expression"])
    with db.get_engine().connect() as c:
        recs = [r[0] for r in c.execute(select(db.loans_staging.c.record).order_by(db.loans_staging.c.id.desc()).limit(sample))]
    fails = sum(1 for r in recs if not fn(r or {}))
    return {"rule_id": rule_id, "version": body["version"], "sampled": len(recs), "would_fail": fails,
            "fail_rate_pct": round(fails / len(recs) * 100, 2) if recs else 0}


# ------------------------------------------------------------------ policy
@app.get("/api/policy")
def read_policy():
    from ..exceptions.policy import effective_policy

    eff = effective_policy()
    return {"policy": get_policy(), "effective": {k: eff[k] for k in ("t1_effective", "t1_auto_suspended", "t1_health")},
            "defaults": DEFAULT_POLICY, "tiers": TIER_LABELS}


class PolicyChange(BaseModel):
    changes: dict
    requested_by: str
    reason: str | None = None


@app.put("/api/policy")
def update_policy(body: PolicyChange, user: User = Depends(current_user)):
    """Called by the Compliance approver; requested_by is the analyst who proposed the change."""
    try:
        return {"policy": set_policy(body.changes, body.requested_by, user.name, user.roles, reason=body.reason)}
    except PolicyError as e:
        _err(e)


# ------------------------------------------------------------------ analytics (Pillar 2)
@app.get("/api/analytics/import-status")
def a_import(limit: int = 25, vendor_id: str | None = None):
    return analytics.import_status(min(max(limit, 1), 500), _scope(vendor_id))


@app.get("/api/analytics/exceptions")
def a_exceptions(days: int = 30, vendor_id: str | None = None):
    return analytics.exception_analytics(days, _scope(vendor_id))


@app.get("/api/analytics/dq-scorecard")
def a_dq(vendor_id: str | None = None):
    return analytics.dq_scorecard(source_ids=_scope(vendor_id))


@app.get("/api/analytics/source-performance")
def a_sources(vendor_id: str | None = None):
    return analytics.source_performance(_scope(vendor_id))


@app.get("/api/analytics/ai-mapping")
def a_ai(vendor_id: str | None = None):
    return analytics.ai_mapping_insights(_scope(vendor_id))


@app.get("/api/analytics/systemic")
def a_systemic(vendor_id: str | None = None):
    return analytics.systemic_issues(source_ids=_scope(vendor_id))


@app.get("/api/analytics/executive")
def a_exec(vendor_id: str | None = None):
    return analytics.executive_summary(_scope(vendor_id))


class Ask(BaseModel):
    question: str


@app.post("/api/analytics/ask")
def a_ask(body: Ask):
    return analytics.ask(body.question)


# ------------------------------------------------------------------ audit
@app.get("/api/audit")
def audit(entity_id: str | None = None, action: str | None = None, limit: int = 200):
    a = db.audit_log
    q = select(a).order_by(a.c.ts.desc()).limit(limit)
    if entity_id:
        q = q.where(a.c.entity_id == entity_id)
    if action:
        q = q.where(a.c.action.like(f"{action}%"))
    with db.get_engine().connect() as c:
        return {"items": [db.row_to_dict(r) for r in c.execute(q)]}


@app.get("/api/audit/verify")
def audit_verify():
    """Recompute the audit hash chain; any edited, deleted or re-ordered entry breaks it."""
    return db.verify_audit_chain()


class Purge(BaseModel):
    older_than_days: int | None = None


@app.post("/api/admin/retention/purge")
def retention_purge(body: Purge, user: User = Depends(current_user)):
    """GLBA data minimisation: drop raw source rows and mask NPI in staging for boarded loans past retention."""
    from ..pipeline.retention import purge_staging_npi

    return purge_staging_npi(body.older_than_days or get_settings().staging_pii_retention_days, user.name)


# ------------------------------------------------------------------ demo seed / kit setup
class DemoSetupIn(BaseModel):
    force: bool = False
    scale: str = "compact"


@app.post("/api/demo/seed")
def demo_seed(rows_per_source: int = 2000, user: User = Depends(current_user)):
    """Generates the four sample sources, onboards them (analyst + SME) and boards a file from each."""
    if not get_settings().enable_demo:
        raise HTTPException(404, "not found")
    out_dir = get_settings().data_dir / "samples"
    files = samples.generate_all(out_dir, rows_per_source)
    results = []
    for key, path in files.items():
        label = samples.SOURCES[key][0]
        reg = mapping_svc.register_source(label, path, "onboarding", f"Synthetic {label} loan tape")
        mapping_svc.accept_all(reg["mapping_id"], "onboarding", 0.0)
        mapping_svc.submit(reg["mapping_id"], "onboarding")
        mapping_svc.approve(reg["mapping_id"], "onboarding.reviewer", ["onboarding_reviewer"], True, "Demo approval")
        bid = pipeline.create_batch(reg["source_id"], path, path.name, user.name)
        results.append(pipeline.run_batch(bid))
    return {"seeded": results}


@app.post("/api/demo/setup")
def demo_setup(body: DemoSetupIn, user: User = Depends(current_user)):
    """Load the demo-kit sales scenario (vendors, schedules, exceptions). Admin + enable_demo only."""
    if not get_settings().enable_demo:
        raise HTTPException(404, "not found")
    from ..demo_setup import DemoSetupConflict, ROWS, run_demo_setup

    if body.scale not in ROWS:
        raise HTTPException(400, f"scale must be one of {list(ROWS)}")
    try:
        return run_demo_setup(scale=body.scale, force=body.force).to_dict()
    except DemoSetupConflict as e:
        raise HTTPException(409, {"code": "demo_data_exists", "message": str(e),
                                  "hint": "pass force=true after confirm"}) from e


# ------------------------------------------------------------------ maintenance (Glue artifacts + rule templates)
@app.get("/api/maintenance/artifacts")
def maintenance_artifacts():
    from ..maintenance import list_artifacts

    return {"artifacts": list_artifacts()}


@app.get("/api/maintenance/artifacts/{artifact_id}")
def maintenance_artifact(artifact_id: str):
    from ..maintenance import MaintenanceError, get_artifact

    try:
        return get_artifact(artifact_id)
    except MaintenanceError as e:
        raise HTTPException(404, str(e)) from None


@app.get("/api/maintenance/rule-templates")
def maintenance_rule_templates():
    return {"templates": rule_tpl.list_templates(include_hidden=True)}


class RuleTemplateBody(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    tree: Any


@app.post("/api/maintenance/rule-templates")
def maintenance_create_rule_template(body: RuleTemplateBody, user: User = Depends(current_user)):
    try:
        return rule_tpl.create_template(body.model_dump(exclude_none=True), user.name)
    except rule_tpl.TemplateError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/maintenance/rule-templates/{template_id}")
def maintenance_update_rule_template(template_id: str, body: dict, user: User = Depends(current_user)):
    try:
        return rule_tpl.update_template(template_id, body, user.name)
    except rule_tpl.TemplateError as e:
        raise HTTPException(400 if "not found" not in str(e).lower() else 404, str(e)) from e


@app.post("/api/maintenance/rule-templates/{template_id}/hide")
def maintenance_hide_rule_template(template_id: str, user: User = Depends(current_user)):
    try:
        return rule_tpl.set_hidden(template_id, True, user.name)
    except rule_tpl.TemplateError as e:
        raise HTTPException(404, str(e)) from e


@app.post("/api/maintenance/rule-templates/{template_id}/unhide")
def maintenance_unhide_rule_template(template_id: str, user: User = Depends(current_user)):
    try:
        return rule_tpl.set_hidden(template_id, False, user.name)
    except rule_tpl.TemplateError as e:
        raise HTTPException(404, str(e)) from e


@app.delete("/api/maintenance/rule-templates/{template_id}")
def maintenance_delete_rule_template(template_id: str, user: User = Depends(current_user)):
    try:
        rule_tpl.delete_template(template_id, user.name)
        return {"ok": True, "id": template_id}
    except rule_tpl.TemplateError as e:
        code = 400 if "built-in" in str(e).lower() else 404
        raise HTTPException(code, str(e)) from e


# ------------------------------------------------------------------ personas (user admin + restrict-only screen nav matrix)
@app.get("/api/personas/me/screens")
def personas_my_screens(user: User = Depends(current_user)):
    from ..personas import visible_screens

    return {"screens": visible_screens(user.roles)}


@app.get("/api/personas/cast")
def personas_cast():
    """Signed-in-as switcher people (local demo cast + enabled directory). Open to any auth user."""
    from ..personas import cast_for_switcher

    return {"cast": cast_for_switcher()}


@app.get("/api/personas/screens")
def personas_screens():
    from ..personas import screens_payload

    return screens_payload()


class ScreenMatrixIn(BaseModel):
    matrix: dict[str, list[str]]


@app.put("/api/personas/screens")
def personas_screens_put(body: ScreenMatrixIn, user: User = Depends(current_user)):
    from ..personas import PersonaError, screens_payload, set_screen_matrix

    try:
        set_screen_matrix(body.matrix, actor=user.name)
        return screens_payload()
    except PersonaError as e:
        raise HTTPException(400, str(e)) from None


@app.get("/api/personas/users")
def personas_users():
    from ..personas import list_users

    return {"users": list_users()}


class PersonaUserIn(BaseModel):
    email: str
    role: str
    temporary_password: str


@app.post("/api/personas/users")
def personas_users_create(body: PersonaUserIn, user: User = Depends(current_user)):
    from ..personas import PersonaError, create_user

    try:
        return {"user": create_user(email=body.email, role=body.role, actor=user.name,
                                    temporary_password=body.temporary_password)}
    except PersonaError as e:
        raise HTTPException(400, str(e)) from None


class PersonaUserPatch(BaseModel):
    role: str | None = None
    enabled: bool | None = None


@app.put("/api/personas/users/{username}")
def personas_users_update(username: str, body: PersonaUserPatch, user: User = Depends(current_user)):
    from ..personas import PersonaError, set_user

    try:
        return {"user": set_user(username, actor=user.name, role=body.role, enabled=body.enabled)}
    except PersonaError as e:
        raise HTTPException(400, str(e)) from None


class PersonaResetIn(BaseModel):
    temporary_password: str


@app.post("/api/personas/users/{username}/reset-password")
def personas_users_reset(username: str, body: PersonaResetIn, user: User = Depends(current_user)):
    from ..personas import PersonaError, reset_password

    try:
        return reset_password(username, temporary_password=body.temporary_password, actor=user.name)
    except PersonaError as e:
        raise HTTPException(400, str(e)) from None


# ------------------------------------------------------------------ static web app
_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _dist / path
        return FileResponse(f if f.is_file() else _dist / "index.html")
