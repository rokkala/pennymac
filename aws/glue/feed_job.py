"""Glue job `lbp-feed` (Glue 5.0, Python 3.11, runs on the driver): one batch end to end on the feed's published configuration.

Job parameters
  --batch_id   batch registered by the arrival Lambda / API
  --mode       process (default) | replay
  --actor      who asked for a replay (audit)
Glue 5.0, 2 x G.1X, no Spark stages (Glue Python shell is Python 3.9 only; lbp needs 3.11).
--additional-python-modules installs the lbp wheel built in CI.
Max concurrent runs is high: per-vendor ordering is enforced by the sequencing gate inside run_batch.
"""
import os
import sys

# Terraform passes the platform settings as --LBP_* job arguments; expose them before lbp reads its settings
for _i, _a in enumerate(sys.argv[:-1]):
    if _a.startswith("--LBP_"):
        os.environ.setdefault(_a[2:], sys.argv[_i + 1])

from awsglue.utils import getResolvedOptions  # type: ignore  # noqa: E402

from lbp import glue_jobs  # noqa: E402

opts = ["batch_id"] + [o for o in ("mode", "actor") if f"--{o}" in sys.argv]
args = getResolvedOptions(sys.argv, opts)
if args.get("mode") == "replay":
    res = glue_jobs.replay(args["batch_id"], args.get("actor", "glue"))
else:
    res = glue_jobs.process_batch(args["batch_id"])
print(glue_jobs.summary(res))
