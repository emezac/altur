"""
SSRF/size guards for audio-first remote fetch (app/services/remote_audio.py).
"""
import os
from contextlib import contextmanager

import pytest

import app.services.remote_audio as ra
from app.core.exceptions import AppError


class _FakeResponse:
    def __init__(self, body: bytes, content_length=None):
        self._body = body
        self._pos = 0
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    # dict-like .get used by the module
    def read(self, n):
        chunk = self._body[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


class _FakeHeaders(dict):
    pass


def _public_addrinfo(*_a, **_k):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]  # a public IP


def _loopback_addrinfo(*_a, **_k):
    return [(2, 1, 6, "", ("127.0.0.1", 443))]


def _fake_opener(body: bytes, content_length=None):
    resp = _FakeResponse(body, content_length)
    resp.headers = _FakeHeaders(resp.headers)

    class _Opener:
        @contextmanager
        def _cm(self):
            yield resp

        def open(self, request, timeout=None):
            return self._cm()

    return _Opener()


def test_rejects_non_https(monkeypatch):
    with pytest.raises(AppError) as exc:
        ra.fetch_to_tempfile("http://example.com/rec.wav")
    assert exc.value.code == "REMOTE_AUDIO_SCHEME"


def test_rejects_host_resolving_to_loopback(monkeypatch):
    monkeypatch.setattr(ra.socket, "getaddrinfo", _loopback_addrinfo)
    with pytest.raises(AppError) as exc:
        ra.fetch_to_tempfile("https://internal.evil.test/rec.wav")
    assert exc.value.code == "REMOTE_AUDIO_SSRF"


def test_rejects_non_allowlisted_host(monkeypatch):
    monkeypatch.setattr(ra.settings, "REMOTE_AUDIO_ALLOWED_HOSTS", "recordings.myprovider.com")
    with pytest.raises(AppError) as exc:
        ra.fetch_to_tempfile("https://evil.example.com/rec.wav")
    assert exc.value.code == "REMOTE_AUDIO_HOST"


def test_enforces_size_cap_from_content_length(monkeypatch):
    monkeypatch.setattr(ra.socket, "getaddrinfo", _public_addrinfo)
    monkeypatch.setattr(ra.settings, "MAX_UPLOAD_MB", 1)
    monkeypatch.setattr(ra, "build_opener", lambda *_h: _fake_opener(b"x", content_length=5 * 1024 * 1024))
    with pytest.raises(AppError) as exc:
        ra.fetch_to_tempfile("https://recordings.myprovider.com/big.wav")
    assert exc.value.code == "REMOTE_AUDIO_TOO_LARGE"


def test_happy_path_downloads_to_tempfile(monkeypatch):
    monkeypatch.setattr(ra.socket, "getaddrinfo", _public_addrinfo)
    payload = b"RIFF....WAVE fake audio bytes"
    monkeypatch.setattr(ra, "build_opener", lambda *_h: _fake_opener(payload, content_length=len(payload)))

    path = ra.fetch_to_tempfile("https://recordings.myprovider.com/call-42.wav")
    try:
        assert os.path.exists(path)
        assert path.endswith(".wav")
        with open(path, "rb") as fh:
            assert fh.read() == payload
    finally:
        os.unlink(path)
