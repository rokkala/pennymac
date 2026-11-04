from lbp.ingestion.parser import read_sample
from lbp.ingestion.profiler import profile_rows
from lbp.mapping.engine import suggest_mappings

EXPECTED = {
    "pcg_retail": {"LoanID": "loan_number", "NoteRate": "interest_rate", "CurrentUPB": "current_principal_balance", "PropertyState": "property_state"},
    "bulk_acquisition": {"Loan No": "loan_number", "Int Rate": "interest_rate", "Orig Bal": "original_loan_amount",
                         "Social Security #": "borrower_ssn", "Seller Loan ID": "prior_servicer_loan_number"},
    "sub_servicing": {"LN_NBR": "loan_number", "B1_TIN": "borrower_ssn", "CUR_UPB": "current_principal_balance", "PROP_ST": "property_state"},
    "correspondent": {"Correspondent Loan Number": "loan_number", "Tax ID": "borrower_ssn", "Unpaid Principal Balance": "current_principal_balance"},
}


def test_auto_map_rate_and_accuracy(sample_files):
    for key, path in sample_files.items():
        meta, rows = read_sample(path, 300)
        prof = profile_rows(meta.columns, rows)
        res = suggest_mappings(prof, rows)
        assert res["stats"]["auto_mapped_pct"] >= 70, key  # PoC success criterion
        got = {s["source"]: s["target"] for s in res["suggestions"] if not s.get("derived_from") and not s["composite"] and not s.get("one_to_many")}
        for src, tgt in EXPECTED[key].items():
            assert got.get(src) == tgt, (key, src, got.get(src))


def test_composites_and_units(sample_files):
    meta, rows = read_sample(sample_files["correspondent"], 300)
    res = suggest_mappings(profile_rows(meta.columns, rows), rows)
    targets = {s["target"]: s for s in res["suggestions"]}
    assert targets["borrower_last_name"]["source"] == "Borrower Name" and targets["borrower_last_name"]["composite"]
    assert targets["property_zip"]["transform"][0]["op"] == "parse_address"
    meta, rows = read_sample(sample_files["sub_servicing"], 300)
    res = suggest_mappings(profile_rows(meta.columns, rows), rows)
    assert res["stats"]["cents_detected"]
    amt = next(s for s in res["suggestions"] if s["target"] == "original_loan_amount")
    assert any(st["op"] == "cents_to_dollars" for st in amt["transform"])


def test_pii_detected_and_not_sampled(sample_files):
    meta, rows = read_sample(sample_files["pcg_retail"], 300)
    prof = profile_rows(meta.columns, rows)
    ssn = next(c for c in prof["columns"] if c["name"] == "BorrowerSSN")
    assert ssn["pii_type"] == "SSN" and ssn["samples"] == []
    loan = next(c for c in prof["columns"] if c["name"] == "LoanID")
    assert loan["pii_type"] is None


def test_mapping_workflow_gates(sample_files):
    import pytest

    from lbp.mapping import service as ms

    reg = ms.register_source("pcg", sample_files["pcg_retail"], "analyst1")
    with pytest.raises(ms.MappingError):
        ms.submit(reg["mapping_id"], "analyst1")  # nothing reviewed yet
    ms.accept_all(reg["mapping_id"], "analyst1", 0.0)
    ms.update_field(reg["mapping_id"], "interest_rate", "override", "analyst1", transform=[{"op": "to_decimal"}])
    ms.submit(reg["mapping_id"], "analyst1")
    with pytest.raises(ms.MappingError):
        ms.approve(reg["mapping_id"], "analyst1", ["sme"])  # same person
    with pytest.raises(ms.MappingError):
        ms.approve(reg["mapping_id"], "bob", ["analyst"])  # not an SME
    m = ms.approve(reg["mapping_id"], "sme1", ["sme"])
    assert m["status"] == "approved" and m["source"]["status"] == "live"


def test_field_inspect_trace_and_dq(onboarded):
    from lbp.mapping.inspect import field_inspect, mapping_dq

    mid = onboarded["bulk_acquisition"]["mapping_id"]
    out = field_inspect(mid, "property_state")
    assert out["steps"] and any(s["op"] == "lookup" for s in out["steps"])
    ex = out["examples"][0]
    assert ex["inputs"] and (ex["steps"] or ex["error"])
    assert {c["id"] for c in out["schema_checks"]} >= {"required", "type", "codes"}
    assert any(r["rule_id"] == "R005" for r in out["dq_rules"])
    # PII never leaves unmasked
    ssn = field_inspect(mid, "borrower_ssn")
    assert all(str(e["output"]).startswith("***") or e["output"] in (None, "") for e in ssn["examples"])
    # testing an unsaved edit: removing the lookup breaks the code-list check
    broken = field_inspect(mid, "property_state", transform=[{"op": "upper"}])
    codes = next(c for c in broken["schema_checks"] if c["id"] == "codes")
    assert codes["failed"] > 0
    dq = mapping_dq(mid)
    assert len(dq["rules"]) >= 22 and all("failed" in r for r in dq["rules"])


def test_one_source_many_targets_and_retarget(sample_files):
    import pytest

    from lbp.mapping import service as ms
    from lbp.mapping.transforms import compile_mapping

    reg = ms.register_source("pcg", sample_files["pcg_retail"], "analyst1")
    mid = reg["mapping_id"]
    # engine offers curated 1:N suggestions below auto-accept
    m = ms.get_mapping(mid)
    extra = next(f for f in m["fields"] if f["target"] == "original_interest_rate")
    assert extra["source"] == "NoteRate" and extra["one_to_many"] and extra["status"] == "needs_review"
    # analyst maps one column to an additional target (1:N)
    sug = ms.suggest_for(mid, ["LoanID"], "investor_loan_number")
    assert sug["already_feeds"] == {"LoanID": ["loan_number"]} and sug["transform"]
    f = ms.add_field(mid, "investor_loan_number", "analyst1", ["LoanID"], sug["transform"])
    assert f["one_to_many"]
    # re-point a mapping at a different target; cast is re-derived for the new type
    moved = ms.retarget_field(mid, "borrower_home_phone", "borrower_cell_phone", "analyst1")
    assert moved["target"] == "borrower_cell_phone" and moved["retargeted_from"] == "borrower_home_phone"
    with pytest.raises(ms.MappingError):
        ms.retarget_field(mid, "borrower_cell_phone", "loan_number", "analyst1")  # already mapped
    ms.update_field(mid, "investor_loan_number", "remove", "analyst1")
    ms.add_field(mid, "investor_loan_number", "analyst1", ["LoanID"], sug["transform"])
    rec, errs = compile_mapping([{**x, "status": "accepted"} for x in ms.get_mapping(mid)["fields"]])({"LoanID": "PCG00000009", "NoteRate": "6.5", "HomePhone": "2125551234"})
    assert rec["loan_number"] == rec["investor_loan_number"] == "PCG00000009"
    assert rec["interest_rate"] == rec["original_interest_rate"] == 6.5
    assert rec["borrower_cell_phone"] == "2125551234" and "borrower_home_phone" not in rec
