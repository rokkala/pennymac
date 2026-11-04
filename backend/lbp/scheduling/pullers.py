"""Pull connectors for vendors that do not push files to the raw S3 zone.

    sftp   vendor SFTP server. Credentials come from Secrets Manager (a secret under
           LBP_VENDOR_SECRET_PREFIX holding {"username", "password"} or {"username", "private_key"}),
           never from the database. The server's host key must be pinned (SHA-256 fingerprint);
           an unknown or changed key refuses the connection.
    s3     a bucket the vendor shares with PennyMac (cross-account), optionally via an assumed role.
    local  a directory under LBP_PULL_LOCAL_ROOT (development, or an SFTP gateway mounted on EFS).

Guardrails common to all: the host / bucket must be on LBP_PULL_ALLOWED_HOSTS, the schedule that
names it must be approved by a second person, only allowed file types and sizes are fetched, names
are sanitised, and every remote file is fetched once (remote name + size + mtime).
Remote files are never deleted or moved.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings

ALLOWED_EXT = {".csv", ".txt", ".dat", ".psv", ".xlsx", ".xlsm"}
PROTOCOLS = ("sftp", "s3", "local")


class PullError(RuntimeError):
    pass


@dataclass
class RemoteFile:
    name: str
    size: int
    mtime: str


def allowed_hosts() -> set[str]:
    return {h.strip().lower() for h in get_settings().pull_allowed_hosts.split(",") if h.strip()}


def validate_pull(cfg: dict) -> list[str]:
    """Static checks run when a schedule is proposed and again before every pull."""
    errs = []
    proto = cfg.get("protocol")
    if proto not in PROTOCOLS:
        return [f"pull.protocol must be one of {PROTOCOLS}"]
    if not cfg.get("pattern"):
        errs.append("pull.pattern (filename glob, e.g. 'LOANS_*.csv') is required")
    if proto == "sftp":
        host = (cfg.get("host") or "").lower()
        if not host:
            errs.append("pull.host is required")
        elif host not in allowed_hosts():
            errs.append(f"host '{host}' is not on the allowed list (LBP_PULL_ALLOWED_HOSTS)")
        fp = cfg.get("host_key_sha256") or ""
        if not fp.startswith("SHA256:") or len(fp) < 20:
            errs.append("pull.host_key_sha256 (the server's pinned key fingerprint, 'SHA256:...') is required")
        if not str(cfg.get("secret_ref") or "").startswith(get_settings().vendor_secret_prefix):
            errs.append(f"pull.secret_ref must be a Secrets Manager secret under '{get_settings().vendor_secret_prefix}'")
        if not cfg.get("path"):
            errs.append("pull.path (remote directory) is required")
    elif proto == "s3":
        if not cfg.get("bucket"):
            errs.append("pull.bucket is required")
        elif f"s3:{cfg['bucket'].lower()}" not in allowed_hosts():
            errs.append(f"bucket '{cfg['bucket']}' is not on the allowed list (add 's3:{cfg['bucket']}' to LBP_PULL_ALLOWED_HOSTS)")
    elif proto == "local":
        root = get_settings().pull_local_root.resolve()
        try:
            (root / (cfg.get("path") or "")).resolve().relative_to(root)
        except ValueError:
            errs.append("pull.path must stay inside LBP_PULL_LOCAL_ROOT")
    return errs


def _ok_name(name: str, pattern: str) -> bool:
    base = Path(name).name
    return (fnmatch.fnmatch(base, pattern) and Path(base).suffix.lower() in ALLOWED_EXT and not base.startswith(".")
            and ".." not in base)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Puller:
    def __init__(self, cfg: dict):
        problems = validate_pull(cfg)
        if problems:
            raise PullError("; ".join(problems))
        self.cfg = cfg
        self.limit = get_settings().max_upload_mb * 1024 * 1024

    def list(self) -> list[RemoteFile]:
        raise NotImplementedError

    def fetch(self, f: RemoteFile, dest_dir: Path) -> Path:
        raise NotImplementedError

    def close(self) -> None:
        pass


class LocalPuller(Puller):
    def _dir(self) -> Path:
        return get_settings().pull_local_root / (self.cfg.get("path") or "")

    def list(self):
        d = self._dir()
        if not d.is_dir():
            raise PullError(f"pull directory does not exist: {self.cfg.get('path')}")
        return [RemoteFile(p.name, p.stat().st_size, str(int(p.stat().st_mtime))) for p in sorted(d.iterdir())
                if p.is_file() and _ok_name(p.name, self.cfg["pattern"])]

    def fetch(self, f, dest_dir):
        import shutil

        dest = dest_dir / Path(f.name).name
        shutil.copyfile(self._dir() / f.name, dest)
        return dest


class S3Puller(Puller):
    def __init__(self, cfg):
        super().__init__(cfg)
        import boto3

        sess = boto3.session.Session(region_name=cfg.get("region") or get_settings().aws_region)
        if cfg.get("role_arn"):
            kw = {"RoleArn": cfg["role_arn"], "RoleSessionName": "lbp-vendor-pull"}
            if cfg.get("external_id"):
                kw["ExternalId"] = cfg["external_id"]
            cr = sess.client("sts").assume_role(**kw)["Credentials"]
            sess = boto3.session.Session(aws_access_key_id=cr["AccessKeyId"], aws_secret_access_key=cr["SecretAccessKey"],
                                         aws_session_token=cr["SessionToken"], region_name=sess.region_name)
        self.s3 = sess.client("s3")

    def list(self):
        out, token = [], None
        prefix = (self.cfg.get("prefix") or "").lstrip("/")
        while True:
            kw = {"Bucket": self.cfg["bucket"], "Prefix": prefix, **({"ContinuationToken": token} if token else {})}
            resp = self.s3.list_objects_v2(**kw)
            for o in resp.get("Contents", []):
                rel = o["Key"][len(prefix):].lstrip("/")
                if "/" not in rel and _ok_name(rel, self.cfg["pattern"]):
                    out.append(RemoteFile(o["Key"], int(o["Size"]), o["LastModified"].isoformat()))
            if not resp.get("IsTruncated"):
                return out
            token = resp["NextContinuationToken"]

    def fetch(self, f, dest_dir):
        dest = dest_dir / Path(f.name).name
        self.s3.download_file(self.cfg["bucket"], f.name, str(dest))
        return dest


class SftpPuller(Puller):
    def __init__(self, cfg):
        super().__init__(cfg)
        try:
            import paramiko
        except ImportError as e:  # pragma: no cover - installed in the worker image
            raise PullError("SFTP support needs the 'paramiko' package in the worker image") from e
        import base64

        import boto3

        secret = json.loads(boto3.client("secretsmanager", region_name=get_settings().aws_region)
                            .get_secret_value(SecretId=cfg["secret_ref"])["SecretString"])
        self.transport = paramiko.Transport((cfg["host"], int(cfg.get("port") or 22)))
        self.transport.start_client(timeout=30)
        key = self.transport.get_remote_server_key()
        fp = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if fp != cfg["host_key_sha256"].rstrip("="):
            self.transport.close()
            raise PullError(f"host key for {cfg['host']} does not match the pinned fingerprint (got {fp}); refusing to connect")
        if secret.get("private_key"):
            import io

            pkey = paramiko.Ed25519Key.from_private_key(io.StringIO(secret["private_key"])) if "OPENSSH" in secret["private_key"] \
                else paramiko.RSAKey.from_private_key(io.StringIO(secret["private_key"]))
            self.transport.auth_publickey(secret["username"], pkey)
        else:
            self.transport.auth_password(secret["username"], secret["password"])
        self.sftp = paramiko.SFTPClient.from_transport(self.transport)

    def list(self):
        return [RemoteFile(a.filename, int(a.st_size or 0), str(int(a.st_mtime or 0))) for a in self.sftp.listdir_attr(self.cfg["path"])
                if _ok_name(a.filename, self.cfg["pattern"])]

    def fetch(self, f, dest_dir):
        dest = dest_dir / Path(f.name).name
        self.sftp.get(f"{self.cfg['path'].rstrip('/')}/{f.name}", str(dest))
        return dest

    def close(self):
        self.transport.close()


def make_puller(cfg: dict) -> Puller:
    return {"local": LocalPuller, "s3": S3Puller, "sftp": SftpPuller}[cfg.get("protocol")](cfg)


def fetch_new(cfg: dict, already: set[tuple[str, int, str]]) -> tuple[list[tuple[RemoteFile, Path, str]], list[str]]:
    """List the remote location and download files not fetched before. Returns ([(remote, local, sha256)], skipped reasons)."""
    p = make_puller(cfg)
    got, skipped = [], []
    try:
        tmp = Path(tempfile.mkdtemp(prefix="lbp-pull-", dir=str(get_settings().data_dir) if get_settings().data_dir.exists() else None))
        for f in p.list():
            if (f.name, f.size, f.mtime) in already:
                continue
            if f.size > p.limit:
                skipped.append(f"{f.name}: larger than the {get_settings().max_upload_mb} MB limit")
                continue
            if f.size == 0:
                skipped.append(f"{f.name}: empty file (vendor may still be writing it)")
                continue
            local = p.fetch(f, tmp)
            if local.stat().st_size != f.size:
                local.unlink(missing_ok=True)
                skipped.append(f"{f.name}: size changed while downloading (still being written); will retry")
                continue
            got.append((f, local, _sha256(local)))
    finally:
        p.close()
    return got, skipped
