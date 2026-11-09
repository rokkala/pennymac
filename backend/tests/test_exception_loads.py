"""Exceptions are filterable/groupable by vendor, file, and load date."""


def _board_one(onboarded, sample_files, key="correspondent"):
    from lbp.pipeline.batch import create_batch, run_batch

    src = onboarded[key]
    path = sample_files[key]
    bid = create_batch(src["source_id"], path, path.name, "ops")
    run_batch(bid, workers=1)
    return bid, path.name, src


def test_exception_list_includes_filename_and_loaded_at(client, onboarded, sample_files):
    bid, fname, _ = _board_one(onboarded, sample_files)
    data = client.get("/api/exceptions?status=open&limit=50").json()
    row = next(i for i in data["items"] if i["batch_id"] == bid)
    assert row["filename"] == fname
    assert row["loaded_at"]
    assert row["vendor_name"]


def test_exception_list_filters_by_loaded_on_and_batch(client, onboarded, sample_files):
    bid, _, src = _board_one(onboarded, sample_files)
    day = client.get(f"/api/exceptions?status=open&batch_id={bid}&limit=5").json()["items"][0]["loaded_at"][:10]
    by_day = client.get(f"/api/exceptions?status=open&loaded_on={day}&limit=200").json()
    assert by_day["total"] >= 1
    assert all((i.get("loaded_at") or "")[:10] == day for i in by_day["items"])
    by_batch = client.get(f"/api/exceptions?status=open&batch_id={bid}&limit=200").json()
    assert by_batch["total"] >= 1
    assert all(i["batch_id"] == bid for i in by_batch["items"])
    # vendor scope via query
    scoped = client.get(f"/api/exceptions?status=open&vendor_id={src['vendor_id']}&limit=200").json()
    assert scoped["total"] >= 1
    assert all(i["vendor_id"] == src["vendor_id"] for i in scoped["items"])


def test_exception_loads_endpoint(client, onboarded, sample_files):
    bid, fname, src = _board_one(onboarded, sample_files)
    loads = client.get("/api/exceptions/loads?status=open").json()["loads"]
    hit = next(x for x in loads if x["batch_id"] == bid)
    assert hit["filename"] == fname
    assert hit["vendor_id"] == src["vendor_id"]
    assert hit["vendor_name"]
    assert hit["loaded_on"]
    assert hit["open_count"] >= 1
    # cascading: vendor filter
    only = client.get(f"/api/exceptions/loads?status=open&vendor_id={src['vendor_id']}").json()["loads"]
    assert only and all(x["vendor_id"] == src["vendor_id"] for x in only)
    # tier scopes open_count (T2 subset ≤ all open for that batch)
    all_open = next(x["open_count"] for x in loads if x["batch_id"] == bid)
    t2 = client.get(f"/api/exceptions/loads?status=open&tier=T2").json()["loads"]
    t2_hit = next((x for x in t2 if x["batch_id"] == bid), None)
    if t2_hit:
        assert t2_hit["open_count"] <= all_open
