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
