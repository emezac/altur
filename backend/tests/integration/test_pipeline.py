import io
import pytest
from unittest.mock import patch
from app.models.call import Call
from app.models.transcript import Transcript
from app.models.summary import Summary
from app.models.tag import CallTag
from app.models.event import CallEvent


def test_pipeline_execution_success(client, db):
    """
    Verifies that a valid call upload processes through the entire STT and LLM
    pipeline inline when is_async=False. Persists data correctly across all tables.
    """
    file_content = b"RIFF\x24\x08\x00\x00WAVEfmt " + b"\x00" * 100
    file_name = "call_01_sales_audio.wav"   # '01' triggers Nube Ventas fixtures

    response = client.post(
        "/api/v1/calls",
        files={"file": (file_name, io.BytesIO(file_content), "audio/wav")}
    )
    assert response.status_code == 202
    call_id = response.json()["call_id"]

    # 1. Verify Call status is COMPLETED
    db_call = db.query(Call).filter(Call.id == call_id).first()
    assert db_call is not None
    assert db_call.status == "COMPLETED"

    # 2. Verify Transcript record
    transcript = db.query(Transcript).filter(Transcript.call_id == call_id).first()
    assert transcript is not None
    assert transcript.language == "es"
    assert "Laura de Nube Ventas" in transcript.raw_text
    assert len(transcript.turns) == 13
    assert transcript.stt_provider == "fake"
    assert transcript.stt_model == "fake-stt-1"

    # 3. Verify Summary record (using actual schema: summary_text, insights blob)
    summary = db.query(Summary).filter(Summary.call_id == call_id).first()
    assert summary is not None
    assert "Carlos" in summary.summary_text
    assert len(summary.key_points) == 5
    assert summary.insights["sentiment"] == "positive"
    assert summary.insights["purchase_intent"] == "high"
    assert summary.llm_provider == "fake"

    # 4. Verify CallTag EAV rows
    tags = db.query(CallTag).filter(CallTag.call_id == call_id).all()
    assert len(tags) >= 3
    tag_map = {t.tag_category: t.tag_value for t in tags}
    assert tag_map["outcome"] == "follow_up_scheduled"
    assert tag_map["next_step"] == "demo_scheduled"
    assert tag_map["objection"] == "no_objections_raised"

    # 5. Verify status change audit trail order
    events = db.query(CallEvent).filter(CallEvent.call_id == call_id).order_by(CallEvent.created_at).all()
    status_changes = [e.payload["to_status"] for e in events if e.event_type == "STATUS_CHANGE"]
    assert status_changes == ["PENDING", "TRANSCRIBING", "TRANSCRIBED", "ANALYZING", "COMPLETED"]


def test_pipeline_execution_error_boundary(client, db):
    """
    Verifies that if a step in the pipeline fails (e.g. LLM crashes), the error
    boundary transitions call status to FAILED and records the error details.
    """
    file_content = b"RIFF\x24\x08\x00\x00WAVEfmt " + b"\x00" * 100
    file_name = "call_01_sales_audio.wav"

    # Mock the LLM provider to raise an exception during complete_json execution
    with patch("app.services.llm.fake.FakeLLMProvider.complete_json",
               side_effect=ValueError("Simulated LLM service crash")):
        response = client.post(
            "/api/v1/calls",
            files={"file": (file_name, io.BytesIO(file_content), "audio/wav")}
        )
        assert response.status_code == 202
        call_id = response.json()["call_id"]

    # Verify Call status is FAILED
    db_call = db.query(Call).filter(Call.id == call_id).first()
    assert db_call is not None
    assert db_call.status == "FAILED"

    # Verify an ERROR audit event was recorded in the database
    error_event = db.query(CallEvent).filter(
        CallEvent.call_id == call_id,
        CallEvent.event_type == "ERROR"
    ).first()
    assert error_event is not None
    assert error_event.payload["step"] == "ANALYZE"
    assert "Simulated LLM service crash" in error_event.payload["error"]
