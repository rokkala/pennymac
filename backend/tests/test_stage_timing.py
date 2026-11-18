"""Per-stage wall timers for Spark/load A/B (JSON lines on stdout)."""
import json
from io import StringIO

from lbp import glue_jobs


def test_stage_timer_prints_json_and_records(monkeypatch, capsys):
    bag = {}
    with glue_jobs.stage_timer("load_clean", bag, batch_id="bat_x", rows=3):
        pass
    out = capsys.readouterr().out.strip().splitlines()[-1]
    ev = json.loads(out)
    assert ev["event"] == "stage_timing" and ev["stage"] == "load_clean"
    assert ev["batch_id"] == "bat_x" and ev["rows"] == 3 and ev["secs"] >= 0
    assert bag["load_clean"] == ev["secs"]
