"""Published feed configurations: the only configuration the data plane (AWS Glue) reads.

Everything a person sets up in the web app (a feed's approved mapping and value maps, its delivery
profile, parse options and profile, the vendor's feeds, the live rule set) is compiled into one
**feed bundle** when it is approved:

    s3://<config bucket>/config/feeds/<source_id>/v<n>.json     immutable, one per publication
    s3://<config bucket>/config/feeds/<source_id>/current.json  what the next run uses

Each bundle carries a SHA-256 of its canonical JSON and an HMAC-SHA256 signature (key in Secrets
Manager). A Glue job refuses a bundle whose signature does not verify, so a hand-edited or partially
written configuration can never board loans. Drafts are never published.

Publication happens automatically on: mapping approval, delivery-profile approval, rule lifecycle
changes (active / canary / shadow / retired), feed moves between vendors. Locally the same files
live under LBP_DATA_DIR/config, and local runs consume them exactly as Glue does.

Live safety switches stay live (not bundled): the T1 kill switch / auto-suspension and the vendor's
suspended status are read from the database at run time, so they take effect immediately.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from .config import get_settings
from .store import db

log = logging.getLogger("lbp.config_store")
SCHEMA = "lbp.feed-config/1"


class ConfigError(RuntimeError):
    pass


@dataclass
class FeedConfig:
    source_id: str
    vendor_id: str | None
    feed_name: str
    vendor_feeds: list[str]
    mapping_id: str
    mapping_version: int
    fields: list[dict]
    parse_options: dict
    profile: dict
    delivery: dict | None
    runtime_set: dict
    rules_key: str
    version: int = 0
    sha256: str = ""
    published_at: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def pii_cols(self) -> dict[str, str]:
        return {c["name"]: c["pii_type"] for c in (self.profile or {}).get("columns", []) if c.get("pii_type")}


# ------------------------------------------------------------------ signing
def _key() -> bytes:
    s = get_settings()
    if s.config_signing_secret_arn:
        import boto3

        return boto3.client("secretsmanager", region_name=s.aws_region).get_secret_value(
            SecretId=s.config_signing_secret_arn)["SecretString"].encode()
    if s.env != "local":
        raise ConfigError("LBP_CONFIG_SIGNING_SECRET_ARN is required outside local")
    return b"lbp-local-dev-config-key"  # local development only (validate_for_production refuses AWS without a secret)


def _canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()


def _sign(body: dict) -> tuple[str, str]:
    raw = _canonical(body)
    return hashlib.sha256(raw).hexdigest(), hmac.new(_key(), raw, hashlib.sha256).hexdigest()


def verify(bundle: dict) -> dict:
    body = {k: v for k, v in bundle.items() if k not in ("sha256", "signature")}
    sha, sig = _sign(body)
    if bundle.get("sha256") != sha or not hmac.compare_digest(bundle.get("signature") or "", sig):
        raise ConfigError(f"feed configuration for {bundle.get('source_id')} v{bundle.get('version')} failed signature verification")
    if bundle.get("schema") != SCHEMA:
        raise ConfigError(f"unsupported configuration schema {bundle.get('schema')}")
    return bundle


# ------------------------------------------------------------------ storage
def _local_root() -> Path:
    p = get_settings().data_dir / "config" / "feeds"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _bucket() -> str | None:
    s = get_settings()
    return (s.config_bucket or s.processed_bucket) if s.env == "aws" else None


def _write(source_id: str, name: str, data: bytes) -> str:
    b = _bucket()
    if b:
        import boto3

        key = f"config/feeds/{source_id}/{name}"
        boto3.client("s3", region_name=get_settings().aws_region).put_object(
            Bucket=b, Key=key, Body=data, ServerSideEncryption="aws:kms", ContentType="application/json")
        return f"s3://{b}/{key}"
    d = _local_root() / source_id
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{name}.tmp"
    tmp.write_bytes(data)
    tmp.replace(d / name)  # atomic: a reader never sees half a file
    return str(d / name)


def _read(source_id: str, name: str) -> bytes | None:
    b = _bucket()
    if b:
        import boto3
        from botocore.exceptions import ClientError

        try:
            return boto3.client("s3", region_name=get_settings().aws_region).get_object(
                Bucket=b, Key=f"config/feeds/{source_id}/{name}")["Body"].read()
        except ClientError:
            return None
    p = _local_root() / source_id / name
    return p.read_bytes() if p.exists() else None


# ------------------------------------------------------------------ publish / load
def build(source_id: str) -> dict:
    from .pipeline.delivery import profile_of
    from .rules.registry import RuleRegistry
    from .vendors import siblings

    with db.get_engine().connect() as c:
        src = c.execute(select(db.sources).where(db.sources.c.source_id == source_id)).first()
        if not src:
            raise ConfigError("unknown feed")
        if not src.active_mapping_id:
            raise ConfigError("feed has no approved mapping")
        m = c.execute(select(db.mappings).where(db.mappings.c.mapping_id == src.active_mapping_id)).first()
        feeds = siblings(c, source_id)
    rs = RuleRegistry().runtime_set()
    return {
        "schema": SCHEMA, "source_id": source_id, "vendor_id": src.vendor_id, "feed_name": src.name, "vendor_feeds": sorted(feeds),
        "mapping": {"mapping_id": m.mapping_id, "version": m.version, "approved_by": m.approved_by,
                    "approved_at": m.approved_at.isoformat() if m.approved_at else None, "fields": m.fields},
        "parse_options": src.parse_options or {}, "profile": src.profile or {}, "delivery": profile_of(src.delivery),
        "rules": rs, "rules_key": rules_key(rs),
    }


def rules_key(rs: dict) -> str:
    return ",".join(f"{r['rule_id']}:{r['version']}:{st}" for st, rs_ in rs.items() for r in rs_)


def publish(source_id: str, actor: str, reason: str) -> dict:
    """Compile, sign and publish a feed's configuration. Returns the publication record (no new
    version when nothing that affects processing changed)."""
    body = build(source_id)
    content = hashlib.sha256(_canonical(body)).hexdigest()
    t = db.config_publications
    with db.get_engine().begin() as c:
        last = c.execute(select(t.c.version, t.c.content_sha256).where(t.c.source_id == source_id).order_by(t.c.version.desc()).limit(1)).first()
        if last and last.content_sha256 == content and _read(source_id, "current.json") is not None:
            return {"source_id": source_id, "version": last.version, "unchanged": True}
        version = (last.version if last else 0) + 1
        body = {**body, "version": version, "published_at": db.now().isoformat() + "Z", "published_by": actor, "reason": reason}
        sha, sig = _sign(body)
        data = json.dumps({**body, "sha256": sha, "signature": sig}, sort_keys=True, default=str).encode()
        uri = _write(source_id, f"v{version}.json", data)
        _write(source_id, "current.json", data)
        c.execute(t.insert().values(source_id=source_id, version=version, sha256=sha, content_sha256=content, uri=uri,
                                    mapping_id=body["mapping"]["mapping_id"], mapping_version=body["mapping"]["version"],
                                    rules_key=body["rules_key"][:2000], reason=reason[:200], actor=actor, published_at=db.now()))
        db.audit(c, actor, "config.publish", "source", source_id, {"version": version, "sha256": sha, "reason": reason,
                                                                   "mapping_version": body["mapping"]["version"]})
    return {"source_id": source_id, "version": version, "sha256": sha, "uri": uri}


def publish_all(actor: str, reason: str) -> list[dict]:
    """Republish every live feed (rule or policy changes affect all of them)."""
    with db.get_engine().connect() as c:
        ids = [r[0] for r in c.execute(select(db.sources.c.source_id).where(db.sources.c.active_mapping_id.is_not(None)))]
    out = []
    for sid in ids:
        try:
            out.append(publish(sid, actor, reason))
        except ConfigError as e:
            log.warning("could not publish %s: %s", sid, e)
    return out


def load(source_id: str) -> FeedConfig:
    """The feed's current published configuration, signature-verified."""
    raw = _read(source_id, "current.json")
    if raw is None:
        raise ConfigError(f"no published configuration for feed {source_id}; approve its mapping first")
    b = verify(json.loads(raw))
    return FeedConfig(source_id=b["source_id"], vendor_id=b.get("vendor_id"), feed_name=b.get("feed_name", ""), vendor_feeds=b.get("vendor_feeds") or [b["source_id"]],
                      mapping_id=b["mapping"]["mapping_id"], mapping_version=b["mapping"]["version"], fields=b["mapping"]["fields"],
                      parse_options=b.get("parse_options") or {}, profile=b.get("profile") or {}, delivery=b.get("delivery"),
                      runtime_set=b["rules"], rules_key=b.get("rules_key", ""), version=b["version"], sha256=b["sha256"],
                      published_at=b.get("published_at", ""))


def history(source_id: str) -> list[dict]:
    with db.get_engine().connect() as c:
        rows = c.execute(select(db.config_publications).where(db.config_publications.c.source_id == source_id)
                         .order_by(db.config_publications.c.version.desc()).limit(50)).all()
    return [db.row_to_dict(r) for r in rows]


def bundle_json(source_id: str, version: int | None = None) -> dict:
    raw = _read(source_id, f"v{version}.json" if version else "current.json")
    if raw is None:
        raise ConfigError("publication not found")
    return verify(json.loads(raw))
