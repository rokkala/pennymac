from lbp.multifile.keys import key_text, normalize_key, normalize_part

ALL = ("trim", "strip_leading_zeros", "upper")


def test_trim_upper_strip_zeros():
    assert normalize_part(" 0012ab ", ALL) == "12AB"


def test_all_zero_becomes_single_zero():
    assert normalize_part("000", ALL) == "0"


def test_empty_and_null_never_match():
    assert normalize_part("", ALL) is None
    assert normalize_part("  ", ALL) is None
    assert normalize_part(None, ALL) is None
    assert normalize_key(("a", ""), ALL) is None
    assert normalize_key(("a", None), ALL) is None
    assert normalize_key(("a", "b"), ALL) == ("A", "B")


def test_composite_key_text_is_unambiguous():
    assert key_text(("a", "bc")) != key_text(("ab", "c"))


def test_every_declared_normalizer_is_implemented_and_others_rejected():
    import pytest

    from lbp.multifile.layout import NORMALIZERS

    for op in NORMALIZERS:
        assert normalize_part(" 0a ", (op,)) is not None
    with pytest.raises(ValueError):
        normalize_part("x", ("trim", "lower"))
    with pytest.raises(ValueError):
        normalize_part(None, ("bogus",))


def test_op_order_matters():
    assert normalize_part(" 0012", ("strip_leading_zeros", "trim")) == "0012"
    assert normalize_part(" 0012", ("trim", "strip_leading_zeros")) == "12"


def test_blank_with_empty_ops_never_matches_and_values_unchanged():
    assert normalize_part("", ()) is None
    assert normalize_part("   ", ()) is None
    assert normalize_part(" a ", ()) == " a "


def test_non_str_and_unicode_input():
    assert normalize_part(12, ALL) == "12"
    assert normalize_part("ß", ("upper",)) == "SS"


def test_key_text_positive():
    assert key_text(("a",)) == "a"
    assert key_text(("a", "b")) == key_text(("a", "b"))
    assert key_text(("a", "b")) == "a\x1fb"
