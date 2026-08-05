"""
Provider-agnostic webhook ingestion (POST /api/v1/calls/webhook).

Transcript-first is the CALL-E path: the provider already transcribed the call, so
STT is skipped and our own analysis runs on the real turns. The inline fake queue
executes analyze_call synchronously, so a completed transcript ingest reaches a
terminal state within the request.
"""
from app.models.call import Call
from app.models.event import CallEvent
from app.models.transcript import Transcript


def test_transcript_first_ingest_skips_stt_and_analyzes(client, db):
    payload = {
        "source": "calle",
        "language": "es",
        "owner_id": "tenant-42",
        "metadata": {"external_call_id": "call_official_123"},
        "transcript_turns": [
            {"speaker": "bot", "text": "Hola, le llamo de Altura CRM.", "offset_seconds": 0},
            {"speaker": "user", "text": "El precio de cuatro mil novecientos es alto.", "offset_seconds": 6},
        ],
    }

    response = client.post("/api/v1/calls/webhook", json=payload)

    assert response.status_code == 202
    data = response.json()
    assert data["mode"] == "transcript"
    assert data["source"] == "calle"
    call_id = data["call_id"]

    call = db.query(Call).filter(Call.id == call_id).first()
    assert call is not None
    assert call.owner_id == "tenant-42"
    # Inline pipeline runs analyze_call (STT skipped) → terminal state.
    assert call.status in ("TRANSCRIBED", "ANALYZING", "COMPLETED")

    transcript = db.query(Transcript).filter(Transcript.call_id == call_id).first()
    assert transcript is not None
    assert transcript.stt_provider == "external:calle"
    # Provider speaker labels are normalized to agent/customer.
    speakers = [t["speaker"] for t in transcript.turns]
    assert speakers == ["agent", "customer"]
    assert "cuatro mil novecientos" in transcript.raw_text

    # The ingest source + metadata are audited, not silently trusted.
    ingest_event = (
        db.query(CallEvent)
        .filter(CallEvent.call_id == call_id, CallEvent.event_type == "WEBHOOK_INGEST")
        .first()
    )
    assert ingest_event is not None
    assert ingest_event.payload["source"] == "calle"
    assert ingest_event.payload["metadata"]["external_call_id"] == "call_official_123"


def test_audio_first_ingest_registers_for_transcription(client, db):
    payload = {"source": "twilio", "audio_url": "https://example.test/rec/abc.wav"}

    response = client.post("/api/v1/calls/webhook", json=payload)

    assert response.status_code == 202
    assert response.json()["mode"] == "audio"
    call = db.query(Call).filter(Call.id == response.json()["call_id"]).first()
    assert call.storage_path == "https://example.test/rec/abc.wav"


def test_ingest_requires_transcript_or_audio(client):
    response = client.post("/api/v1/calls/webhook", json={"source": "calle"})
    assert response.status_code == 422  # neither transcript_turns nor audio_url
