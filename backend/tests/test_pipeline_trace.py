from lbp.pipeline.trace import summarize_events


def test_summarize_events_keeps_each_step_and_its_return():
    events = [
        {"type": "TaskStateEntered", "stateEnteredEventDetails": {"name": "Route"}},
        {"type": "TaskSucceeded", "taskSucceededEventDetails": {"output": '{"engine": "standard", "job_name": "lbp-poc-feed"}'}},
        {"type": "ChoiceStateEntered", "stateEnteredEventDetails": {"name": "Engine"}},
        {"type": "TaskStateEntered", "stateEnteredEventDetails": {"name": "GlueStandard"}},
        {"type": "TaskFailed", "taskFailedEventDetails": {"error": "States.TaskFailed", "cause": "ssm us-east-1"}},
        {"type": "TaskStateEntered", "stateEnteredEventDetails": {"name": "GlueStandard"}},
        {"type": "TaskSucceeded", "taskSucceededEventDetails": {"output": '{"glue": {"state": "SUCCEEDED", "seconds": 40}}'}},
        {"type": "TaskStateEntered", "stateEnteredEventDetails": {"name": "Finalize"}},
        {"type": "TaskSucceeded", "taskSucceededEventDetails": {"output": '{"status": "completed", "balanced": true}'}},
    ]
    out = summarize_events(events, "SUCCEEDED")
    assert [s["label"] for s in out["steps"]] == ["Route", "Glue", "Glue", "Finalize"]
    assert out["steps"][1]["state"] == "failed"
    assert "us-east-1" in out["steps"][1]["summary"]
    assert out["steps"][-1]["summary"] == "completed · True"
    assert out["current"]["label"] == "Finalize"
