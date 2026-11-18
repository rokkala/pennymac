"""Throwaway spike: JSONL → CSV on S3 → aws_s3.table_import_from_s3 timing.

Job params: --batch_id (for part listing), optional --LBP_SPIKE_MAX_ROWS (default 1000000).
Does not touch production sse_loans; uses UNLOGGED spike_* tables then drops them.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time

for _i, _a in enumerate(sys.argv[:-1]):
    if _a.startswith("--LBP_") or _a.startswith("--batch"):
        if _a.startswith("--") and _i + 1 < len(sys.argv):
            key = _a[2:]
            os.environ.setdefault(key if key.startswith("LBP_") else f"LBP_{key.upper()}", sys.argv[_i + 1])

from awsglue.utils import getResolvedOptions  # type: ignore  # noqa: E402
import boto3  # noqa: E402
from sqlalchemy import text  # noqa: E402

from lbp.store import db  # noqa: E402

args = getResolvedOptions(sys.argv, ["batch_id", "processed_bucket"])
batch_id = args["batch_id"]
bucket = args["processed_bucket"]
region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("LBP_AWS_REGION") or "ap-southeast-2"
max_rows = int(os.environ.get("LBP_SPIKE_MAX_ROWS", "1000000"))
prefix = f"bulk-load/{batch_id}/clean/"
csv_key = f"spike/s3-import/{batch_id}/sse_{max_rows}.csv"

s3 = boto3.client("s3", region_name=region)


def _list_sse_keys() -> list[str]:
    keys = []
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        for obj in resp.get("Contents") or []:
            if obj["Key"].endswith("/sse.jsonl"):
                keys.append(obj["Key"])
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    keys.sort()
    return keys


def _build_csv() -> tuple[list[str], int, float]:
    """Stream clean sse.jsonl → one CSV on S3. Returns (cols, rows, build_secs)."""
    t0 = time.time()
    keys = _list_sse_keys()
    if not keys:
        raise SystemExit(f"no clean sse.jsonl under s3://{bucket}/{prefix}")

    cols: list[str] | None = None
    rows = 0
    buf = io.StringIO()
    writer = None
    # Multipart-ish: accumulate chunks then put (1M flat rows ~ few hundred MB — single put OK for spike)
    for key in keys:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"]
        for raw in body.iter_lines():
            if not raw:
                continue
            rec = json.loads(raw)
            if cols is None:
                cols = sorted(rec.keys())
                writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
                writer.writeheader()
            # Flatten non-scalars for TEXT COPY/import
            flat = {c: (json.dumps(rec[c], default=str) if isinstance(rec.get(c), (dict, list)) else rec.get(c)) for c in cols}
            writer.writerow(flat)
            rows += 1
            if rows >= max_rows:
                break
        if rows >= max_rows:
            break

    assert cols and writer
    payload = buf.getvalue().encode("utf-8")
    s3.put_object(Bucket=bucket, Key=csv_key, Body=payload, ContentType="text/csv")
    return cols, rows, time.time() - t0


def _ensure_extensions(conn) -> None:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS aws_commons"))
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS aws_s3 CASCADE"))
    conn.commit()


def _import_aws_s3(conn, cols: list[str]) -> tuple[int, float, object]:
    col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
    conn.execute(text("DROP TABLE IF EXISTS spike_sse_import"))
    conn.execute(text(f"CREATE UNLOGGED TABLE spike_sse_import ({col_defs})"))
    conn.commit()
    col_list = ", ".join(cols)
    sql = text(
        """
        SELECT aws_s3.table_import_from_s3(
          'spike_sse_import',
          :cols,
          '(FORMAT CSV, HEADER true)',
          aws_commons.create_s3_uri(:bucket, :key, :region)
        )
        """
    )
    t0 = time.time()
    result = conn.execute(
        sql, {"cols": col_list, "bucket": bucket, "key": csv_key, "region": region}
    ).scalar()
    conn.commit()
    elapsed = time.time() - t0
    n = conn.execute(text("SELECT count(*) FROM spike_sse_import")).scalar()
    return int(n or 0), elapsed, result


def _import_stdin_copy(conn, cols: list[str]) -> tuple[int, float]:
    """Baseline: download CSV and COPY FROM STDIN (current-style path)."""
    conn.execute(text("DROP TABLE IF EXISTS spike_sse_stdin"))
    col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
    conn.execute(text(f"CREATE UNLOGGED TABLE spike_sse_stdin ({col_defs})"))
    conn.commit()
    obj = s3.get_object(Bucket=bucket, Key=csv_key)
    data = obj["Body"].read()
    raw = conn.connection.driver_connection
    t0 = time.time()
    with raw.cursor() as cur:
        with cur.copy(
            f"COPY spike_sse_stdin ({', '.join(cols)}) FROM STDIN WITH (FORMAT CSV, HEADER true)"
        ) as copy:
            copy.write(data.decode("utf-8"))
    conn.commit()
    elapsed = time.time() - t0
    n = conn.execute(text("SELECT count(*) FROM spike_sse_stdin")).scalar()
    return int(n or 0), elapsed


def _reuse_or_build() -> tuple[list[str], int, float]:
    """Reuse existing spike CSV when present (skip rebuild after infra fixes)."""
    try:
        head = s3.head_object(Bucket=bucket, Key=csv_key)
    except Exception:
        head = None
    if head and head.get("ContentLength", 0) > 0 and os.environ.get("LBP_SPIKE_FORCE_BUILD", "0") not in ("1", "true"):
        # Read header only for column list
        obj = s3.get_object(Bucket=bucket, Key=csv_key, Range="bytes=0-65535")
        first = obj["Body"].read().decode("utf-8", errors="replace").splitlines()[0]
        cols = next(csv.reader([first]))
        # row count unknown cheaply — use max_rows as intended size
        print(json.dumps({"event": "csv_reused", "s3": f"s3://{bucket}/{csv_key}", "bytes": head["ContentLength"], "cols": len(cols)}))
        return cols, max_rows, 0.0
    return _build_csv()


def main() -> None:
    cols, rows, build_s = _reuse_or_build()
    print(json.dumps({"event": "csv_built", "rows": rows, "cols": len(cols), "s3": f"s3://{bucket}/{csv_key}", "secs": round(build_s, 2)}))

    eng = db.get_engine()
    with eng.connect() as conn:
        _ensure_extensions(conn)
        n1, s3_secs, import_msg = _import_aws_s3(conn, cols)
        print(json.dumps({"event": "aws_s3_import", "rows": n1, "secs": round(s3_secs, 2), "msg": str(import_msg)}))
        n2, stdin_secs = _import_stdin_copy(conn, cols)
        print(json.dumps({"event": "stdin_copy", "rows": n2, "secs": round(stdin_secs, 2)}))
        conn.execute(text("DROP TABLE IF EXISTS spike_sse_import"))
        conn.execute(text("DROP TABLE IF EXISTS spike_sse_stdin"))
        conn.commit()

    print(json.dumps({
        "event": "spike_done",
        "rows": rows,
        "csv_build_secs": round(build_s, 2),
        "aws_s3_import_secs": round(s3_secs, 2),
        "stdin_copy_secs": round(stdin_secs, 2),
        "winner": "aws_s3" if s3_secs < stdin_secs else "stdin_copy",
        "note": "UNLOGGED text staging only — not full OLTP sse_loans with indexes/DUP02",
    }))


if __name__ == "__main__":
    main()
