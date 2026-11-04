"""SFTP pull connector against a real in-process SFTP server: host-key pinning, password auth from
Secrets Manager, pattern/extension filtering, fetch-once."""
import base64
import hashlib
import os
import socket
import threading
from pathlib import Path

import pytest

paramiko = pytest.importorskip("paramiko")


class _Server(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if (username, password) == ("pennymac", "s3cret") else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class _SFTP(paramiko.SFTPServerInterface):
    ROOT = None

    def _p(self, path):
        return str(Path(self.ROOT) / path.lstrip("/"))

    def list_folder(self, path):
        out = []
        for name in os.listdir(self._p(path)):
            attr = paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(self._p(path), name)))
            attr.filename = name
            out.append(attr)
        return out

    def stat(self, path):
        return paramiko.SFTPAttributes.from_stat(os.stat(self._p(path)))

    lstat = stat

    def open(self, path, flags, attr):
        h = paramiko.SFTPHandle(flags)
        h.readfile = open(self._p(path), "rb")  # noqa: SIM115
        return h


def _serve(sock, key, root):
    _SFTP.ROOT = root
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            return
        t = paramiko.Transport(conn)
        t.add_server_key(key)
        t.set_subsystem_handler("sftp", paramiko.SFTPServer, _SFTP)
        t.start_server(server=_Server())


@pytest.fixture()
def sftp_server(tmp_path):
    key = paramiko.RSAKey.generate(2048)
    root = tmp_path / "sftp"
    (root / "out").mkdir(parents=True)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    threading.Thread(target=_serve, args=(sock, key, str(root)), daemon=True).start()
    fp = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    yield {"port": sock.getsockname()[1], "fingerprint": fp, "root": root}
    sock.close()


def test_sftp_pull_pins_host_key_and_fetches_once(onboarded, sftp_server, monkeypatch):
    import boto3
    from moto import mock_aws

    from lbp import config
    from lbp.scheduling.pullers import PullError, fetch_new

    monkeypatch.setenv("LBP_PULL_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "x")
    config.reset_settings()
    src = onboarded["pcg_retail"]
    out = sftp_server["root"] / "out"
    (out / "PCG_DELTA_000001.csv").write_bytes(Path(src["path"]).read_bytes())
    (out / "PCG_DELTA_000002.exe").write_text("never")
    (out / "README.txt").write_text("never")
    with mock_aws():
        boto3.client("secretsmanager", region_name="us-east-1").create_secret(
            Name="lbp/vendors/pcg", SecretString='{"username": "pennymac", "password": "s3cret"}')
        cfg = {"protocol": "sftp", "host": "127.0.0.1", "port": sftp_server["port"], "path": "/out", "pattern": "PCG_*.csv",
               "secret_ref": "lbp/vendors/pcg", "host_key_sha256": sftp_server["fingerprint"]}
        got, skipped = fetch_new(cfg, set())
        assert [g[0].name for g in got] == ["PCG_DELTA_000001.csv"] and not skipped
        assert got[0][1].read_bytes() == Path(src["path"]).read_bytes()
        again, _ = fetch_new(cfg, {(g[0].name, g[0].size, g[0].mtime) for g in got})
        assert again == []
        # a different server key (MITM / unannounced rotation) is refused before any credential is sent
        with pytest.raises(PullError, match="does not match the pinned fingerprint"):
            fetch_new({**cfg, "host_key_sha256": "SHA256:" + "A" * 43}, set())
