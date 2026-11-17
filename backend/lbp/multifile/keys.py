"""Join-key normalization: the single definition shared by every join engine.

`normalize` applies to the join key only; stored values keep their original form. Empty or null
parts never match (they normalize to None). Pure and dependency-free.
"""
from __future__ import annotations

from collections.abc import Sequence

KEY_SEP = "\x1f"


def normalize_part(v: str | None, ops: Sequence[str]) -> str | None:
    """Apply `ops` in the order given; None when the input is null or the result is empty."""
    if v is None:
        return None
    s = str(v)
    for op in ops:
        if op == "trim":
            s = s.strip()
        elif op == "strip_leading_zeros":
            if s:
                s = s.lstrip("0") or "0"
        elif op == "upper":
            s = s.upper()
        else:
            raise ValueError(f"unknown normalizer: {op!r}")
    # A blank value never matches, even when no trim op is declared.
    if not s.strip():
        return None
    return s


def normalize_key(parts: Sequence[str | None], ops: Sequence[str]) -> tuple[str, ...] | None:
    """Normalize every part; None if any part is null or empty."""
    out: list[str] = []
    for p in parts:
        n = normalize_part(p, ops)
        if n is None:
            return None
        out.append(n)
    return tuple(out)


def key_text(key: tuple[str, ...]) -> str:
    """Stable single-string form of a (composite) key, used as the SQL join column."""
    return KEY_SEP.join(key)
