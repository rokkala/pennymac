"""Glue job `lbp-feed-load`: COPY clean+dirty S3 parts into Postgres after Spark DB-free materialize.

Job parameters: --batch_id. Same lbp wheel as feed-spark. Prefer small worker count (not a Spark cluster).
"""
import json
import os
import sys

for _i, _a in enumerate(sys.argv[:-1]):
    if _a.startswith("--LBP_"):
        os.environ.setdefault(_a[2:], sys.argv[_i + 1])

from awsglue.utils import getResolvedOptions  # type: ignore  # noqa: E402

from lbp import glue_jobs  # noqa: E402
from lbp.config_store import load as load_config  # noqa: E402
from lbp.pipeline.batch import LEASE_FROM, BatchBusyError  # noqa: E402
from lbp.pipeline.sequencing import acquire  # noqa: E402
from lbp.store import db  # noqa: E402
from sqlalchemy import select  # noqa: E402

args = getResolvedOptions(sys.argv, ["batch_id"])
batch_id = args["batch_id"]

with db.get_engine().connect() as c:
    b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
if not b:
    raise SystemExit(f"unknown batch {batch_id}")
# Gate before acquire — acquire() flips status to running, which would trip run_load_bulk.
if b.status not in ("staged", "failed", "paused"):
    raise ValueError(f"load refuses batch status={b.status!r}; want staged|failed|paused")

leased, g = acquire(batch_id, f"glue-load:{os.getpid()}", LEASE_FROM)
if not leased:
    if g and g["decision"] != "go":
        print(json.dumps({"batch_id": batch_id, "status": "waiting" if g["decision"] == "wait" else "out_of_order"}))
        raise SystemExit(0)
    raise BatchBusyError(batch_id)

cfg = load_config(b.source_id)
print(glue_jobs.summary(glue_jobs.run_load_bulk(batch_id, cfg)))
