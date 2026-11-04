"""Allowlisted Glue / data-plane source artifacts for the Maintenance console (read-only)."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _repo_root() -> Path:
    """Monorepo checkout, Docker `/app`, or `LBP_REPO_ROOT`."""
    env = os.environ.get("LBP_REPO_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for cand in (here.parents[2], here.parents[1]):
        if (cand / "aws" / "glue").is_dir() or (cand / "backend" / "lbp" / "glue_jobs.py").is_file():
            return cand
    return here.parents[2]


REPO_ROOT = _repo_root()

# group: jobs (Glue) | shared | orchestration | notebooks
ARTIFACTS: list[dict] = [
    {"id": "feed-job", "title": "lbp-feed", "subtitle": "Board / replay one batch (driver)", "path": "aws/glue/feed_job.py", "kind": "python", "group": "jobs"},
    {"id": "feed-spark-job", "title": "lbp-feed-spark", "subtitle": "Large full tapes (Spark)", "path": "aws/glue/feed_spark_job.py", "kind": "python", "group": "jobs"},
    {"id": "vendor-pull-job", "title": "lbp-vendor-pull", "subtitle": "SFTP / S3 pull into raw zone", "path": "aws/glue/vendor_pull_job.py", "kind": "python", "group": "jobs"},
    {"id": "glue-jobs", "title": "lbp.glue_jobs", "subtitle": "Shared entrypoints the Glue scripts call", "path": "backend/lbp/glue_jobs.py", "kind": "python", "group": "shared"},
    {"id": "dispatch", "title": "lbp.dispatch", "subtitle": "API / control plane starts Glue runs", "path": "backend/lbp/dispatch.py", "kind": "python", "group": "shared"},
    {"id": "boarding-sfn", "title": "Step Functions · boarding", "subtitle": "Route → Glue → finalize → notify", "path": "aws/stepfunctions/boarding.asl.json", "kind": "json", "group": "orchestration"},
    {"id": "lambdas", "title": "Lambdas · handlers", "subtitle": "Arrival, route, finalize, API, scheduler", "path": "aws/lambdas/handlers.py", "kind": "python", "group": "orchestration"},
    {"id": "nb-feed-workbench", "title": "Notebook · feed workbench", "subtitle": "Dev dry-run — does not load loans", "path": "aws/glue/notebooks/feed_workbench.ipynb", "kind": "notebook", "group": "notebooks"},
    {"id": "nb-rule-lab", "title": "Notebook · rule lab", "subtitle": "Dev rule tryout — does not change rules", "path": "aws/glue/notebooks/rule_lab.ipynb", "kind": "notebook", "group": "notebooks"},
]

GROUPS = [
    ("jobs", "Glue jobs"),
    ("shared", "Shared libraries"),
    ("orchestration", "Orchestration"),
    ("notebooks", "Notebooks (dev only)"),
]

_BY_ID = {a["id"]: a for a in ARTIFACTS}
_META_KEYS = ("id", "title", "subtitle", "path", "kind", "group")


class MaintenanceError(Exception):
    pass


def list_artifacts() -> list[dict]:
    return [{k: a[k] for k in _META_KEYS} for a in ARTIFACTS]


def _resolve(rel: str) -> Path:
    root = _repo_root()
    if ".." in Path(rel).parts or Path(rel).is_absolute():
        raise MaintenanceError("unsafe path")
    candidates = [root / rel]
    if rel.startswith("backend/"):
        candidates.append(root / rel[len("backend/"):])
    full = next((c.resolve() for c in candidates if c.is_file()), (root / rel).resolve())
    try:
        full.relative_to(root.resolve())
    except ValueError as e:
        raise MaintenanceError("path escapes repository") from e
    return full


def _notebook_cells(raw: str) -> list[dict]:
    nb = json.loads(raw)
    out = []
    for cell in nb.get("cells") or []:
        src = cell.get("source") or ""
        if isinstance(src, list):
            src = "".join(src)
        out.append({"cell_type": cell.get("cell_type") or "code", "source": src})
    return out


def get_artifact(artifact_id: str) -> dict:
    meta = _BY_ID.get(artifact_id)
    if not meta:
        raise MaintenanceError(f"unknown artifact: {artifact_id}")
    path = _resolve(meta["path"])
    if not path.is_file():
        raise MaintenanceError(f"file missing: {meta['path']}")
    text = path.read_text(encoding="utf-8")
    content: str | list = _notebook_cells(text) if meta["kind"] == "notebook" else text
    return {**{k: meta[k] for k in _META_KEYS}, "content": content}
