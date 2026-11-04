def test_s3_round_trip_through_pipeline(onboarded, monkeypatch):
    """Batch file and feed configuration live in S3 (as in Glue); the pipeline, pre-flight and replay read it via the storage layer."""
    import boto3
    from moto import mock_aws
    from sqlalchemy import select

    from lbp import config
    from lbp.pipeline.batch import create_batch, run_batch
    from lbp.pipeline.replay import replay_batch
    from lbp.storage import local_path, persist_upload
    from lbp.store import db

    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="lbp-raw")
        monkeypatch.setenv("LBP_ENV", "aws")
        monkeypatch.setenv("LBP_RAW_BUCKET", "lbp-raw")
        monkeypatch.setenv("LBP_AWS_REGION", "us-east-1")
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="lbp-processed")
        monkeypatch.setenv("LBP_PROCESSED_BUCKET", "lbp-processed")  # signed feed configurations live here in AWS
        sec = boto3.client("secretsmanager", region_name="us-east-1").create_secret(Name="cfg", SecretString="k")["ARN"]
        monkeypatch.setenv("LBP_CONFIG_SIGNING_SECRET_ARN", sec)
        config.reset_settings()
        from lbp.config_store import publish_all

        publish_all("test", "configs to S3")
        src = onboarded["sub_servicing"]
        tmp = src["path"].parent / "copy.txt"
        tmp.write_bytes(src["path"].read_bytes())
        uri = persist_upload(tmp, "incoming/test")
        assert uri.startswith("s3://lbp-raw/incoming/test/") and not tmp.exists()
        assert local_path(uri).read_bytes() == src["path"].read_bytes()
        bid = create_batch(src["source_id"], uri, "copy.txt", "ops")
        run_batch(bid, workers=1)
        with db.get_engine().connect() as c:
            b = c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()
        assert b.status == "completed" and b.file_path == uri and b.reconciliation["balanced"]
        assert replay_batch(bid, "ops", dry_run=True)["replayed"] == b.processed - b.loaded
