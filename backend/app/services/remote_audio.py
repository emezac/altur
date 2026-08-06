"""
Fetch a remote recording URL to a local temp file before STT (audio-first ingestion).

This exists for providers that expose recorded audio (Twilio, Aircall, a recordings
bucket) — NOT CALL-E, which returns a transcript and no audio. Downloading a URL that
arrived in a webhook payload is an SSRF vector, so this is deliberately fail-closed:

  * HTTPS only (no http/file/gopher/…);
  * the host must resolve exclusively to public IPs (blocks localhost, 169.254.169.254,
    RFC1918, link-local, reserved);
  * optional host allowlist (REMOTE_AUDIO_ALLOWED_HOSTS);
  * redirects are refused (presigned URLs don't need them, and a redirect could point
    back at an internal address);
  * size cap (MAX_UPLOAD_MB) enforced by Content-Length AND during streaming;
  * bounded timeout.

Residual risk: DNS rebinding between the resolve-check and urllib's own connect (TOCTOU).
Pinning the socket to the validated IP is the follow-up hardening; the checks here stop
the common cases (internal hostnames, metadata endpoints, loopback).
"""
import ipaddress
import logging
import os
import socket
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from app.core.config import settings
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

_CHUNK = 64 * 1024


class _RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise AppError(
            "REMOTE_AUDIO_REDIRECT",
            "Redirects are not allowed when fetching remote audio.",
            400,
        )


def is_remote_url(path: str) -> bool:
    return isinstance(path, str) and path.lower().startswith(("http://", "https://"))


def _allowed_hosts() -> list[str]:
    raw = settings.REMOTE_AUDIO_ALLOWED_HOSTS or ""
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _guard_url(parsed) -> None:
    if parsed.scheme != "https":
        raise AppError("REMOTE_AUDIO_SCHEME", "Remote audio URL must use HTTPS.", 400)
    host = parsed.hostname
    if not host:
        raise AppError("REMOTE_AUDIO_HOST", "Remote audio URL is missing a host.", 400)

    allow = _allowed_hosts()
    if allow and host.lower() not in allow:
        raise AppError("REMOTE_AUDIO_HOST", f"Host '{host}' is not in the allowed host list.", 400)

    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as err:
        raise AppError("REMOTE_AUDIO_DNS", f"Could not resolve remote audio host: {err}", 400)

    for info in infos:
        ip = info[4][0]
        if not _ip_is_public(ip):
            raise AppError(
                "REMOTE_AUDIO_SSRF",
                "Remote audio host resolves to a non-public address.",
                400,
            )


def _suffix(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in (".wav", ".mp3", ".m4a", ".ogg", ".flac") else ".audio"


def fetch_to_tempfile(url: str) -> str:
    """Download `url` to a temp file after SSRF/size guards. Returns the local path.

    Caller owns the returned file and must delete it.
    """
    parsed = urlparse(url)
    _guard_url(parsed)

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    timeout = settings.REMOTE_AUDIO_TIMEOUT_SECONDS
    opener = build_opener(_RefuseRedirects)
    request = Request(url, headers={"User-Agent": "altur-call-analyzer/1.0"})

    fd, tmp_path = tempfile.mkstemp(suffix=_suffix(parsed.path))
    try:
        with opener.open(request, timeout=timeout) as response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > max_bytes:
                raise AppError(
                    "REMOTE_AUDIO_TOO_LARGE",
                    f"Remote audio exceeds the {settings.MAX_UPLOAD_MB}MB limit.",
                    413,
                )
            written = 0
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise AppError(
                            "REMOTE_AUDIO_TOO_LARGE",
                            f"Remote audio exceeds the {settings.MAX_UPLOAD_MB}MB limit.",
                            413,
                        )
                    out.write(chunk)
        logger.info(f"Fetched remote audio ({written} bytes) from {parsed.hostname} -> {tmp_path}")
        return tmp_path
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
