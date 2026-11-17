"""Local join engine: a master file plus detail files -> one joined CSV row per master row.

Bounded memory, whatever the file sizes: nothing is held per file, only per batch of rows.

    pass 1   stream the master; count its normalized keys per relation into SQLite (`master_keys`)
    load     stream each detail into its own SQLite table `(row_no, nkey, data)`, indexed on (nkey, row_no)
    orphans  anti-join of each detail table against `master_keys` (detail rows with no master)
    pass 2   stream the master again in file order; for each relation look up the detail rows for the
             row's key in detail file order and let the relation's mode handler turn them into columns

The SQLite database lives in `tmp_dir` and is removed afterwards. Row numbers are 1-based data-row
indexes (header excluded, blank lines skipped, as `iter_rows` yields them).
"""
from __future__ import annotations

import contextlib
import csv
import json
import os
import sqlite3
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lbp.ingestion.parser import ParseOptions, iter_rows
from lbp.mapping.transforms import TRUE_VALUES, TransformError, _date
from lbp.multifile.keys import KEY_SEP, key_text, normalize_key
from lbp.multifile.layout import LayoutError, normalize_layout, validate_layout
from lbp.rules.jsonlogic import _truthy, compile_logic

BATCH_ROWS = 5000
JOIN01_ORPHAN = "JOIN01"
# The join does not care how files are paired into a set; validate the layout with a readiness policy
# that imposes no filename rules, so a layout valid under its real readiness is never rejected here.
_NEUTRAL_READINESS = {"pairing": "window_minutes", "window_minutes": 1, "on_timeout": "alert_only"}


@dataclass
class RoleStats:
    rows_in: int = 0
    matched: int = 0
    orphaned: int = 0
    rejected: int = 0


@dataclass
class JoinResult:
    columns: list[str]
    rows_out: int
    per_role: dict[str, RoleStats]
    exceptions_path: Path
    exception_counts: dict[str, int]
    master_match_rate: float
    detail_match_rate: dict[str, float]
    blocked: str | None


class MergeMode:
    """merge (1:1): the detail's columns added to the master row as `role.column`."""

    def __init__(self, role: str, relation: dict, detail_columns: list[str]):
        self.columns = [f"{role}.{c}" for c in detail_columns]

    def reduce(self, rows: Iterator[list[str]]) -> tuple[list[str], int]:
        """(output values, number of detail rows seen). The first row in detail file order wins."""
        first = next(rows, None)
        if first is None:
            return [""] * len(self.columns), 0
        return first, 1 + sum(1 for _ in rows)


def _blank(v: str | None) -> bool:
    return v is None or v.strip() == ""


def _dec(v: str) -> Decimal | None:
    """A finite Decimal from a numeric string ($ and thousands separators allowed), else None."""
    try:
        d = Decimal(v.strip().replace("$", "").replace(",", ""))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _fmt_decimal(d: Decimal) -> str:
    """Plain notation, no exponent and no trailing zeros (so 0.1+0.2 gives 0.3, 100+200 gives 300)."""
    d = d.normalize()
    return "0" if d == 0 else format(d, "f")


class _SortKey:
    """Total order over a row's order_by values: per key text/Decimal/date, null or unparseable last
    whatever the direction, ties broken by detail file order (the row index)."""

    __slots__ = ("parts", "idx")

    def __init__(self, parts: list[tuple[bool, object, bool]], idx: int):
        self.parts, self.idx = parts, idx

    def __lt__(self, other: _SortKey) -> bool:
        for (an, av, desc), (bn, bv, _) in zip(self.parts, other.parts, strict=True):
            if an != bn:
                return bn  # a non-null value sorts before a null one in both directions
            if an or av == bv:
                continue
            return (av > bv) if desc else (av < bv)
        return self.idx < other.idx


def _sort_value(kind: str, v: str | None) -> object | None:
    if _blank(v):
        return None
    if kind == "number":
        return _dec(v)
    if kind == "date":
        try:
            return datetime.strptime(_date(v), "%Y-%m-%d").date()
        except (TransformError, ValueError):
            return None
    return v


class _Acc:
    """Streaming state of one aggregate column over one master's detail rows (file order)."""

    def __init__(self, spec: dict, columns: list[str], tag: str):
        self.op, self.name, self.src = spec["op"], spec["as"], spec.get("col")
        self.tag = tag
        self.where = compile_logic(spec["where"]) if spec.get("where") else None
        self.order = [(k["col"], bool(k.get("desc", False)), k.get("type", "text")) for k in spec.get("order_by") or []]
        needed = ([self.src] if self.src else []) + [c for c, _, _ in self.order]
        missing = [c for c in needed if c not in columns]
        if missing:
            raise LayoutError(f"{tag}: aggregate column {self.name} uses column(s) {missing} not in the detail file")
        self.pos = {c: i for i, c in enumerate(columns)}
        self.reset()

    def reset(self) -> None:
        self.n = 0
        self.total = Decimal(0)
        self.seen_value = False
        self.lo_dec: tuple[Decimal, str] | None = None
        self.hi_dec: tuple[Decimal, str] | None = None
        self.lo_txt: str | None = None
        self.hi_txt: str | None = None
        self.numeric = True
        self.any_true = False
        self.pick: tuple[_SortKey, str] | None = None  # first/last by order, or file order
        self.distinct: list[str] = []
        self.distinct_seen: set[str] = set()
        self.keyed: list[tuple[_SortKey, str]] = []

    def _key(self, row: list[str], idx: int) -> _SortKey:
        return _SortKey([(v is None, v, desc) for v, desc in
                         ((_sort_value(t, row[self.pos[c]]), d) for c, d, t in self.order)], idx)

    def add(self, row: list[str], rowdict: dict[str, str] | None, idx: int) -> None:
        if self.where is not None and not _truthy(self.where(rowdict)):
            return
        self.n += 1
        if self.src is None:
            return
        v = row[self.pos[self.src]]
        if _blank(v):
            return
        self.seen_value = True
        op = self.op
        if op == "sum":
            d = _dec(v)
            if d is None:
                raise LayoutError(f"{self.tag}: aggregate column {self.name}: non-numeric value in {self.src}")
            self.total += d
        elif op in ("min", "max"):
            d = _dec(v)
            if d is None:
                self.numeric = False
            else:
                if self.lo_dec is None or d < self.lo_dec[0]:
                    self.lo_dec = (d, v)
                if self.hi_dec is None or d > self.hi_dec[0]:
                    self.hi_dec = (d, v)
            if self.lo_txt is None or v < self.lo_txt:
                self.lo_txt = v
            if self.hi_txt is None or v > self.hi_txt:
                self.hi_txt = v
        elif op == "any":
            self.any_true = self.any_true or v.strip().lower() in TRUE_VALUES
        elif op in ("first", "last"):
            key = self._key(row, idx)
            if self.pick is None or (key < self.pick[0] if op == "first" else self.pick[0] < key):
                self.pick = (key, v)
        elif op == "concat_distinct":
            if self.order:
                self.keyed.append((self._key(row, idx), v))
            elif v not in self.distinct_seen:
                self.distinct_seen.add(v)
                self.distinct.append(v)

    def result(self) -> str:
        op = self.op
        if op == "count":
            return str(self.n)
        if not self.seen_value:
            return ""
        if op == "sum":
            return _fmt_decimal(self.total)
        if op == "min":
            return self.lo_dec[1] if self.numeric and self.lo_dec else self.lo_txt or ""
        if op == "max":
            return self.hi_dec[1] if self.numeric and self.hi_dec else self.hi_txt or ""
        if op == "any":
            return "true" if self.any_true else "false"
        if op in ("first", "last"):
            return self.pick[1] if self.pick else ""
        if self.order:
            seen: set[str] = set()
            out = []
            for _, v in sorted(self.keyed, key=lambda kv: kv[0]):
                if v not in seen:
                    seen.add(v)
                    out.append(v)
            return "|".join(out)
        return "|".join(self.distinct)


class AggregateMode:
    """aggregate (1:N): a master's detail rows reduced to the declared columns, named by `as`. Streams the
    rows (no per-master buffer except concat_distinct with order_by, which holds that master's values)."""

    def __init__(self, role: str, relation: dict, detail_columns: list[str]):
        specs = (relation.get("aggregate") or {}).get("columns") or []
        if not specs:
            raise LayoutError(f"relation {role}->{relation.get('to')}: aggregate needs at least one column")
        self.accs = [_Acc(c, detail_columns, f"relation {role}->{relation.get('to')}") for c in specs]
        self.columns = [a.name for a in self.accs]
        self._detail_columns = detail_columns
        self._needs_dict = any(a.where is not None for a in self.accs)

    def reduce(self, rows: Iterator[list[str]]) -> tuple[list[str], int]:
        for a in self.accs:
            a.reset()
        n = 0
        for n, row in enumerate(rows, start=1):  # noqa: B007 - n is the row count after the loop
            rd = dict(zip(self._detail_columns, row, strict=True)) if self._needs_dict else None
            for a in self.accs:
                a.add(row, rd, n)
        return [a.result() for a in self.accs], n


# Mode name -> handler class with `.columns` and `.reduce(rows)`.
MODES: dict[str, Callable[..., object]] = {"merge": MergeMode, "aggregate": AggregateMode}


@dataclass
class _Relation:
    idx: int
    role: str
    spec: dict
    parent_cols: list[str]
    detail_cols: list[str]
    ops: list[str]
    table: str
    columns: list[str] = field(default_factory=list)  # detail file header
    handler: MergeMode | AggregateMode | None = None

    def master_key(self, row: dict[str, str]) -> str | None:
        k = normalize_key([row.get(c) for c in self.parent_cols], self.ops)
        return key_text(k) if k is not None else None

    def detail_key(self, row: dict[str, str]) -> str | None:
        k = normalize_key([row.get(c) for c in self.detail_cols], self.ops)
        return key_text(k) if k is not None else None


class _Exceptions:
    """Writes `{"code","role","row_number","key","message","raw"}` per line and counts by code."""

    def __init__(self, path: Path):
        self.path = path
        self.counts: dict[str, int] = {}
        self._f = path.open("w", encoding="utf-8")

    def add(self, code: str, role: str, row_number: int, nkey: str | None, message: str, raw: dict) -> None:
        key = nkey.replace(KEY_SEP, "|") if nkey is not None else None
        rec = {"code": code, "role": role, "row_number": row_number, "key": key, "message": message, "raw": raw}
        self._f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.counts[code] = self.counts.get(code, 0) + 1

    def close(self) -> None:
        self._f.close()


def _parse_options(role: str, file_spec: dict, overrides: dict[str, dict]) -> ParseOptions:
    opts = {**(file_spec.get("parse_options") or {}), **(overrides.get(role) or {})}
    allowed = {f.name for f in fields(ParseOptions)}
    unknown = sorted(set(opts) - allowed)
    if unknown:
        raise LayoutError(f"unknown parse option(s) for {role}: {unknown}; use {sorted(allowed)}")
    return ParseOptions(**opts)


def _require_columns(role: str, header: list[str], needed: list[str]) -> None:
    missing = [c for c in needed if c not in header]
    if missing:
        raise LayoutError(f"{role} file has no column(s) {missing}")


def _relations(lay: dict, inputs: dict[str, Path]) -> list[_Relation]:
    errs = validate_layout(lay, _NEUTRAL_READINESS)
    if errs:
        raise LayoutError("; ".join(errs))
    if "master" not in inputs:
        raise LayoutError("no input file for role master")
    rels = []
    for i, r in enumerate(lay["relations"]):
        tag = f"relation {r['detail']}->{r['to']}"
        if r["to"] != "master":
            raise LayoutError(f"{tag}: details can only join the master in this version")
        if r["mode"] not in MODES:
            raise LayoutError(f"{tag}: mode {r['mode']} is not supported by the join engine yet")
        if r["detail"] not in inputs:
            raise LayoutError(f"no input file for role {r['detail']}")
        norm = r["normalize"] if isinstance(r["normalize"], list) else [r["normalize"]]
        rels.append(_Relation(idx=i, role=r["detail"], spec=r, parent_cols=[p["parent"] for p in r["on"]],
                              detail_cols=[p["detail"] for p in r["on"]], ops=norm, table=f"detail_{i}"))
    return rels


def _batched_insert(conn: sqlite3.Connection, sql: str, rows: Iterator[tuple]) -> None:
    batch: list[tuple] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= BATCH_ROWS:
            conn.executemany(sql, batch)
            batch.clear()
    if batch:
        conn.executemany(sql, batch)


def _open_db(tmp_dir: Path) -> tuple[sqlite3.Connection, Path]:
    fd, name = tempfile.mkstemp(prefix="join_", suffix=".sqlite", dir=tmp_dir)
    os.close(fd)
    conn = sqlite3.connect(name)
    # Scratch data: no journal or fsync; a bounded page cache keeps memory flat for any file size.
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=FILE")
    conn.execute("PRAGMA cache_size=-16000")
    return conn, Path(name)


def _rate(num: int, den: int) -> float:
    return num / den if den else 1.0


def join_files(layout: dict, inputs: dict[str, Path], parse_options: dict[str, dict], out_path: Path,
               tmp_dir: Path) -> JoinResult:
    """Join `inputs` (role -> file) per `layout`; write the joined CSV to `out_path` in master file order and
    the join exceptions as JSONL beside it. Raises LayoutError when the layout or the files' headers cannot
    be joined."""
    lay = normalize_layout(layout)
    rels = _relations(lay, inputs)
    master_spec = next(f for f in lay["files"] if f.get("role") == "master")
    master_opts = _parse_options("master", master_spec, parse_options or {})
    files_by_role = {f.get("role"): f for f in lay["files"]}
    out_path = Path(out_path)
    exc_path = out_path.with_name(out_path.stem + ".exceptions.jsonl")
    per_role = {"master": RoleStats(), **{r.role: RoleStats() for r in rels}}

    conn, db_path = _open_db(Path(tmp_dir))
    exc = _Exceptions(exc_path)
    try:
        # Pass 1: master key counts per relation (normalize can differ per relation).
        conn.execute("CREATE TABLE master_rows (rel INTEGER, nkey TEXT)")
        meta, rows = iter_rows(Path(inputs["master"]), master_opts)
        master_cols = list(meta.columns)
        for r in rels:
            _require_columns("master", master_cols, r.parent_cols)
        _require_columns("master", master_cols, list(master_spec.get("key") or []))

        def master_keys() -> Iterator[tuple]:
            for row in rows:
                per_role["master"].rows_in += 1
                for r in rels:
                    k = r.master_key(row)
                    if k is not None:
                        yield (r.idx, k)

        _batched_insert(conn, "INSERT INTO master_rows VALUES (?, ?)", master_keys())
        conn.execute("CREATE TABLE master_keys AS SELECT rel, nkey, COUNT(*) AS cnt FROM master_rows GROUP BY rel, nkey")
        conn.execute("CREATE UNIQUE INDEX ix_master_keys ON master_keys (rel, nkey)")
        conn.execute("DROP TABLE master_rows")

        # Details: one table per relation; rows stored as a JSON list in header order.
        for r in rels:
            dmeta, drows = iter_rows(Path(inputs[r.role]), _parse_options(r.role, files_by_role.get(r.role) or {},
                                                                         parse_options or {}))
            r.columns = list(dmeta.columns)
            _require_columns(r.role, r.columns, r.detail_cols)
            r.handler = MODES[r.spec["mode"]](r.role, r.spec, r.columns)
            conn.execute(f"CREATE TABLE {r.table} (row_no INTEGER, nkey TEXT, data TEXT)")

            def detail_rows(r: _Relation = r, drows: Iterator[dict[str, str]] = drows) -> Iterator[tuple]:
                for n, row in enumerate(drows, start=1):
                    yield (n, r.detail_key(row), json.dumps([row[c] for c in r.columns], ensure_ascii=False))

            _batched_insert(conn, f"INSERT INTO {r.table} VALUES (?, ?, ?)", detail_rows())
            # Built after loading (faster than maintaining it per insert); covers lookup + file-order sort.
            conn.execute(f"CREATE INDEX ix_{r.table} ON {r.table} (nkey, row_no)")
            st = per_role[r.role]
            st.rows_in = conn.execute(f"SELECT COUNT(*) FROM {r.table}").fetchone()[0]
            # Task 5: null/empty keys become JOIN05; until then they are counted as rejected.
            st.rejected = conn.execute(f"SELECT COUNT(*) FROM {r.table} WHERE nkey IS NULL").fetchone()[0]
            orphan_sql = (f"SELECT row_no, nkey, data FROM {r.table} d WHERE nkey IS NOT NULL AND NOT EXISTS "
                          f"(SELECT 1 FROM master_keys m WHERE m.rel = ? AND m.nkey = d.nkey) ORDER BY row_no")
            for row_no, nkey, data in conn.execute(orphan_sql, (r.idx,)):
                st.orphaned += 1
                if r.spec["on_orphan_detail"] == "exception":
                    exc.add(JOIN01_ORPHAN, r.role, row_no, nkey, f"{r.role} row has no matching master row",
                            dict(zip(r.columns, json.loads(data), strict=True)))
            st.matched = st.rows_in - st.orphaned - st.rejected

        columns = master_cols + [c for r in rels for c in r.handler.columns]
        dupes = sorted({c for c in columns if columns.count(c) > 1})
        if dupes:
            raise LayoutError(f"output column(s) {dupes} produced more than once")

        # Pass 2: master again, in file order; details per key in detail file order.
        rows_out = 0
        _, rows = iter_rows(Path(inputs["master"]), master_opts)
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(columns)
            for row in rows:
                out = [row[c] for c in master_cols]
                any_match = False
                for r in rels:
                    k = r.master_key(row)
                    found: Iterator[list[str]] = iter(())
                    if k is not None:
                        cur = conn.execute(f"SELECT data FROM {r.table} WHERE nkey = ? ORDER BY row_no", (k,))
                        found = (json.loads(d) for (d,) in cur)
                    values, n = r.handler.reduce(found)
                    any_match = any_match or n > 0
                    out.extend(values)
                per_role["master"].matched += any_match
                w.writerow(out)
                rows_out += 1
    finally:
        exc.close()
        conn.close()
        with contextlib.suppress(FileNotFoundError):
            db_path.unlink()

    m = per_role["master"]
    return JoinResult(
        columns=columns,
        rows_out=rows_out,
        per_role=per_role,
        exceptions_path=exc_path,
        exception_counts=dict(exc.counts),
        master_match_rate=_rate(m.matched, m.rows_in),
        detail_match_rate={r.role: _rate(per_role[r.role].matched, per_role[r.role].rows_in) for r in rels},
        blocked=None,  # Task 5: min_match_rate gate
    )
