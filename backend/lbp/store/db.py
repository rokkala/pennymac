"""Relational store (SQLAlchemy Core).

Local: SQLite. AWS: RDS SQL Server (the SSE database itself) or Aurora PostgreSQL for the
platform tables - set LBP_DATABASE_URL. The `sse_loans` table is generated from the SSE
target schema so the loader writes real typed columns, mirroring the SSE staging tables.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from ..config import get_settings
from ..schema.sse_target import ATTRIBUTES

metadata = MetaData()


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    # Full uuid4 hex — [:12] birthday-collides under parallel 10M exception inserts.
    return f"{prefix}_{uuid.uuid4().hex}"


# A vendor (seller, correspondent, sub-servicer, bulk seller, internal channel) owns one or more feeds.
# Each feed (a `source`) has its own file format, mapping versions, delivery profile and schedules.
vendors = Table(
    "vendors", metadata,
    Column("vendor_id", String(40), primary_key=True),
    Column("name", String(120), nullable=False, unique=True),
    Column("vendor_type", String(20)),   # correspondent | bulk_seller | sub_servicer | retail | other
    Column("legal_name", String(200)),
    Column("external_ref", String(60)),  # PennyMac's counterparty / seller number
    Column("contact", JSON),             # business contact for delivery issues (name, email, phone)
    Column("status", String(20), default="onboarding"),  # onboarding | active | suspended | offboarded
    Column("notes", Text),
    Column("created_by", String(80)),
    Column("created_at", DateTime, default=now),
    Column("updated_at", DateTime),
)

sources = Table(
    "sources", metadata,
    Column("source_id", String(40), primary_key=True),
    Column("vendor_id", String(40), index=True),
    Column("name", String(120), nullable=False),
    Column("description", Text),
    Column("format", String(10)),
    Column("parse_options", JSON),
    Column("profile", JSON),
    Column("sample_file", String(500)),
    Column("status", String(20), default="draft"),  # draft | mapping | live | retired
    Column("active_mapping_id", String(40)),
    # How this vendor delivers: full tapes, incremental change files or full snapshots (see pipeline/delivery.py)
    Column("delivery", JSON),
    Column("delivery_draft", JSON),        # proposed change awaiting a second approver
    Column("delivery_proposed_by", String(80)),
    Column("last_sequence", String(40)),   # highest file sequence applied (per-vendor ordering cursor)
    Column("seq_lock_at", DateTime),       # write-first row lock that serialises the sequencing gate
    Column("created_by", String(80)),
    Column("created_at", DateTime, default=now),
)

mappings = Table(
    "mappings", metadata,
    Column("mapping_id", String(40), primary_key=True),
    Column("source_id", String(40), index=True),
    Column("version", Integer, default=1),
    Column("status", String(20), default="draft"),  # draft | in_review | approved | superseded | rejected
    Column("fields", JSON),
    Column("stats", JSON),
    Column("created_by", String(80)),
    Column("reviewed_by", String(80)),
    Column("approved_by", String(80)),
    Column("comments", JSON),
    Column("created_at", DateTime, default=now),
    Column("approved_at", DateTime),
)

batches = Table(
    "batches", metadata,
    Column("batch_id", String(40), primary_key=True),
    Column("source_id", String(40), index=True),
    Column("mapping_id", String(40)),
    Column("filename", String(300)),
    Column("file_path", String(500)),
    Column("status", String(20), default="queued"),  # queued | claimed | running | staged | paused | completed | failed | blocked
    Column("total_rows", Integer, default=0),
    Column("processed", Integer, default=0),
    Column("passed", Integer, default=0),
    Column("warned", Integer, default=0),
    Column("failed", Integer, default=0),
    Column("loaded", Integer, default=0),
    Column("checkpoint", Integer, default=0),
    Column("micro_batches", JSON),
    Column("reconciliation", JSON),
    Column("file_sha256", String(64), index=True),
    Column("heartbeat_at", DateTime),  # liveness of the worker holding the batch lease
    Column("worker_id", String(80)),
    Column("preflight", JSON),  # schema-drift check result (+ override)
    Column("replays", JSON),    # history of replays of held loans
    Column("load_type", String(12), default="full"),  # full | incremental | snapshot
    Column("sequence", String(40), index=True),        # sortable: zero-padded integer or ISO date
    Column("sequence_detail", JSON),                    # gate decision, overrides
    Column("change_summary", JSON),                     # adds / updates / closes / unchanged / conflicts
    Column("delivery_id", String(40), index=True),      # scheduled delivery this file satisfied
    Column("throughput_lps", Float, default=0.0),
    Column("error", Text),
    Column("submitted_by", String(80)),
    Column("created_at", DateTime, default=now),
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
)

loans_staging = Table(
    "loans_staging", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("batch_id", String(40), index=True),
    Column("row_number", Integer),
    Column("loan_number", String(40), index=True),
    Column("status", String(10)),  # PASS | WARN | FAIL
    Column("record", JSON),
    Column("raw", JSON(none_as_null=True)),
    Column("transform_errors", JSON),
    Column("boarded", Boolean, default=False),
    Column("action", String(16)),        # add | update | close | close_inferred | unchanged (incremental only)
    Column("changes", JSON(none_as_null=True)),  # {field: {"old": v, "new": v}} vs the SSE record it was based on
    Column("base_version", Integer),     # sse_loans.lbp_version the delta was computed against
    Column("updated_at", DateTime, default=now),
)

_TYPE = {"string": lambda a: String(a.length or 255), "code": lambda a: String(a.length or 10), "int": lambda a: Integer(),
         # money and rates: exact decimal storage in SSE (floats are never written to money columns)
         "decimal": lambda a: Numeric(20, 6, asdecimal=False), "date": lambda a: Date(), "bool": lambda a: Boolean()}

sse_loans = Table(
    "sse_loans", metadata,
    Column("loan_number", String(40), primary_key=True),
    *[Column(a.name, _TYPE[a.dtype](a)) for a in ATTRIBUTES if a.name != "loan_number"],
    Column("lbp_batch_id", String(40), index=True),
    Column("lbp_boarded_at", DateTime, default=now),
    Column("lbp_dq_status", String(10)),
    Column("lbp_source_id", String(40), index=True),   # owning vendor (snapshot diffs, freshness)
    Column("lbp_status", String(10), default="active"),  # active | closed
    Column("lbp_version", Integer, default=1),          # optimistic concurrency for incremental updates
    Column("lbp_updated_at", DateTime),
    Column("lbp_closed_at", DateTime),
    Column("lbp_close_reason", String(60)),
)

# Every change applied to (or held against) a boarded loan. NPI values are masked; a fingerprint proves the change.
loan_changes = Table(
    "loan_changes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("batch_id", String(40), index=True),
    Column("source_id", String(40), index=True),
    Column("loan_number", String(40), index=True),
    Column("staging_id", Integer, index=True),
    Column("action", String(16)),
    Column("changes", JSON),
    Column("base_version", Integer),
    Column("applied_version", Integer),
    Column("status", String(12), index=True),  # applied | held | conflict | rejected
    Column("actor", String(80)),
    Column("created_at", DateTime, default=now),
)

# Vendor delivery calendar: when a file is due, and (optionally) where to pull it from.
delivery_schedules = Table(
    "delivery_schedules", metadata,
    Column("schedule_id", String(40), primary_key=True),
    Column("source_id", String(40), index=True),
    Column("name", String(120)),
    Column("config", JSON),      # active: cron, timezone, calendar, holiday_rule, grace/miss minutes, load_type, pull
    Column("proposed", JSON),    # pending change (maker-checker)
    Column("status", String(20), index=True),  # pending_approval | active | paused | retired
    Column("version", Integer, default=0),
    Column("proposed_by", String(80)),
    Column("approved_by", String(80)),
    Column("created_by", String(80)),
    Column("created_at", DateTime, default=now),
    Column("approved_at", DateTime),
    Column("last_pull_at", DateTime),
)

deliveries = Table(
    "deliveries", metadata,
    Column("delivery_id", String(40), primary_key=True),
    Column("schedule_id", String(40), index=True),
    Column("source_id", String(40), index=True),
    Column("due_at", DateTime, index=True),          # UTC
    Column("window_start", DateTime),                # UTC; arrivals from here count toward this delivery
    Column("local_label", String(40)),               # due time in the vendor's timezone, for people
    Column("status", String(16), index=True),        # expected | received | late | received_late | missed | waived
    Column("batch_ids", JSON),
    Column("received_at", DateTime),
    Column("late_alerted_at", DateTime),
    Column("missed_alerted_at", DateTime),
    Column("waived_by", String(80)),
    Column("waive_reason", Text),
    Column("pull_attempts", Integer, default=0),
    Column("last_pull_error", Text),
    Column("created_at", DateTime, default=now),
    UniqueConstraint("schedule_id", "due_at", name="uq_delivery_window"),
)

pulled_files = Table(
    "pulled_files", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("schedule_id", String(40), index=True),
    Column("remote_name", String(300)),
    Column("remote_size", BigInteger),
    Column("remote_mtime", String(40)),
    Column("sha256", String(64)),
    Column("batch_id", String(40)),
    Column("fetched_at", DateTime, default=now),
    UniqueConstraint("schedule_id", "remote_name", "remote_size", "remote_mtime", name="uq_pulled_file"),
)

# Every signed configuration published for the data plane (Glue reads the file; this is the index + audit).
config_publications = Table(
    "config_publications", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_id", String(40), index=True),
    Column("version", Integer),
    Column("sha256", String(64)),
    Column("content_sha256", String(64)),
    Column("uri", String(500)),
    Column("mapping_id", String(40)),
    Column("mapping_version", Integer),
    Column("rules_key", Text),
    Column("reason", String(200)),
    Column("actor", String(80)),
    Column("published_at", DateTime, default=now),
    UniqueConstraint("source_id", "version", name="uq_config_publication"),
)

# Single-row leader lease so only one scheduler tick runs at a time across workers / Lambdas.
scheduler_state = Table(
    "scheduler_state", metadata,
    Column("id", Integer, primary_key=True),
    Column("owner", String(80)),
    Column("heartbeat_at", DateTime),
    Column("last_tick_at", DateTime),
    Column("last_result", JSON),
)

exceptions = Table(
    "exceptions", metadata,
    Column("exception_id", String(40), primary_key=True),
    Column("batch_id", String(40), index=True),
    Column("source_id", String(40), index=True),
    Column("loan_number", String(40), index=True),
    Column("staging_id", Integer, index=True),
    Column("rule_id", String(20), index=True),
    Column("rule_version", Integer),
    Column("rule_name", String(200)),
    Column("category", String(30)),
    Column("severity", String(10)),  # FAIL | WARN
    Column("blocking", Boolean, default=True),
    Column("field", String(80)),
    Column("original_value", Text),
    Column("message", Text),
    Column("risk", String(10)),
    Column("tier", String(4), index=True),  # T1..T5
    Column("queue", String(40), index=True),
    Column("status", String(20), index=True),  # open | auto_applied | pending_review | pending_checker | resolved | rejected | escalated | rolled_back
    Column("proposal", JSON),
    Column("resolved_value", Text),
    Column("maker", String(80)),
    Column("checker", String(80)),
    Column("qa_sample", Boolean, default=False),
    Column("created_at", DateTime, default=now),
    Column("resolved_at", DateTime),
)

rules = Table(
    "rules", metadata,
    Column("rule_id", String(20), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("status", String(20), index=True),  # draft | in_review | approved | shadow | canary | active | retired | rejected
    Column("body", JSON),
    Column("created_at", DateTime, default=now),
    Column("updated_at", DateTime, default=now),
)

rule_templates = Table(
    "rule_templates", metadata,
    Column("id", String(80), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("description", Text, default=""),
    Column("tree", JSON, nullable=False),
    Column("builtin", Boolean, default=False),
    Column("hidden", Boolean, default=False),
    Column("version", Integer, default=1),
    Column("updated_by", String(80)),
    Column("updated_at", DateTime, default=now),
)

notifications = Table(
    "notifications", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(80), nullable=False, index=True),
    Column("kind", String(60), nullable=False),
    Column("title", String(200), nullable=False),
    Column("body", Text, default=""),
    Column("entity_type", String(30), default="rule"),
    Column("entity_id", String(80), index=True),
    Column("read_at", DateTime),
    Column("created_at", DateTime, default=now, index=True),
)

policy = Table(
    "policy", metadata,
    Column("key", String(80), primary_key=True),
    Column("value", JSON),
    Column("updated_by", String(80)),
    Column("approved_by", String(80)),
    Column("updated_at", DateTime, default=now),
)

precedents = Table(
    "precedents", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("rule_id", String(20), index=True),
    Column("field", String(80)),
    Column("source_id", String(40)),
    Column("original_value", Text),
    Column("corrected_value", Text),
    Column("context", JSON),
    Column("resolved_by", String(80)),
    Column("created_at", DateTime, default=now),
)

# Learning loop: what humans approved (or rejected) for a given normalised source column name
mapping_memory = Table(
    "mapping_memory", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("norm_source", String(200), index=True),
    Column("target", String(80), index=True),
    Column("transform", JSON),
    Column("example_source", String(200)),
    Column("source_names", JSON),
    Column("role", String(12), default="primary"),  # primary | secondary (an extra 1:N target)
    Column("approved_count", Integer, default=0),
    Column("rejected_count", Integer, default=0),
    Column("last_actor", String(80)),
    Column("updated_at", DateTime, default=now),
)

audit_log = Table(
    "audit_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime, default=now, index=True),
    Column("actor", String(80)),
    Column("action", String(60)),
    Column("entity_type", String(30)),
    Column("entity_id", String(60), index=True),
    Column("detail", JSON),
    Column("prev_hash", String(64)),
    Column("hash", String(64)),
)

# Single-row head of the audit hash chain; locking it serialises writers so the chain never forks.
audit_chain = Table(
    "audit_chain", metadata,
    Column("id", Integer, primary_key=True),
    Column("last_hash", String(64)),
    Column("count", Integer, default=0),
)

_engine: Engine | None = None
_lock = threading.Lock()


def get_engine(create: bool | None = None) -> Engine:
    global _engine
    with _lock:
        if _engine is None:
            url = get_settings().resolved_database_url()
            kwargs = {"future": True}
            if url.startswith("sqlite"):
                kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if not url.startswith("sqlite"):
                kwargs.update(pool_pre_ping=True, pool_recycle=1800)
            _engine = create_engine(url, **kwargs)
            if get_settings().db_secret_arn and not get_settings().database_url:
                from ..config import db_secret

                @event.listens_for(_engine, "do_connect")
                def _inject_password(dialect, conn_rec, cargs, cparams):  # noqa: ANN001
                    # current password for every new connection: RDS rotation needs no restart
                    cparams["password"] = db_secret()["password"]
            if url.startswith("sqlite"):
                @event.listens_for(_engine, "connect")
                def _pragmas(conn, _):  # noqa: ANN001
                    conn.isolation_level = None  # let SQLAlchemy own transactions (needed for SAVEPOINTs)
                    cur = conn.cursor()
                    cur.execute("PRAGMA journal_mode=WAL")
                    cur.execute("PRAGMA synchronous=NORMAL")
                    cur.execute("PRAGMA busy_timeout=30000")
                    cur.close()

                @event.listens_for(_engine, "begin")
                def _begin(conn):  # noqa: ANN001
                    conn.exec_driver_sql("BEGIN")
            if create if create is not None else get_settings().auto_create_schema:
                metadata.create_all(_engine)
                _ensure_chain_head(_engine)
    return _engine


def _ensure_chain_head(engine) -> None:
    with engine.begin() as c:
        if c.execute(select(audit_chain.c.id).where(audit_chain.c.id == 1)).first() is None:
            c.execute(insert(audit_chain).values(id=1, last_hash="0" * 64, count=0))
        if c.execute(select(scheduler_state.c.id).where(scheduler_state.c.id == 1)).first() is None:
            c.execute(insert(scheduler_state).values(id=1))


def reset_engine() -> None:
    global _engine
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


GENESIS = "0" * 64


def _entry_hash(prev: str, ts, actor, action, entity_type, entity_id, detail) -> str:
    import hashlib

    body = json.dumps([prev, ts.isoformat() if hasattr(ts, "isoformat") else str(ts), actor, action, entity_type, entity_id, detail],
                      sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def audit(conn, actor: str, action: str, entity_type: str, entity_id: str, detail: dict | None = None) -> None:
    """Append-only, hash-chained audit trail (SOX). Each entry commits to the previous one, so an
    edited, deleted or inserted row is detectable with verify_audit_chain(). Mirrored to CloudTrail in AWS."""
    ts = now()
    det = json.loads(json.dumps(detail or {}, default=str))
    # Write first: the UPDATE takes the row lock (RDS) / write lock (SQLite) before we read the head,
    # so two writers can never chain onto the same previous hash.
    if conn.execute(audit_chain.update().where(audit_chain.c.id == 1).values(count=audit_chain.c.count + 1)).rowcount == 0:
        conn.execute(insert(audit_chain).values(id=1, last_hash=GENESIS, count=1))
    head = conn.execute(select(audit_chain).where(audit_chain.c.id == 1)).first()
    prev = head.last_hash
    h = _entry_hash(prev, ts, actor or "system", action, entity_type, str(entity_id), det)
    conn.execute(insert(audit_log).values(ts=ts, actor=actor or "system", action=action, entity_type=entity_type,
                                          entity_id=str(entity_id), detail=det, prev_hash=prev, hash=h))
    conn.execute(audit_chain.update().where(audit_chain.c.id == 1).values(last_hash=h))


def verify_audit_chain() -> dict:
    with get_engine().connect() as c:
        rows = c.execute(select(audit_log).order_by(audit_log.c.id)).all()
        head = c.execute(select(audit_chain).where(audit_chain.c.id == 1)).first()
    prev = GENESIS
    for r in rows:
        if r.prev_hash != prev or _entry_hash(prev, r.ts, r.actor, r.action, r.entity_type, r.entity_id, r.detail) != r.hash:
            return {"valid": False, "entries": len(rows), "broken_at_id": r.id, "action": r.action}
        prev = r.hash
    if head and (head.last_hash != prev or (head.count or 0) != len(rows)):
        return {"valid": False, "entries": len(rows), "broken_at_id": None, "reason": "chain head does not match (entries removed)"}
    return {"valid": True, "entries": len(rows), "head": prev}


def check_schema_current() -> None:
    """Production: the schema is owned by migrations; refuse to run against an un-migrated database."""
    from sqlalchemy import inspect as sa_inspect

    insp = sa_inspect(get_engine(create=False))
    missing = [t for t in metadata.tables if not insp.has_table(t)]
    if missing:
        raise RuntimeError(f"database schema is not current (missing {missing[:5]}); run `python -m lbp.cli migrate`")


def row_to_dict(row) -> dict:
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat() + "Z"
    return d


__all__ = [
    "metadata", "vendors", "sources", "mappings", "batches", "loans_staging", "sse_loans", "exceptions", "rules", "rule_templates", "policy", "mapping_memory",
    "precedents", "loan_changes", "delivery_schedules", "deliveries", "pulled_files", "scheduler_state", "config_publications", "audit_log", "audit_chain", "verify_audit_chain", "check_schema_current", "get_engine", "reset_engine", "audit", "row_to_dict", "now", "new_id", "select",
    "insert", "update",
]
