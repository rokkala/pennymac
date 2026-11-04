import pytest

from lbp.maintenance import MaintenanceError, get_artifact, list_artifacts


def test_list_includes_all_jobs():
    ids = {a["id"] for a in list_artifacts()}
    assert {"feed-job", "feed-spark-job", "vendor-pull-job", "boarding-sfn", "lambdas", "dispatch"} <= ids
    assert all(a.get("group") for a in list_artifacts())


def test_get_feed_job_returns_python_source():
    a = get_artifact("feed-job")
    assert a["kind"] == "python" and "lbp-feed" in a["content"] and "glue_jobs" in a["content"]


def test_unknown_id_raises():
    with pytest.raises(MaintenanceError):
        get_artifact("not-a-real-id")


def test_notebook_strips_outputs():
    a = get_artifact("nb-feed-workbench")
    assert a["kind"] == "notebook" and isinstance(a["content"], list)
    assert all("outputs" not in c for c in a["content"])
    assert any(c["cell_type"] == "markdown" for c in a["content"])
