"""Analytics grain: vendor and file-load."""

from datetime import timedelta


def test_import_status_includes_exception_counts_per_batch(client, onboarded, sample_files):
    from lbp.pipeline.batch import create_batch, run_batch

    src = onboarded["correspondent"]
    bid = create_batch(src["source_id"], sample_files["correspondent"], "correspondent_sample.csv", "ops")
    run_batch(bid, workers=1)

    data = client.get("/api/analytics/import-status").json()
    row = next(b for b in data["batches"] if b["batch_id"] == bid)
    assert "exceptions" in row
    assert "open_exceptions" in row
    assert row["exceptions"] >= row["open_exceptions"] >= 0
    # boarding the sample file always raises exceptions in this fixture set
    assert row["exceptions"] > 0
    assert row["vendor_name"]
    assert row["filename"]


def test_import_status_filters_status_days_and_q(onboarded, sample_files):
    from lbp.analytics.service import import_status
    from lbp.pipeline.batch import create_batch, run_batch
    from lbp.store import db

    src = onboarded["correspondent"]
    done = create_batch(src["source_id"], sample_files["correspondent"], "correspondent_sample.csv", "ops")
    run_batch(done, workers=1)
    fail = create_batch(src["source_id"], sample_files["correspondent"], "fail_tape.csv", "ops",
                        allow_duplicate=True, reason="test duplicate for filters")
    with db.get_engine().begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == fail).values(status="failed", error="test"))

    since = db.now() - timedelta(days=30)
    data = import_status(limit=50, statuses=["completed"], since=since, q="correspondent_sample")
    assert "attention" in data
    assert data["batches"]
    assert all(b["status"] == "completed" for b in data["batches"])
    assert all("correspondent_sample" in b["filename"] for b in data["batches"])


def test_attention_not_capped_by_limit(onboarded, sample_files):
    from lbp.analytics.service import import_status
    from lbp.pipeline.batch import create_batch
    from lbp.store import db

    src = onboarded["correspondent"]
    a = create_batch(src["source_id"], sample_files["correspondent"], "attn_a.csv", "ops",
                     allow_duplicate=True, reason="attention fixture a")
    b = create_batch(src["source_id"], sample_files["correspondent"], "attn_b.csv", "ops",
                     allow_duplicate=True, reason="attention fixture b")
    with db.get_engine().begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id.in_((a, b))).values(status="failed", error="test"))

    data = import_status(limit=1, since=db.now() - timedelta(days=30))
    assert data["attention"] >= 2
    assert len(data["batches"]) == 1


def test_import_status_q_respects_vendor_scope(onboarded, sample_files):
    from lbp.analytics.service import import_status
    from lbp.pipeline.batch import create_batch
    from lbp.store import db

    a = onboarded["correspondent"]
    b = onboarded["sub_servicing"]
    create_batch(a["source_id"], sample_files["correspondent"], "scoped_pcg.csv", "ops",
                 allow_duplicate=True, reason="scope fixture")
    data = import_status(limit=50, source_ids=[b["source_id"]], q="scoped_pcg")
    assert data["batches"] == []
