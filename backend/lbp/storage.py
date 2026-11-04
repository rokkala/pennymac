"""File storage: local paths in development, S3 in AWS (ECS task disks are ephemeral).

Everything that keeps a reference to a source file (batch files, onboarding samples) stores a
URI: a local path or s3://bucket/key. Readers call local_path(uri) to get a readable file;
S3 objects are downloaded once into a per-process cache. Uploads are written to the raw zone
with SSE-KMS (bucket default) when LBP_ENV=aws.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .config import get_settings


def is_s3(uri: str | Path) -> bool:
    return str(uri).startswith("s3://")


def _split(uri: str) -> tuple[str, str]:
    rest = str(uri)[5:]
    bucket, _, key = rest.partition("/")
    return bucket, key


def _s3():
    import boto3

    return boto3.client("s3", region_name=get_settings().aws_region)


def local_path(uri: str | Path) -> Path:
    if not is_s3(uri):
        return Path(uri)
    bucket, key = _split(str(uri))
    cache = get_settings().data_dir / "s3cache"
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / f"{hashlib.sha256(str(uri).encode()).hexdigest()[:16]}_{Path(key).name}"
    if not dest.exists():
        tmp = dest.with_suffix(dest.suffix + ".part")
        _s3().download_file(bucket, key, str(tmp))
        tmp.rename(dest)
    return dest


def persist_upload(local_file: Path, prefix: str, metadata: dict | None = None) -> str:
    """Store an uploaded file durably and return its URI (S3 in AWS, the local path otherwise)."""
    s = get_settings()
    if s.env != "aws" or not s.raw_bucket:
        return str(local_file)
    key = f"{prefix.strip('/')}/{local_file.name}"
    extra = {"ServerSideEncryption": "aws:kms", **({"Metadata": metadata} if metadata else {})}
    _s3().upload_file(str(local_file), s.raw_bucket, key, ExtraArgs=extra)
    local_file.unlink(missing_ok=True)
    return f"s3://{s.raw_bucket}/{key}"
