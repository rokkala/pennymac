"""Config-driven source file parsing (CSV / TXT / Excel) with format auto-detection.

Rows are returned as dicts of raw strings. Typing happens later in the transform step so
that the original value is always available for exception handling and audit.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

DELIMITERS = [",", "|", "\t", ";", "~"]


@dataclass
class ParseOptions:
    format: str | None = None  # csv | txt | xlsx  (None = auto-detect)
    delimiter: str | None = None
    sheet: str | int | None = 0
    header_row: int = 0
    encoding: str = "utf-8-sig"


@dataclass
class ParsedFile:
    columns: list[str]
    format: str
    delimiter: str | None
    row_count: int | None = None


def detect_format(path: Path, head: bytes | None = None) -> str:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return "xlsx"
    head = head if head is not None else path.open("rb").read(4)
    if head[:2] == b"PK":  # zip container -> xlsx even with odd extension
        return "xlsx"
    return "txt" if suffix in (".txt", ".dat", ".psv") else "csv"


def sniff_delimiter(sample: str) -> str:
    first_line = sample.splitlines()[0] if sample else ""
    counts = {d: first_line.count(d) for d in DELIMITERS}
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        return ","
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(DELIMITERS)).delimiter
    except csv.Error:
        return best


def _clean_header(h: object, idx: int) -> str:
    s = str(h).strip() if h is not None else ""
    return s or f"column_{idx + 1}"


def iter_rows(path: Path, opts: ParseOptions | None = None) -> tuple[ParsedFile, Iterator[dict[str, str]]]:
    """Return file metadata plus a lazy row iterator, so 1M-row files are never fully in memory."""
    opts = opts or ParseOptions()
    fmt = opts.format or detect_format(path)
    if fmt == "xlsx":
        return _iter_excel(path, opts)
    with path.open("r", encoding=opts.encoding, errors="replace") as f:
        sample = f.read(64 * 1024)
    delim = opts.delimiter or sniff_delimiter(sample)

    f = path.open("r", encoding=opts.encoding, errors="replace", newline="")
    reader = csv.reader(f, delimiter=delim)
    for _ in range(opts.header_row):
        next(reader, None)
    header = [_clean_header(h, i) for i, h in enumerate(next(reader, []))]
    meta = ParsedFile(columns=header, format=fmt, delimiter=delim)

    def gen():
        try:
            for raw in reader:
                if not raw or all(not c.strip() for c in raw):
                    continue
                if len(raw) < len(header):
                    raw = raw + [""] * (len(header) - len(raw))
                yield {header[i]: raw[i].strip() for i in range(len(header))}
        finally:
            f.close()

    return meta, gen()


def _iter_excel(path: Path, opts: ParseOptions):
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[opts.sheet] if isinstance(opts.sheet, int) else wb[opts.sheet]
    rows = ws.iter_rows(values_only=True)
    for _ in range(opts.header_row):
        next(rows, None)
    header = [_clean_header(h, i) for i, h in enumerate(next(rows, ()))]
    meta = ParsedFile(columns=header, format="xlsx", delimiter=None)

    def fmt_cell(v) -> str:
        if v is None:
            return ""
        if hasattr(v, "strftime"):
            return v.strftime("%m/%d/%Y")
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v).strip()

    def gen():
        try:
            for raw in rows:
                if raw is None or all(c is None or str(c).strip() == "" for c in raw):
                    continue
                yield {header[i]: fmt_cell(raw[i]) if i < len(raw) else "" for i in range(len(header))}
        finally:
            wb.close()

    return meta, gen()


def read_sample(path: Path, n: int = 1000, opts: ParseOptions | None = None) -> tuple[ParsedFile, list[dict[str, str]]]:
    meta, it = iter_rows(path, opts)
    out = []
    for row in it:
        out.append(row)
        if len(out) >= n:
            break
    return meta, out


def read_bytes_sample(data: bytes, filename: str, n: int = 1000) -> tuple[ParsedFile, list[dict[str, str]]]:
    """Helper for Lambda handlers that receive an S3 object body."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
        tmp.write(data)
        p = Path(tmp.name)
    try:
        return read_sample(p, n)
    finally:
        p.unlink(missing_ok=True)


def to_csv_bytes(columns: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode()


def estimate_rows(path: Path) -> int:
    """Fast data-row estimate for progress / ETA (line count, or sheet dimension for Excel)."""
    if detect_format(path) == "xlsx":
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True)
        try:
            return max((wb.worksheets[0].max_row or 1) - 1, 0)
        finally:
            wb.close()
    n = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            n += chunk.count(b"\n")
    return max(n - 1, 0)
