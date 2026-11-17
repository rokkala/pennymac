"""Join scale (Task 15): a detail file 10x the master joins with bounded memory.

Slow: deselected by default (pyproject addopts `-m "not slow"`); run with

    pytest -m slow tests/test_join_scale.py

LBP_SCALE_ROWS sets the number of master rows (default 1,000,000; the detail file has 10x as many rows).
"""
from __future__ import annotations

import csv
import os
import resource
import sys
import time
from pathlib import Path

import pytest

from lbp.multifile.joiner import join_files

MASTERS = int(os.environ.get("LBP_SCALE_ROWS", "1000000"))
DETAILS_PER_MASTER = 10
CHUNK = 50_000
MAX_SECONDS = 1800
MAX_RSS_BYTES = 1024**3

LAYOUT = {
    "files": [
        {"role": "master", "entity": "loan", "name_pattern": r"m_(?P<date>\d+)\.csv", "key": ["id"], "required": True},
        {"role": "items", "name_pattern": r"i_(?P<date>\d+)\.csv", "required": True},
    ],
    "relations": [{"detail": "items", "to": "master", "on": [{"parent": "id", "detail": "ref"}],
                   "normalize": ["trim", "strip_leading_zeros", "upper"], "mode": "aggregate", "on_orphan_detail": "drop",
                   "aggregate": {"columns": [{"as": "total", "op": "sum", "col": "amt"}, {"as": "n", "op": "count"}]}}],
}


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # macOS reports bytes, Linux KiB


def _write_master(path: Path, n: int) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "amount"])
        for start in range(0, n, CHUNK):
            w.writerows([f"L{i:09d}", i % 1000] for i in range(start, min(n, start + CHUNK)))


def _write_details(path: Path, n: int) -> None:
    """Detail rows in file order master 0..n-1, `DETAILS_PER_MASTER` rows each; the ref is zero-padded so the
    key normalization does work on every row. amt = j + 1, so each master's total is 55 and n is 10."""
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ref", "amt"])
        for start in range(0, n, CHUNK // DETAILS_PER_MASTER):
            stop = min(n, start + CHUNK // DETAILS_PER_MASTER)
            w.writerows([f"0L{i:09d}", j + 1] for i in range(start, stop) for j in range(DETAILS_PER_MASTER))


@pytest.mark.slow
def test_join_scale(tmp_path: Path):
    master, details, out = tmp_path / "m.csv", tmp_path / "i.csv", tmp_path / "joined.csv"
    t0 = time.monotonic()
    _write_master(master, MASTERS)
    _write_details(details, MASTERS)
    gen_s = time.monotonic() - t0

    t1 = time.monotonic()
    res = join_files(LAYOUT, {"master": master, "items": details}, {}, out, tmp_path)
    join_s = time.monotonic() - t1
    rss = _peak_rss_bytes()
    print(f"\njoin scale: {MASTERS:,} masters x {MASTERS * DETAILS_PER_MASTER:,} details; generate {gen_s:.1f}s, "
          f"join {join_s:.1f}s, peak RSS {rss / 1024**2:.0f} MiB")

    assert res.rows_out == MASTERS
    assert res.per_role["items"].rows_in == MASTERS * DETAILS_PER_MASTER
    assert res.per_role["items"].orphaned == 0 and res.master_match_rate == 1.0
    with out.open(newline="") as f:
        r = csv.reader(f)
        header = next(r)
        first = next(r)
    row = dict(zip(header, first, strict=True))
    assert row["id"] == "L000000000" and row["total"] == "55" and row["n"] == "10"
    assert join_s < MAX_SECONDS
    assert rss < MAX_RSS_BYTES
