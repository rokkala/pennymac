"""The Glue data plane: signed feed configurations, the standard job, and the Spark job run on a local Spark."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from lbp import config_store
from lbp.mapping import service as ms
from lbp.pipeline.batch import create_batch, run_batch
from lbp.store import db

ROOT = Path(__file__).resolve().parents[2]


def _batch(bid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()


def test_approval_publishes_a_signed_bundle_and_runs_use_it(onboarded, tmp_path):
    src = onboarded["pcg_retail"]
    cfg = config_store.load(src["source_id"])
    assert cfg.mapping_id == src["mapping_id"] and cfg.version == 1 and cfg.runtime_set["active"]
    assert config_store.publish(src["source_id"], "sme1", "no-op")["unchanged"] is True
    hist = config_store.history(src["source_id"])
    assert hist[0]["reason"] == "mapping v1 approved"
    # a run records which publication it used
    b = _batch(run_batch(create_batch(src["source_id"], src["path"], "t.csv", "ops"), workers=1)["batch_id"])
    assert b.sequence_detail["config"]["version"] == 1 and b.preflight["config_version"] == 1
    # a rule change republishes every live feed
    from lbp.rules.registry import RuleRegistry

    reg = RuleRegistry()
    base = reg.get("R015", 1)
    v2 = reg.create_draft({**base, "rule_id": "R015", "tests": base["tests"]}, "dan.sme")
    reg.transition("R015", v2["version"], "in_review", "dan.sme")
    reg.transition("R015", v2["version"], "approved", "ana", ["compliance"])
    reg.transition("R015", v2["version"], "shadow", "ana", ["compliance"])
    assert config_store.load(src["source_id"]).version == 2
    assert any(r["rule_id"] == "R015" for r in config_store.load(src["source_id"]).runtime_set["shadow"])


def test_tampered_or_stale_configuration_is_refused(onboarded):
    src = onboarded["pcg_retail"]
    cur = Path(db.get_engine().url.database).parent / "config" / "feeds" / src["source_id"] / "current.json" \
        if db.get_engine().url.get_backend_name() == "sqlite" else None
    from lbp.config import get_settings

    cur = get_settings().data_dir / "config" / "feeds" / src["source_id"] / "current.json"
    good = cur.read_text()
    body = json.loads(good)
    body["mapping"]["fields"][0]["transform"] = [{"op": "constant", "value": "X"}]  # someone edits the file in S3
    cur.write_text(json.dumps(body))
    bid = create_batch(src["source_id"], src["path"], "t.csv", "ops")
    with pytest.raises(config_store.ConfigError, match="signature"):
        run_batch(bid, workers=1)
    assert _batch(bid).status == "failed" and "signature" in _batch(bid).error
    cur.write_text(good)
    # a new mapping version approved but not yet published is caught too
    v2 = ms.new_version(src["source_id"], "analyst1")
    ms.submit(v2["mapping_id"], "analyst1")
    with db.get_engine().begin() as c:  # simulate the publication failing after the approval committed
        c.execute(db.sources.update().where(db.sources.c.source_id == src["source_id"]).values(active_mapping_id=v2["mapping_id"]))
    bid2 = create_batch(src["source_id"], src["path"], "t2.csv", "ops", allow_duplicate=True, reason="x")
    with pytest.raises(config_store.ConfigError, match="behind"):
        run_batch(bid2, workers=1)


def test_standard_job_entrypoint(onboarded):
    from lbp import glue_jobs

    src = onboarded["bulk_acquisition"]
    res = glue_jobs.process_batch(create_batch(src["source_id"], src["path"], src["path"].name, "s3"))
    assert res["processed"] == 300 and _batch(res["batch_id"]).status == "completed"
    assert json.loads(glue_jobs.summary(res))["batch_id"] == res["batch_id"]


@pytest.mark.skipif(not shutil.which("java"), reason="needs Java for a local Spark")
def test_spark_job_on_local_spark(onboarded, tmp_path, env):
    pytest.importorskip("pyspark")
    pytest.importorskip("pyarrow")
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    fake = tmp_path / "fakeglue" / "awsglue"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text("")
    (fake / "utils.py").write_text(
        "def getResolvedOptions(argv, names):\n"
        "    out = {}\n"
        "    for n in names:\n"
        "        out[n] = argv[argv.index('--' + n) + 1]\n"
        "    return out\n")
    (fake / "context.py").write_text(
        "from pyspark.sql import SparkSession\n"
        "class GlueContext:\n"
        "    def __init__(self, sc):\n"
        "        self.spark_session = SparkSession(sc)\n")
    boot = tmp_path / "boot.py"
    boot.write_text("import pyspark, runpy, sys\n"
                    "pyspark.SparkContext.getOrCreate(pyspark.SparkConf().setMaster('local[2]').setAppName('lbp-test')"
                    ".set('spark.ui.enabled','false').set('spark.sql.shuffle.partitions','4'))\n"
                    f"sys.argv = ['job', '--batch_id', '{bid}', '--processed_bucket', '{tmp_path / 'processed'}']\n"
                    f"runpy.run_path('{ROOT / 'aws' / 'glue' / 'feed_spark_job.py'}', run_name='__main__')\n")
    envv = {**os.environ, "PYTHONPATH": f"{tmp_path / 'fakeglue'}:{ROOT / 'backend'}", "PYSPARK_PYTHON": sys.executable}
    # SparkContext() inside the script picks up the context created by boot.py
    envv["LBP_WORKERS"] = "1"
    r = subprocess.run([sys.executable, str(boot)], env=envv, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    b = _batch(bid)
    assert b.status == "completed" and b.reconciliation["balanced"] and b.processed == 300, (b.status, b.error, r.stdout[-500:])
    assert list((tmp_path / "processed").rglob("*.parquet"))
    # same outcome as the standard engine on the same file
    from lbp import glue_jobs

    p2 = tmp_path / "copy.csv"
    p2.write_text(Path(src["path"]).read_text())
    with db.get_engine().begin() as c:
        c.execute(db.sse_loans.delete())
    res = glue_jobs.process_batch(create_batch(src["source_id"], p2, "copy.csv", "s3", allow_duplicate=True, reason="engine parity"))
    assert (res["passed"], res["warned"], res["failed"]) == (b.passed, b.warned, b.failed)
