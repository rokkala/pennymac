"""Throughput test: generate N loans, onboard the source, board through the full pipeline.

    python scripts/load_test.py --rows 100000 --workers 8 --micro-batch 10000

Prints loans/sec and the projected 24h capacity against the 1M/24h target.
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=100_000)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--micro-batch", type=int, default=10_000)
    ap.add_argument("--source", default="pcg_retail", choices=["pcg_retail", "sub_servicing", "correspondent", "bulk_acquisition"])
    ap.add_argument("--data-dir", default=".lbp_loadtest")
    a = ap.parse_args()
    os.environ["LBP_DATA_DIR"] = a.data_dir

    from lbp import samples
    from lbp.mapping import service as ms
    from lbp.pipeline.batch import create_batch, run_batch
    from lbp.rules.registry import RuleRegistry

    RuleRegistry().seed_defaults()
    label, ext, writer = samples.SOURCES[a.source]
    path = Path(a.data_dir) / f"load_{a.source}_{a.rows}.{ext}"
    t = time.time()
    writer(path, a.rows)
    print(f"generated {a.rows:,} rows in {time.time() - t:.1f}s -> {path}")
    sample = Path(a.data_dir) / f"sample_{a.source}.{ext}"
    writer(sample, 1000)
    reg = ms.register_source(label, sample, "analyst")
    ms.accept_all(reg["mapping_id"], "analyst", 0.0)
    ms.submit(reg["mapping_id"], "analyst")
    ms.approve(reg["mapping_id"], "sme", ["sme"])
    bid = create_batch(reg["source_id"], path, path.name, "loadtest")
    t = time.time()
    res = run_batch(bid, workers=a.workers, micro_batch_size=a.micro_batch)
    secs = time.time() - t
    lps = res["processed"] / secs
    print(f"processed {res['processed']:,} | boarded {res['loaded']:,} | failed {res['failed']:,} | {secs:.1f}s")
    print(f"throughput {lps:,.0f} loans/sec  ->  projected {lps * 86400 / 1e6:,.1f}M loans / 24h  ({lps * 86400 / 1e6:,.0f}x the 1M/24h target)")


if __name__ == "__main__":
    main()
