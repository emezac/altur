"""
Phase 8 — Integration tests: robustness, error handling, idempotency.

Acceptance criteria:
  1. Duplicate job delivery does NOT reprocess (STT/LLM called exactly once).
  2. POST /calls returns 503 (no side effects) when the queue is unavailable.
  3. Unhandled internal exceptions do NOT surface stack traces to clients.
  4. Retry-from-FAILED resumes from the correct stage (transcription or analysis).
  5. Empty transcript (0 turns) is treated as a benign result, not an error.
  6. /health returns 503 when Redis is unreachable.
"""
import io
import pytest
from unittest.mock import patch, MagicMock, call as mock_call

from app.models.call import Call
from app.models.transcript import Transcript
from app.models.tag import CallTag
from app.models.event import CallEvent
from app.workers.tasks import transcribe_call, analyze_call
from app.services.state_machine import transition


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _mp3_header() -> bytes:
    """Minimal valid MP3 header bytes (ID3 tag)."""
    return b"ID3" + b"\x00" * 7 + b"\x00" * 2048


def _make_call(db, filename="test.wav", status="PENDING") -> Call:
    c = Call(
        filename=filename,
        storage_path=f"path/{filename}",
        mime_type="audio/wav",
        file_size_bytes=1024,
        status=status,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_transcript(db, call_id: str, raw_text: str = "hello world") -> Transcript:
    t = Transcript(
        call_id=call_id,
        language="en",
        raw_text=raw_text,
        turns=[{"speaker": "agent", "start": 0.0, "end": 1.0, "text": raw_text}],
        stt_confidence=0.9,
        stt_provider="fake",
        stt_model="fake-stt",
    )
    db.add(t)
    db.commit()
    return t


_FAKE_LLM_RESPONSE = {
    "summary": {
        "executive_summary": "Test summary",
        "key_points": ["point 1"],
        "sentiment": "positive",
        "sentiment_score": 0.9,
        "purchase_intent": "high",
        "intent_score": 0.8,
        "insights": {
            "buying_signals": [],
            "risks": [],
            "inconsistencies": [],
            "tone_notes": [],
        },
    },
    "tags": {
        "outcome": "follow_up_scheduled",
        "outcome_confidence": 0.9,
        "next_step": "send_proposal",
        "next_step_confidence": 0.85,
        "objection": "price_budget",
        "objection_confidence": 0.8,
        "compliance_flag": "none",
        "product_interest": ["Pro Plan"],
    },
}


# ---------------------------------------------------------------------------
# 1. Idempotency: duplicate job delivery
# ---------------------------------------------------------------------------

class TestDuplicateJobIdempotency:
    """
    Verifies that a duplicate RQ job delivery does not invoke STT or LLM
    a second time. The atomic transition() guard is the mechanism.
    """

    def test_duplicate_transcribe_call_does_not_reinvoke_stt(self, db, monkeypatch):
        """
        Scenario: transcribe_call is delivered twice for the same call.
        The second delivery must exit without calling STT again.
        """
        call = _make_call(db)
        call_id = call.id

        # Fake STT provider
        fake_stt = MagicMock()
        fake_turn = MagicMock()
        fake_turn.text = "hello"
        fake_turn.model_dump.return_value = {"speaker": "agent", "start": 0.0, "end": 1.0, "text": "hello"}
        fake_result = MagicMock()
        fake_result.turns = [fake_turn]
        fake_result.language = "en"
        fake_result.stt_confidence = 0.9
        fake_result.provider = "fake"
        fake_result.model = "fake-stt"
        fake_stt.transcribe.return_value = fake_result

        call_counter = {"count": 0}

        def counting_stt():
            call_counter["count"] += 1
            return fake_stt

        monkeypatch.setattr("app.workers.tasks.get_stt_provider", counting_stt)
        monkeypatch.setattr("app.workers.tasks.get_queue", lambda: MagicMock())

        # First delivery: should succeed
        transcribe_call(call_id)

        db.expire_all()
        call_after_first = db.query(Call).filter(Call.id == call_id).first()
        assert call_after_first.status == "TRANSCRIBED"
        assert call_counter["count"] == 1

        # Second delivery: state is no longer PENDING/FAILED -> should be a no-op
        transcribe_call(call_id)
        assert call_counter["count"] == 1  # STT NOT called again

    def test_duplicate_analyze_call_does_not_reinvoke_llm(self, db, monkeypatch):
        """
        Scenario: analyze_call is delivered twice for the same call.
        The second delivery must exit without calling the LLM again.
        """
        import json as json_mod
        call = _make_call(db, status="TRANSCRIBED")
        call_id = call.id
        _make_transcript(db, call_id)

        llm_call_counter = {"count": 0}

        def counting_llm():
            fake = MagicMock()
            llm_call_counter["count"] += 1
            fake.complete_json.return_value = json_mod.dumps(_FAKE_LLM_RESPONSE)
            return fake

        monkeypatch.setattr("app.workers.tasks.get_llm_provider", counting_llm)

        # First delivery
        analyze_call(call_id)

        db.expire_all()
        assert db.query(Call).filter(Call.id == call_id).first().status == "COMPLETED"
        assert llm_call_counter["count"] == 1

        # Second delivery: status is no longer TRANSCRIBED -> no-op
        analyze_call(call_id)
        assert llm_call_counter["count"] == 1  # LLM NOT called again


# ---------------------------------------------------------------------------
# 2. POST /calls returns 503 when queue is down
# ---------------------------------------------------------------------------

class TestQueueUnavailable503:
    """
    POST /calls must return 503 with no side effects (no DB records,
    no storage files) when the job queue (Redis) is unreachable.
    """

    def test_upload_returns_503_when_queue_down(self, client, db, monkeypatch):
        monkeypatch.setattr("app.api.calls.check_queue_available", lambda: False)

        audio_bytes = _mp3_header()
        r = client.post(
            "/api/v1/calls",
            files={"file": ("sample.mp3", io.BytesIO(audio_bytes), "audio/mpeg")},
        )
        assert r.status_code == 503
        body = r.json()
        assert body["error"]["code"] == "QUEUE_UNAVAILABLE"

    def test_upload_503_creates_no_db_record(self, client, db, monkeypatch):
        monkeypatch.setattr("app.api.calls.check_queue_available", lambda: False)

        before_count = db.query(Call).count()
        audio_bytes = _mp3_header()
        client.post(
            "/api/v1/calls",
            files={"file": ("sample.mp3", io.BytesIO(audio_bytes), "audio/mpeg")},
        )
        after_count = db.query(Call).count()
        assert after_count == before_count  # No orphaned record

    def test_health_returns_503_when_redis_unreachable(self, client, monkeypatch):
        monkeypatch.setattr("app.api.health.check_redis", lambda: False)

        r = client.get("/health")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "unhealthy"
        assert body["queue"] is False


# ---------------------------------------------------------------------------
# 3. No stack trace reaches the client
# ---------------------------------------------------------------------------

class TestNoStackTraceInResponse:
    """
    Unhandled exceptions inside route handlers must never surface a Python
    traceback in the HTTP response body.
    """

    def test_internal_error_returns_500_without_traceback(self, client, db, monkeypatch):
        """
        Monkey-patch list_calls to raise an unexpected RuntimeError.
        The response must be HTTP 500 with a sanitized JSON body.
        """
        def boom(*args, **kwargs):
            raise RuntimeError("Simulated unexpected database crash")

        monkeypatch.setattr("app.api.calls.list_calls", boom)

        r = client.get("/api/v1/calls")
        assert r.status_code == 500

        body = r.json()
        # Must NOT expose traceback or internal detail
        response_text = str(body)
        assert "Traceback" not in response_text
        assert "RuntimeError" not in response_text
        assert "Simulated" not in response_text

        # Must follow our error envelope schema
        assert "error" in body
        assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
        assert "request_id" in body["error"]

    def test_404_returns_clean_json(self, client):
        r = client.get("/api/v1/calls/does-not-exist-12345")
        assert r.status_code == 404
        body = r.json()
        # FastAPI HTTPException format
        assert "detail" in body
        assert "Traceback" not in str(body)


# ---------------------------------------------------------------------------
# 4. Worker error boundary transitions call to FAILED
# ---------------------------------------------------------------------------

class TestWorkerErrorBoundary:
    """
    When the STT or LLM provider raises, the worker must:
      - transition the call to FAILED
      - write an ERROR event with the error message
      - NOT propagate the exception
    """

    def test_transcribe_call_stt_error_sets_failed_status(self, db, monkeypatch):
        call = _make_call(db)
        call_id = call.id

        def failing_stt():
            m = MagicMock()
            m.transcribe.side_effect = ConnectionError("STT provider unreachable")
            return m

        monkeypatch.setattr("app.workers.tasks.get_stt_provider", failing_stt)
        monkeypatch.setattr("app.workers.tasks.get_queue", lambda: MagicMock())

        # Must not raise
        transcribe_call(call_id)

        db.expire_all()
        updated_call = db.query(Call).filter(Call.id == call_id).first()
        assert updated_call.status == "FAILED"

        error_events = (
            db.query(CallEvent)
            .filter(CallEvent.call_id == call_id, CallEvent.event_type == "ERROR")
            .all()
        )
        assert len(error_events) >= 1
        assert "STT provider unreachable" in str(error_events[0].payload)

    def test_analyze_call_llm_error_sets_failed_status(self, db, monkeypatch):
        call = _make_call(db, status="TRANSCRIBED")
        call_id = call.id
        _make_transcript(db, call_id)

        def failing_llm():
            m = MagicMock()
            m.complete_json.side_effect = TimeoutError("LLM timeout")
            return m

        monkeypatch.setattr("app.workers.tasks.get_llm_provider", failing_llm)

        analyze_call(call_id)

        db.expire_all()
        assert db.query(Call).filter(Call.id == call_id).first().status == "FAILED"

        error_events = (
            db.query(CallEvent)
            .filter(CallEvent.call_id == call_id, CallEvent.event_type == "ERROR")
            .all()
        )
        assert any("LLM timeout" in str(e.payload) for e in error_events)


# ---------------------------------------------------------------------------
# 5. Retry-from-FAILED resumes at the correct stage
# ---------------------------------------------------------------------------

class TestRetryResumesFromCorrectStage:
    """
    POST /calls/{id}/retry must:
      - Re-enqueue transcribe_call when no transcript exists yet.
      - Re-enqueue analyze_call when transcript already exists (skip STT).
    """

    def test_retry_failed_call_without_transcript_re_enqueues_transcribe(self, client, db, monkeypatch):
        call = _make_call(db, status="FAILED")
        call_id = call.id

        enqueued = []

        class FakeQueue:
            def enqueue(self, fn, *args, **kwargs):
                enqueued.append(fn.__name__)

        # get_queue is imported from app.workers.queue inside calls_service
        monkeypatch.setattr("app.workers.queue.get_queue", lambda: FakeQueue())

        r = client.post(f"/api/v1/calls/{call_id}/retry")
        assert r.status_code == 200
        assert "transcribe_call" in enqueued

    def test_retry_failed_call_with_transcript_re_enqueues_analyze(self, client, db, monkeypatch):
        call = _make_call(db, status="FAILED")
        call_id = call.id
        _make_transcript(db, call_id)

        enqueued = []

        class FakeQueue:
            def enqueue(self, fn, *args, **kwargs):
                enqueued.append(fn.__name__)

        monkeypatch.setattr("app.workers.queue.get_queue", lambda: FakeQueue())

        r = client.post(f"/api/v1/calls/{call_id}/retry")
        assert r.status_code == 200
        assert "analyze_call" in enqueued

    def test_retry_non_failed_call_returns_409(self, client, db):
        call = _make_call(db, status="COMPLETED")
        r = client.post(f"/api/v1/calls/{call.id}/retry")
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# 6. Empty transcript is benign (not an error)
# ---------------------------------------------------------------------------

class TestEmptyTranscriptBenign:
    """
    An STT result with zero turns (e.g. silence) must complete the pipeline
    without raising an error. The call transitions to TRANSCRIBED then COMPLETED.
    """

    def test_empty_transcript_completes_pipeline(self, db, monkeypatch):
        import json as json_mod

        call = _make_call(db)
        call_id = call.id

        # STT returns 0 turns (silence / empty audio)
        fake_stt = MagicMock()
        fake_result = MagicMock()
        fake_result.turns = []
        fake_result.language = "en"
        fake_result.stt_confidence = 0.0
        fake_result.provider = "fake"
        fake_result.model = "fake-stt"
        fake_stt.transcribe.return_value = fake_result

        monkeypatch.setattr("app.workers.tasks.get_stt_provider", lambda: fake_stt)

        fake_llm = MagicMock()
        fake_llm.complete_json.return_value = json_mod.dumps(_FAKE_LLM_RESPONSE)
        monkeypatch.setattr("app.workers.tasks.get_llm_provider", lambda: fake_llm)
        monkeypatch.setattr("app.workers.tasks.get_queue", lambda: MagicMock())

        transcribe_call(call_id)
        db.expire_all()
        transcribed = db.query(Call).filter(Call.id == call_id).first()
        assert transcribed.status == "TRANSCRIBED"

        # analyze_call handles empty raw_text gracefully
        analyze_call(call_id)
        db.expire_all()
        completed = db.query(Call).filter(Call.id == call_id).first()
        assert completed.status == "COMPLETED"
