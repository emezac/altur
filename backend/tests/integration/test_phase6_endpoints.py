"""
Integration tests for Phase 6 endpoints:
  - GET /calls (pagination + filtering)
  - GET /calls/{id}/status
  - PATCH /calls/{id}/tags
  - POST /calls/{id}/retry
  - GET /calls/{id}/export
  - GET /analytics/summary
"""
import pytest
from app.models.call import Call
from app.models.tag import CallTag, CallTagOverride
from app.models.event import CallEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_call(db, filename="test.wav", status="PENDING", duration=None) -> Call:
    c = Call(
        filename=filename,
        storage_path=f"path/{filename}",
        mime_type="audio/wav",
        file_size_bytes=1024,
        status=status,
        duration_seconds=duration,
    )
    db.add(c)
    db.commit()
    return c


# ---------------------------------------------------------------------------
# Pagination tests
# ---------------------------------------------------------------------------

def test_list_calls_pagination(client, db):
    for i in range(5):
        _make_call(db, filename=f"call_{i}.wav")

    r = client.get("/api/v1/calls?page=1&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    assert body["total"] >= 5


def test_list_calls_filter_by_status(client, db):
    _make_call(db, filename="done.wav", status="COMPLETED")
    _make_call(db, filename="fail.wav", status="FAILED")

    r = client.get("/api/v1/calls?status=FAILED")
    assert r.status_code == 200
    body = r.json()
    assert all(item["status"] == "FAILED" for item in body["items"])


def test_list_calls_filter_by_tag(client, db):
    c = _make_call(db, filename="tagged.wav", status="COMPLETED")
    db.add(CallTag(call_id=c.id, tag_category="sentiment", tag_value="positive", confidence=0.9))
    db.commit()

    r = client.get("/api/v1/calls?tag=positive")
    assert r.status_code == 200
    body = r.json()
    assert any(item["id"] == c.id for item in body["items"])


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------

def test_status_pending(client, db):
    c = _make_call(db, status="PENDING")
    r = client.get(f"/api/v1/calls/{c.id}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PENDING"
    assert body["progress"] == 5
    assert body["error_message"] is None


def test_status_completed(client, db):
    c = _make_call(db, status="COMPLETED")
    r = client.get(f"/api/v1/calls/{c.id}/status")
    assert r.status_code == 200
    assert r.json()["progress"] == 100


def test_status_failed_with_error_event(client, db):
    c = _make_call(db, status="FAILED")
    db.add(CallEvent(
        call_id=c.id,
        event_type="TRANSCRIPTION_ERROR",
        payload={"error": "STT provider timeout"},
    ))
    db.commit()

    r = client.get(f"/api/v1/calls/{c.id}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    assert "STT provider timeout" in body["error_message"]


def test_status_not_found(client):
    r = client.get("/api/v1/calls/non-existent-id/status")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tag override endpoint
# ---------------------------------------------------------------------------

def test_patch_tags_override(client, db):
    c = _make_call(db, status="COMPLETED")
    db.add(CallTag(call_id=c.id, tag_category="sentiment", tag_value="neutral", confidence=0.7, source="model"))
    db.commit()

    r = client.patch(
        f"/api/v1/calls/{c.id}/tags",
        json={"category": "sentiment", "value": "positive", "reason": "Reviewer override"},
    )
    assert r.status_code == 204

    # Verify audit record was created
    audit = db.query(CallTagOverride).filter_by(call_id=c.id).first()
    assert audit is not None
    assert audit.previous_value == "neutral"
    assert audit.new_value == "positive"
    assert audit.action == "changed"


def test_patch_tags_invalid_category(client, db):
    c = _make_call(db, status="COMPLETED")
    r = client.patch(
        f"/api/v1/calls/{c.id}/tags",
        json={"category": "nonexistent_category", "value": "foo"},
    )
    assert r.status_code == 422


def test_patch_tags_invalid_value(client, db):
    c = _make_call(db, status="COMPLETED")
    r = client.patch(
        f"/api/v1/calls/{c.id}/tags",
        json={"category": "sentiment", "value": "super_happy_feeling"},
    )
    assert r.status_code == 422


def test_patch_tags_not_found(client):
    r = client.patch(
        "/api/v1/calls/nonexistent/tags",
        json={"category": "sentiment", "value": "positive"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Retry endpoint
# ---------------------------------------------------------------------------

def test_retry_failed_call(client, db):
    c = _make_call(db, status="FAILED")
    r = client.post(f"/api/v1/calls/{c.id}/retry")
    assert r.status_code == 200
    body = r.json()
    assert body["call_id"] == c.id
    assert body["status"] in ("PENDING", "TRANSCRIBED")


def test_retry_non_failed_call_returns_409(client, db):
    c = _make_call(db, status="COMPLETED")
    r = client.post(f"/api/v1/calls/{c.id}/retry")
    assert r.status_code == 409


def test_retry_not_found(client):
    r = client.post("/api/v1/calls/ghost-id/retry")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Export endpoint
# ---------------------------------------------------------------------------

def test_export_call_structure(client, db):
    c = _make_call(db, filename="export_test.wav", status="COMPLETED", duration=120.5)
    db.add(CallTag(call_id=c.id, tag_category="outcome", tag_value="won_deal_closed", confidence=0.95, source="model"))
    db.commit()

    r = client.get(f"/api/v1/calls/{c.id}/export")
    assert r.status_code == 200
    # Should be a JSON download
    assert "attachment" in r.headers.get("content-disposition", "")

    body = r.json()
    assert body["call_id"] == c.id
    assert body["filename"] == "export_test.wav"
    assert body["duration_seconds"] == 120.5
    assert body["status"] == "COMPLETED"
    assert len(body["tags_effective"]) == 1
    assert body["tags_effective"][0]["value"] == "won_deal_closed"


def test_export_not_found(client):
    r = client.get("/api/v1/calls/ghost-id/export")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Analytics summary endpoint
# ---------------------------------------------------------------------------

def test_analytics_summary_empty(client, db):
    r = client.get("/api/v1/analytics/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["total_calls"] == 0
    assert body["conversion_rate"] == 0.0
    assert body["by_status"] == {}


def test_analytics_summary_with_calls(client, db):
    c1 = _make_call(db, filename="a.wav", status="COMPLETED", duration=60.0)
    c2 = _make_call(db, filename="b.wav", status="FAILED", duration=None)
    c3 = _make_call(db, filename="c.wav", status="COMPLETED", duration=120.0)

    # Tag c1 with positive sentiment and converted outcome
    db.add(CallTag(call_id=c1.id, tag_category="sentiment", tag_value="positive", confidence=0.9, source="model"))
    db.add(CallTag(call_id=c1.id, tag_category="outcome", tag_value="converted", confidence=0.85, source="model"))
    # Tag c3 with negative sentiment
    db.add(CallTag(call_id=c3.id, tag_category="sentiment", tag_value="negative", confidence=0.7, source="model"))
    db.commit()

    r = client.get("/api/v1/analytics/summary")
    assert r.status_code == 200
    body = r.json()

    assert body["total_calls"] == 3
    assert body["by_status"]["COMPLETED"] == 2
    assert body["by_status"]["FAILED"] == 1
    # Conversion rate: 1 converted out of 3 total = 33.33%
    assert body["conversion_rate"] == pytest.approx(33.33, abs=0.1)
    assert body["sentiment_distribution"]["positive"] == 1
    assert body["sentiment_distribution"]["negative"] == 1
    # avg_duration of the two calls with duration (60 + 120) / 2 = 90
    assert body["avg_duration_seconds"] == pytest.approx(90.0, abs=0.1)


def test_analytics_summary_volume_by_day(client, db):
    _make_call(db, filename="d1.wav", status="COMPLETED")
    _make_call(db, filename="d2.wav", status="PENDING")

    r = client.get("/api/v1/analytics/summary")
    body = r.json()
    # There should be at least one entry in volume_by_day
    assert len(body["volume_by_day"]) >= 1
    # Each entry should have date and count keys
    entry = body["volume_by_day"][0]
    assert "date" in entry
    assert "count" in entry
