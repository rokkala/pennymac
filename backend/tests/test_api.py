def test_end_to_end_via_api(client, sample_files):
    h = {"X-User": "analyst1", "X-Roles": "analyst"}
    with open(sample_files["bulk_acquisition"], "rb") as f:
        r = client.post("/api/sources", data={"name": "Bulk"}, files={"file": ("bulk.xlsx", f)}, headers=h)
    assert r.status_code == 200, r.text
    mid, sid = r.json()["mapping_id"], r.json()["source_id"]
    assert client.post(f"/api/mappings/{mid}/accept-all?min_confidence=0", headers=h).status_code == 200
    pv = client.get(f"/api/mappings/{mid}/preview").json()
    assert pv["rows"] > 0 and pv["pass_rate"] > 80
    assert client.post(f"/api/mappings/{mid}/submit", headers=h).status_code == 200
    r = client.post(f"/api/mappings/{mid}/approve", json={"approve": True}, headers={"X-User": "sme1", "X-Roles": "sme"})
    assert r.json()["status"] == "approved"
    from lbp.pipeline.batch import create_batch, run_batch

    bid = create_batch(sid, sample_files["bulk_acquisition"], "bulk.xlsx", "ops")
    run_batch(bid, workers=1)
    b = client.get(f"/api/batches/{bid}").json()
    assert b["status"] == "completed" and b["reconciliation"]["balanced"]
    ex = client.get("/api/exceptions?status=open").json()
    assert ex["total"] > 0
    one = client.get(f"/api/exceptions/{ex['items'][0]['exception_id']}", headers={"X-Roles": "reviewer"}).json()
    if one["field"] == "borrower_ssn" and one["loan_record"].get("borrower_ssn"):
        assert one["loan_record"]["borrower_ssn"].startswith("***")
    for path in ("import-status", "exceptions", "dq-scorecard", "source-performance", "ai-mapping", "executive"):
        assert client.get(f"/api/analytics/{path}").status_code == 200, path
    assert client.post("/api/analytics/ask", json={"question": "what are the top exception rules?"}).json()["answer"]
    assert client.get("/api/rules").json()["rules"]
    d = client.post("/api/rules/author", json={"text": "Credit score must be at least 580"}).json()
    assert d["draft"]["field"] == "borrower_fico" and all(t["passed"] for t in d["test_results"])
    assert client.get("/api/audit").json()["items"]


def test_presign_requires_aws(client):
    assert client.post("/api/upload/presign?source_id=x&filename=a.csv").status_code == 400


def test_incremental_and_scheduler_api(client, onboarded, tmp_path):
    import csv

    from lbp.pipeline.batch import create_batch, run_batch

    src = onboarded["pcg_retail"]
    sid = src["source_id"]
    run_batch(create_batch(sid, src["path"], src["path"].name, "ops1"), workers=1)
    an, sme, ops = ({"X-User": "ana", "X-Roles": "analyst"}, {"X-User": "sam", "X-Roles": "sme"}, {"X-User": "oli", "X-Roles": "ops"})
    prof = {"load_type": "incremental", "action": {"mode": "column", "column": "Action", "values": {"C": "update", "D": "close"}},
            "sequence": {"source": "filename", "pattern": r"_(\d+)\.csv$", "kind": "integer"}}
    assert client.put(f"/api/sources/{sid}/delivery", json=prof, headers=ops).status_code == 403
    bad = client.put(f"/api/sources/{sid}/delivery", json={**prof, "action": {"mode": "column", "values": {"C": "upsert"}}}, headers=an)
    assert bad.status_code == 400 and "action.column" in bad.json()["detail"]
    assert client.put(f"/api/sources/{sid}/delivery", json=prof, headers=an).status_code == 200
    t = client.get(f"/api/sources/{sid}/delivery/test?filename=PCG_DELTA_000042.csv&draft=true").json()
    assert t["ok"] and t["sequence"] == "42" and t["load_type"] == "incremental"
    assert client.post(f"/api/sources/{sid}/delivery/approve", json={"approve": True}, headers=an).status_code == 403
    assert client.post(f"/api/sources/{sid}/delivery/approve", json={"approve": True}, headers=sme).status_code == 200
    d = client.get(f"/api/sources/{sid}/delivery").json()
    assert d["configured"] and d["delivery"]["load_type"] == "incremental" and d["draft"] is None
    # upload a change file through the API
    ln = client.get("/api/batches?limit=1").json()["batches"][0]
    with open(src["path"]) as f:
        first = next(csv.DictReader(f))["LoanID"]
    p = tmp_path / "PCG_DELTA_000001.csv"
    p.write_text(f"LoanID,Action,CurrentUPB\n{first},C,4242\n")
    with open(p, "rb") as f:
        r = client.post("/api/upload", data={"source_id": sid, "auto_start": "false"}, files={"file": (p.name, f)}, headers=ops)
    assert r.status_code == 200, r.text
    bid = r.json()["batch_id"]
    run_batch(bid, workers=1)
    b = client.get(f"/api/batches/{bid}").json()
    assert b["load_type"] == "incremental" and b["sequence"] == "1" and b["change_summary"]["updates_applied"] == 1, (b, ln)
    ch = client.get(f"/api/batches/{bid}/changes").json()
    assert ch["by_action"] == {"update": 1} and ch["applied"][0]["changes"]["current_principal_balance"]["new"] == 4242
    hist = client.get(f"/api/loans/{first}/history").json()
    assert hist["loan"]["lbp_version"] == 2 and hist["history"][0]["action"] == "update"
    # sequencing actions are role-checked
    assert client.post(f"/api/batches/{bid}/discard", json={"reason": "x"}, headers=an).status_code == 403
    assert client.post(f"/api/batches/{bid}/discard", json={"reason": "x"}, headers=ops).status_code == 400  # completed
    # scheduler
    pv = client.get("/api/schedules/preview?cron=0%206%20*%20*%20MON-FRI&timezone=America/New_York").json()
    assert pv["valid"] and pv["describe"] == "Business days at 06:00"
    cfg = {"cron": "0 6 * * MON-FRI", "timezone": "America/New_York", "calendar": "us_federal"}
    # compliance (member) cannot create schedules; onboarding/monitoring can
    assert client.post("/api/schedules", json={"source_id": sid, "name": "PCG daily", "config": cfg},
                       headers={"X-User": "comp", "X-Roles": "compliance"}).status_code == 403
    s = client.post("/api/schedules", json={"source_id": sid, "name": "PCG daily", "config": cfg}, headers=ops).json()
    assert s["status"] == "pending_approval"
    assert client.post(f"/api/schedules/{s['schedule_id']}/approve", json={"approve": True}, headers=ops).status_code == 403
    s = client.post(f"/api/schedules/{s['schedule_id']}/approve", json={"approve": True}, headers=sme).json()
    assert s["status"] == "active" and s["next_due"]
    assert client.post("/api/scheduler/tick", headers=ops).status_code == 200
    dl = client.get("/api/deliveries?days_ahead=5").json()["deliveries"]
    assert dl and dl[0]["source_name"] and dl[0]["status"] == "expected"
    w = client.post(f"/api/deliveries/{dl[0]['delivery_id']}/waive", json={"reason": "vendor holiday"}, headers=ops)
    assert w.status_code == 200 and w.json()["status"] == "waived"
    v = {x["source_id"]: x for x in client.get("/api/analytics/vendors").json()["vendors"]}[sid]
    assert v["load_type"] == "incremental" and v["last_sequence"] == "1" and v["schedules"] == 1
