"""Glue job `lbp-vendor-pull` (Glue 5.0, driver only): fetch a vendor's new files (SFTP / shared S3) into the raw zone.

Job parameters
  --schedule_id   an approved, active pull schedule (host allow-list, pinned SSH host key, Secrets Manager credentials)
Each fetched file lands in s3://<raw>/incoming/<feed_id>/..., where the arrival event starts `lbp-feed`.
Runs in the VPC through a Glue NETWORK connection; egress to vendors is limited to tcp/22 on vendor CIDRs.
"""
import os
import sys

# Terraform passes the platform settings as --LBP_* job arguments; expose them before lbp reads its settings
for _i, _a in enumerate(sys.argv[:-1]):
    if _a.startswith("--LBP_"):
        os.environ.setdefault(_a[2:], sys.argv[_i + 1])

from awsglue.utils import getResolvedOptions  # type: ignore  # noqa: E402

from lbp import glue_jobs  # noqa: E402

args = getResolvedOptions(sys.argv, ["schedule_id"])
print(glue_jobs.summary(glue_jobs.pull(args["schedule_id"])))
