"""Runtime configuration. Every setting can be overridden with an LBP_* environment variable.

Local mode (default) runs the whole platform on one machine with SQLite and the local
filesystem. AWS mode swaps the storage adapters for S3 / DynamoDB / RDS without touching
the processing, rule or exception logic.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(f"LBP_{name}", default)


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _env("ENV", "local"))  # local | aws
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(Path.cwd() / ".lbp_data"))))
    # SQLAlchemy URL. Local: SQLite. AWS: mssql+pyodbc://... (RDS SQL Server) or postgresql://...
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", ""))
    # heuristic | bedrock | anthropic
    ai_provider: str = field(default_factory=lambda: _env("AI_PROVIDER", "heuristic"))
    bedrock_model_id: str = field(default_factory=lambda: _env("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-5-20250929-v1:0"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-sonnet-4-5"))
    aws_region: str = field(default_factory=lambda: _env("AWS_REGION", os.environ.get("AWS_REGION", "us-east-1")))
    # Pipeline
    micro_batch_size: int = field(default_factory=lambda: int(_env("MICRO_BATCH_SIZE", "10000")))
    workers: int = field(default_factory=lambda: int(_env("WORKERS", str(max(2, (os.cpu_count() or 2))))))
    # Max rows/sec written to SSE. 0 = unthrottled. Protects SSE during large imports.
    sse_throttle_rps: int = field(default_factory=lambda: int(_env("SSE_THROTTLE_RPS", "0")))
    # AWS resource names (used when env == aws)
    raw_bucket: str = field(default_factory=lambda: _env("RAW_BUCKET", ""))
    processed_bucket: str = field(default_factory=lambda: _env("PROCESSED_BUCKET", ""))
    rules_table: str = field(default_factory=lambda: _env("RULES_TABLE", ""))
    policy_table: str = field(default_factory=lambda: _env("POLICY_TABLE", ""))
    # Security
    # dev: identity from X-User/X-Roles headers (local only) | jwt: verify Cognito access/id token
    auth_mode: str = field(default_factory=lambda: _env("AUTH_MODE", "dev" if _env("ENV", "local") == "local" else "jwt"))
    cognito_region: str = field(default_factory=lambda: _env("COGNITO_REGION", os.environ.get("AWS_REGION", "us-east-1")))
    cognito_user_pool_id: str = field(default_factory=lambda: _env("COGNITO_USER_POOL_ID", ""))
    cognito_client_id: str = field(default_factory=lambda: _env("COGNITO_CLIENT_ID", ""))
    cognito_domain: str = field(default_factory=lambda: _env("COGNITO_DOMAIN", ""))
    cors_origins: str = field(default_factory=lambda: _env("CORS_ORIGINS", "*" if _env("ENV", "local") == "local" else ""))
    enable_demo: bool = field(default_factory=lambda: _env("ENABLE_DEMO", "true" if _env("ENV", "local") == "local" else "false") == "true")
    max_upload_mb: int = field(default_factory=lambda: int(_env("MAX_UPLOAD_MB", "1024")))
    staging_pii_retention_days: int = field(default_factory=lambda: int(_env("STAGING_PII_RETENTION_DAYS", "30")))
    # RDS-managed credentials (Secrets Manager, rotated): password fetched per new connection
    db_secret_arn: str = field(default_factory=lambda: _env("DB_SECRET_ARN", ""))
    db_host: str = field(default_factory=lambda: _env("DB_HOST", ""))
    db_name: str = field(default_factory=lambda: _env("DB_NAME", "lbp"))
    db_driver: str = field(default_factory=lambda: _env("DB_DRIVER", "mssql+pyodbc"))
    ssm_prefix: str = field(default_factory=lambda: _env("SSM_PREFIX", ""))
    # Vendor delivery scheduler
    scheduler_enabled: bool = field(default_factory=lambda: _env("SCHEDULER_ENABLED", "true" if _env("ENV", "local") == "local" else "false") == "true")
    alert_topic_arn: str = field(default_factory=lambda: _env("ALERT_TOPIC_ARN", ""))
    # pull connectors: only these hosts / buckets may be pulled from (comma list; "sftp.vendor.com", "s3:vendor-bucket")
    pull_allowed_hosts: str = field(default_factory=lambda: _env("PULL_ALLOWED_HOSTS", ""))
    # pull credentials must live under this Secrets Manager prefix (never in the database)
    vendor_secret_prefix: str = field(default_factory=lambda: _env("VENDOR_SECRET_PREFIX", "lbp/vendors/"))
    pull_local_root: Path = field(default_factory=lambda: Path(_env("PULL_LOCAL_ROOT", str(Path(_env("DATA_DIR", str(Path.cwd() / ".lbp_data"))) / "dropzone"))))
    # Data plane (AWS Glue) configuration bundles
    config_bucket: str = field(default_factory=lambda: _env("CONFIG_BUCKET", ""))
    config_signing_secret_arn: str = field(default_factory=lambda: _env("CONFIG_SIGNING_SECRET_ARN", ""))
    state_machine_arn: str = field(default_factory=lambda: _env("STATE_MACHINE_ARN", ""))
    glue_feed_job: str = field(default_factory=lambda: _env("GLUE_FEED_JOB", ""))
    glue_pull_job: str = field(default_factory=lambda: _env("GLUE_PULL_JOB", ""))
    auto_create_schema: bool = field(default_factory=lambda: _env("AUTO_CREATE_SCHEMA", "true" if _env("ENV", "local") == "local" else "false") == "true")

    def validate_for_production(self) -> list[str]:
        """Settings that must hold outside a developer laptop. The API refuses to start otherwise."""
        if self.env == "local":
            return []
        p = []
        if self.auth_mode != "jwt":
            p.append("LBP_AUTH_MODE must be 'jwt' outside local")
        if not (self.cognito_user_pool_id and self.cognito_client_id):
            p.append("LBP_COGNITO_USER_POOL_ID and LBP_COGNITO_CLIENT_ID are required")
        if self.database_url.startswith("sqlite") or not (self.database_url or (self.db_secret_arn and self.db_host)):
            p.append("database must be RDS: set LBP_DB_SECRET_ARN + LBP_DB_HOST (or a non-SQLite LBP_DATABASE_URL)")
        if self.enable_demo:
            p.append("LBP_ENABLE_DEMO must be false")
        if self.cors_origins.strip() == "*":
            p.append("LBP_CORS_ORIGINS must list explicit origins")
        if self.auto_create_schema:
            p.append("LBP_AUTO_CREATE_SCHEMA must be false (run migrations)")
        if not self.config_signing_secret_arn:
            p.append("LBP_CONFIG_SIGNING_SECRET_ARN is required (feed configurations for Glue are signed)")
        return p

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.db_secret_arn and self.db_host:
            user = db_secret()["username"]
            port = 1433 if self.db_driver.startswith("mssql") else 5432
            extra = "?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no" if self.db_driver.startswith("mssql") else "?sslmode=require"
            return f"{self.db_driver}://{user}@{self.db_host}:{port}/{self.db_name}{extra}"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.data_dir / 'lbp.db'}"


_settings: Settings | None = None


_secret_cache: dict = {}
SECRET_TTL_SECONDS = 300


def db_secret(force: bool = False) -> dict:
    """RDS-managed secret {username, password}. Cached briefly; refreshed after rotation."""
    import json
    import time

    s = get_settings()
    hit = _secret_cache.get(s.db_secret_arn)
    if hit and not force and time.time() - hit[0] < SECRET_TTL_SECONDS:
        return hit[1]
    import boto3

    val = json.loads(boto3.client("secretsmanager", region_name=s.aws_region).get_secret_value(SecretId=s.db_secret_arn)["SecretString"])
    _secret_cache[s.db_secret_arn] = (time.time(), val)
    return val


def _apply_ssm(s: Settings) -> Settings:
    """Overlay settings published by Terraform under LBP_SSM_PREFIX (e.g. the Cognito client id)."""
    if not s.ssm_prefix:
        return s
    import dataclasses

    import boto3

    resp = boto3.client("ssm", region_name=s.aws_region).get_parameters_by_path(Path=s.ssm_prefix, Recursive=False)
    vals = {p["Name"].rsplit("/", 1)[-1]: p["Value"] for p in resp.get("Parameters", [])}
    allowed = {"cognito_client_id", "cognito_domain", "cognito_user_pool_id", "cors_origins"}
    return dataclasses.replace(s, **{k: v for k, v in vals.items() if k in allowed and not os.environ.get(f"LBP_{k.upper()}")})


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = _apply_ssm(Settings())
    return _settings


def reset_settings() -> None:
    """Used by tests after changing environment variables."""
    global _settings
    _settings = None
