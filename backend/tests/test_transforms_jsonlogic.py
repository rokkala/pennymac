from lbp.mapping.transforms import apply_field, compile_mapping
from lbp.rules.jsonlogic import apply, validate


def test_casts_and_lookups():
    assert apply_field({"sources": ["a"], "transform": [{"op": "to_decimal"}]}, {"a": "$1,234.50"}) == 1234.5
    assert apply_field({"sources": ["a"], "transform": [{"op": "to_date"}]}, {"a": "20240115"}) == "2024-01-15"
    assert apply_field({"sources": ["a"], "transform": [{"op": "to_date", "format": "%m/%d/%Y"}]}, {"a": "01/15/2024"}) == "2024-01-15"
    assert apply_field({"sources": ["a"], "transform": [{"op": "lookup", "table": "state_name_to_code"}]}, {"a": "Texas"}) == "TX"
    assert apply_field({"sources": ["a"], "transform": [{"op": "cents_to_dollars"}]}, {"a": "12345"}) == 123.45
    assert apply_field({"sources": ["a"], "transform": [{"op": "to_decimal"}, {"op": "normalize_rate"}]}, {"a": "0.065"}) == 6.5
    assert apply_field({"sources": ["a"], "transform": [{"op": "to_bool"}]}, {"a": "Yes"}) is True


def test_composite_split_and_concat():
    row = {"n": "Garcia, Maria", "addr": "12 Oak St, Plano, TX 75024", "f": "Maria", "l": "Garcia"}
    assert apply_field({"sources": ["n"], "transform": [{"op": "split", "delimiter": ",", "index": 1}]}, row) == "Maria"
    assert apply_field({"sources": ["addr"], "transform": [{"op": "parse_address", "part": "zip"}]}, row) == "75024"
    assert apply_field({"sources": ["f", "l"], "transform": [{"op": "concat", "separator": " "}]}, row) == "Maria Garcia"


def test_transform_errors_are_captured_not_raised():
    run = compile_mapping([{"target": "note_date", "sources": ["d"], "transform": [{"op": "to_date"}], "status": "accepted"}])
    rec, errs = run({"d": "not a date"})
    assert rec["note_date"] is None and "note_date" in errs


def test_default_injection():
    assert apply_field({"sources": ["a"], "transform": [{"op": "default", "value": "CNV"}]}, {"a": ""}) == "CNV"


def test_jsonlogic_ops():
    d = {"a": 5, "b": "2024-01-01", "c": "2024-03-01", "s": "ABC123"}
    assert apply({"<=": [1, {"var": "a"}, 10]}, d)
    assert apply({"days_between": [{"var": "b"}, {"var": "c"}]}, d) == 60
    assert apply({"matches": [{"var": "s"}, "[A-Z]{3}\\d{3}"]}, d)
    assert apply({"if": [{"==": [{"var": "a"}, 5]}, "yes", "no"]}, d) == "yes"
    assert apply({"missing": ["a", "zz"]}, d) == ["zz"]
    assert round(apply({"pmt": [6.5, 360, 400000]}, d), 2) == 2528.27
    assert validate({"<": [{"var": "not_a_field"}, 1]}) == ["unknown field: not_a_field"]
    assert validate({"nope": [1]})


def test_jsonlogic_guided_authoring_ops():
    d = {"a": 1, "b": "", "c": "x", "d1": "2024-01-01", "d2": "2024-06-01"}
    assert apply({"xor": [True, False, False]}, d) is True
    assert apply({"xor": [True, True]}, d) is False
    assert apply({"xor": [False, False]}, d) is False
    assert apply({"all_present": [{"var": "a"}, {"var": "c"}]}, d) is True
    assert apply({"all_present": [{"var": "a"}, {"var": "b"}]}, d) is False
    assert apply({"date_before": [{"var": "d1"}, {"var": "d2"}]}, d) is True
    assert apply({"date_after": [{"var": "d2"}, {"var": "d1"}]}, d) is True
    assert apply({"date_before": [{"var": "d2"}, {"var": "d1"}]}, d) is False
    assert not validate({"xor": [{"var": "interest_rate"}, False]})
