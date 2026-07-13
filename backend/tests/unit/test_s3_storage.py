"""
Offline tests for S3CompatibleStorage using moto (in-process S3 mock — no network).
Covers the full lifecycle: save → exists → open → presigned get_url → delete.
"""
import io

import boto3
import pytest

from app.core.config import settings

moto = pytest.importorskip("moto")
from moto import mock_aws  # noqa: E402


BUCKET = "test-audio-bucket"


@pytest.fixture
def s3_env(monkeypatch):
    # Point the storage at a mocked AWS (no custom endpoint so moto intercepts).
    monkeypatch.setattr(settings, "S3_BUCKET_NAME", BUCKET)
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", None)
    monkeypatch.setattr(settings, "S3_REGION", "us-east-1")
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield


def test_s3_save_exists_open_delete(s3_env):
    from app.services.storage.s3 import S3CompatibleStorage

    storage = S3CompatibleStorage()
    payload = b"RIFF\x00\x00\x00\x00WAVEfmt fake-audio-bytes"

    key = storage.save(io.BytesIO(payload), "call 01.wav")

    # Key is sanitized and namespaced, not a filesystem path
    assert key.endswith("_call01.wav")
    assert "/" not in key

    assert storage.exists(key) is True
    assert storage.open(key).read() == payload

    storage.delete(key)
    assert storage.exists(key) is False


def test_s3_get_url_returns_presigned(s3_env):
    from app.services.storage.s3 import S3CompatibleStorage

    storage = S3CompatibleStorage()
    key = storage.save(io.BytesIO(b"data"), "x.mp3")

    url = storage.get_url(key, expires_in=600)
    assert url and url.startswith("http")
    assert key in url
    # Presigned signature params are present
    assert "X-Amz-Signature" in url or "Signature" in url


def test_s3_exists_false_for_missing_key(s3_env):
    from app.services.storage.s3 import S3CompatibleStorage

    storage = S3CompatibleStorage()
    assert storage.exists("does-not-exist.wav") is False
