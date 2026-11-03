"""The connection string may come from a secret file (week 4, Compose secrets)."""

from __future__ import annotations

from caselaw_extraction import db
from caselaw_extraction.store import dsn_from_env


def test_dsn_from_env_prefers_variable_then_file(monkeypatch, tmp_path):
    monkeypatch.delenv("CASELAW_DSN", raising=False)
    monkeypatch.delenv("CASELAW_DSN_FILE", raising=False)
    assert dsn_from_env() is None
    f = tmp_path / "dsn"
    f.write_text("postgresql://u:p@h:5432/d\n")
    monkeypatch.setenv("CASELAW_DSN_FILE", str(f))
    assert dsn_from_env() == "postgresql://u:p@h:5432/d"
    monkeypatch.setenv("CASELAW_DSN", "postgresql://x")
    assert dsn_from_env() == "postgresql://x"


def test_open_run_local_and_s3_endpoint(monkeypatch, tmp_path):
    fs, base = db.open_run(tmp_path, "r")
    assert base.endswith("/r")
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    fs, base = db.open_run("s3://bucket/runs", "r")
    assert type(fs).__name__ == "S3FileSystem" and base == "bucket/runs/r"
