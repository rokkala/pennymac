import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LBP_DATA_DIR", str(tmp_path / "data"))
    test_db = os.environ.get("LBP_TEST_DATABASE_URL")  # e.g. postgresql+psycopg://lbp@/lbp_test?host=/tmp&port=5433
    if test_db:
        monkeypatch.setenv("LBP_DATABASE_URL", test_db)
    monkeypatch.setenv("LBP_WORKERS", "1")
    monkeypatch.setenv("LBP_MICRO_BATCH_SIZE", "100")
    from lbp import ai, config
    from lbp.store import db

    config.reset_settings()
    db.reset_engine()
    ai._client = None
    if test_db:
        db.metadata.drop_all(db.get_engine())
        db.reset_engine()
    from lbp.rules.registry import RuleRegistry

    RuleRegistry().seed_defaults()
    yield tmp_path
    db.reset_engine()
    config.reset_settings()


@pytest.fixture()
def sample_files(env):
    from lbp.samples import generate_all

    return generate_all(env / "samples", 300)


@pytest.fixture()
def onboarded(sample_files):
    """All four sources onboarded and approved."""
    from lbp.mapping import service as ms

    out = {}
    for key, path in sample_files.items():
        reg = ms.register_source(key, path, "analyst1")
        ms.accept_all(reg["mapping_id"], "analyst1", 0.0)
        ms.submit(reg["mapping_id"], "analyst1")
        ms.approve(reg["mapping_id"], "sme1", ["sme"])
        out[key] = {**reg, "path": path}
    return out


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient

    from lbp.api.main import app

    with TestClient(app) as c:
        yield c
