"""Demo kit setup: resolver, wipe/conflict, run_demo_setup, API."""
from __future__ import annotations

import pytest

from lbp.demo_setup import resolve_kit_dir


def test_resolve_kit_dir_finds_demo_kit(tmp_path):
    kit = tmp_path / "demo_kit"
    (kit / "files").mkdir(parents=True)
    (kit / "MANIFEST.csv").write_text("stage,vendor,feed,file,rows,what_it_shows,expected_outcome\n")
    assert resolve_kit_dir(tmp_path) == kit.resolve()


def test_resolve_kit_dir_falls_back_to_hyphen_nest(tmp_path):
    kit = tmp_path / "demo-kit" / "demo_kit"
    (kit / "files").mkdir(parents=True)
    assert resolve_kit_dir(tmp_path) == kit.resolve()


def test_resolve_kit_dir_env_override(tmp_path, monkeypatch):
    kit = tmp_path / "custom"
    kit.mkdir()
    monkeypatch.setenv("LBP_DEMO_KIT", str(kit))
    assert resolve_kit_dir(tmp_path) == kit.resolve()


def test_resolve_kit_dir_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.delenv("LBP_DEMO_KIT", raising=False)
    assert resolve_kit_dir(tmp_path) is None


def test_data_is_present_false_on_fresh_env(env):
    from lbp.demo_setup import data_is_present

    assert data_is_present() is False


def test_data_is_present_true_after_source(env, sample_files):
    from lbp.demo_setup import data_is_present
    from lbp.mapping import service as ms

    path = next(iter(sample_files.values()))
    ms.register_source("T", path, "analyst.demo", "t")
    assert data_is_present() is True


def test_wipe_data_dir_clears_presence(env, sample_files):
    from lbp.config import get_settings
    from lbp.demo_setup import data_is_present, wipe_data_dir
    from lbp.mapping import service as ms
    from lbp.rules.registry import RuleRegistry

    ms.register_source("T", next(iter(sample_files.values())), "a", "t")
    wipe_data_dir(get_settings().data_dir)
    RuleRegistry().seed_defaults()
    assert data_is_present() is False


def test_run_demo_setup_compact_creates_vendors_and_batches(env, monkeypatch):
    monkeypatch.setenv("LBP_PULL_ALLOWED_HOSTS", "sftp.westside-partner.example")
    from lbp import vendors as vs
    from lbp.demo_setup import run_demo_setup
    from lbp.store import db
    from sqlalchemy import func, select

    result = run_demo_setup(scale="compact", force=False)
    assert result.scale == "compact"
    assert result.rows == 200
    assert len(vs.list_vendors()) >= 4
    with db.get_engine().connect() as c:
        n_batches = c.execute(select(func.count()).select_from(db.batches)).scalar()
    assert n_batches >= 4
    assert result.vendors >= 4
    assert result.batches >= 4


def test_run_demo_setup_builds_master_detail_feed(env, monkeypatch):
    """One two-file feed: layout approved by two users, one set loaded, one set waiting for its detail file."""
    monkeypatch.setenv("LBP_PULL_ALLOWED_HOSTS", "sftp.westside-partner.example")
    from sqlalchemy import select

    from lbp.demo_setup import run_demo_setup
    from lbp.store import db

    run_demo_setup(scale="compact")
    with db.get_engine().connect() as c:
        feeds = c.execute(select(db.sources).where(db.sources.c.layout.is_not(None))).all()
        assert len(feeds) == 1
        sid = feeds[0].source_id
        assert feeds[0].layout_draft is None and feeds[0].active_mapping_id
        acts = {(r.action, r.actor) for r in c.execute(select(db.audit_log).where(db.audit_log.c.entity_id == sid))}
        proposer = next(a for act, a in acts if act == "source.layout_propose")
        approver = next(a for act, a in acts if act == "source.layout_approve")
        assert proposer != approver
        sets = {s.status: s for s in c.execute(select(db.file_sets).where(db.file_sets.c.source_id == sid))}
        assert set(sets) == {"consumed", "waiting"}
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == sets["consumed"].batch_id)).first()
        assert b.status == "completed" and b.reconciliation["join"]["per_role"]["escrow_items"]["orphaned"] > 0
        waiting = [m.role for m in c.execute(select(db.batch_files).where(db.batch_files.c.set_id == sets["waiting"].set_id))]
        assert waiting == ["master"]
    from lbp.config import get_settings

    live = get_settings().data_dir / "demo_uploads" / "3_multi_file"
    assert [p.name for p in live.iterdir()] == [f"escrow_items_{sets['waiting'].pairing_key}.csv"]


def test_run_demo_setup_conflict_without_force(env, monkeypatch):
    monkeypatch.setenv("LBP_PULL_ALLOWED_HOSTS", "sftp.westside-partner.example")
    from lbp.demo_setup import DemoSetupConflict, run_demo_setup

    run_demo_setup(scale="compact")
    with pytest.raises(DemoSetupConflict):
        run_demo_setup(scale="compact", force=False)


def test_run_demo_setup_force_rebuilds(env, monkeypatch):
    monkeypatch.setenv("LBP_PULL_ALLOWED_HOSTS", "sftp.westside-partner.example")
    from lbp.demo_setup import run_demo_setup

    run_demo_setup(scale="compact")
    again = run_demo_setup(scale="compact", force=True)
    assert again.scale == "compact"


def test_demo_setup_api_requires_admin(client, env, monkeypatch):
    monkeypatch.setenv("LBP_PULL_ALLOWED_HOSTS", "sftp.westside-partner.example")
    r = client.post(
        "/api/demo/setup",
        json={"force": False, "scale": "compact"},
        headers={"X-User": "priya.analyst", "X-Roles": "analyst"},
    )
    assert r.status_code == 403


def test_demo_setup_api_409_then_force(client, env, monkeypatch):
    monkeypatch.setenv("LBP_PULL_ALLOWED_HOSTS", "sftp.westside-partner.example")
    h = {"X-User": "admin", "X-Roles": "admin"}
    assert client.post("/api/demo/setup", json={"force": False, "scale": "compact"}, headers=h).status_code == 200
    assert client.post("/api/demo/setup", json={"force": False, "scale": "compact"}, headers=h).status_code == 409
    assert client.post("/api/demo/setup", json={"force": True, "scale": "compact"}, headers=h).status_code == 200


def test_config_exposes_demo_setup(client, env):
    cfg = client.get("/api/config").json()
    assert cfg["demo"] is True
    assert cfg["demo_setup"]["default_scale"] == "compact"
