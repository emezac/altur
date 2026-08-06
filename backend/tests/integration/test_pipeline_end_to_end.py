import io
import pytest
from app.models.call import Call
from app.models.transcript import Transcript
from app.models.summary import Summary
from app.models.tag import CallTag

def test_pipeline_end_to_end_fixture_01(client, db):
    """
    Subir call_01.wav -> process -> COMPLETED/DONE
    Assert transcript, summary, and tags match the canonical analysis_01 fixture.
    """
    file_content = b"RIFF\x24\x08\x00\x00WAVEfmt " + b"\x00" * 100
    file_name = "call_01_sales_demo.wav"  # Filename has '01' to trigger fixture 01
    
    response = client.post(
        "/api/v1/calls",
        files={"file": (file_name, io.BytesIO(file_content), "audio/wav")}
    )
    assert response.status_code == 202
    call_id = response.json()["call_id"]
    
    # Verify call transitions to COMPLETED
    call = db.query(Call).filter(Call.id == call_id).first()
    assert call is not None
    assert call.status == "COMPLETED"
    
    # Verify transcript is populated and matches Laura/Carlos (Nube Ventas)
    transcript = db.query(Transcript).filter(Transcript.call_id == call_id).first()
    assert transcript is not None
    assert transcript.language == "es"
    assert "Laura de Nube Ventas" in transcript.raw_text
    
    # Verify summary and insights
    summary = db.query(Summary).filter(Summary.call_id == call_id).first()
    assert summary is not None
    assert "Carlos" in summary.summary_text
    assert summary.insights["sentiment"] == "positive"
    assert summary.insights["purchase_intent"] == "high"
    
    # Verify EAV tags match
    tags = db.query(CallTag).filter(CallTag.call_id == call_id).all()
    tag_map = {t.tag_category: t.tag_value for t in tags}
    assert tag_map["outcome"] == "follow_up_scheduled" or tag_map["outcome"] == "won_deal_closed"
    assert tag_map["next_step"] == "demo_scheduled"
    assert tag_map["objection"] == "no_objections_raised"
    # sentiment / intent_level are now persisted as tags from the summary block
    assert tag_map["sentiment"] == "positive"
    assert tag_map["intent_level"] == "high"


def test_pipeline_persists_sentiment_tag(client, db):
    """
    A completed fake pipeline must persist the sentiment (and intent_level) from the
    analysis summary as CallTag rows, with the *_score carried over as confidence.
    This guards the list/analytics views that read the "sentiment" tag category.
    """
    file_content = b"RIFF\x24\x08\x00\x00WAVEfmt " + b"\x00" * 100
    file_name = "call_01_sales_demo.wav"  # Filename has '01' to trigger fixture 01

    response = client.post(
        "/api/v1/calls",
        files={"file": (file_name, io.BytesIO(file_content), "audio/wav")},
    )
    assert response.status_code == 202
    call_id = response.json()["call_id"]

    call = db.query(Call).filter(Call.id == call_id).first()
    assert call is not None and call.status == "COMPLETED"

    sentiment_tag = (
        db.query(CallTag)
        .filter(CallTag.call_id == call_id, CallTag.tag_category == "sentiment")
        .first()
    )
    assert sentiment_tag is not None, "pipeline did not persist a sentiment tag"
    assert sentiment_tag.tag_value == "positive"
    assert sentiment_tag.source == "model"
    assert 0.0 <= sentiment_tag.confidence <= 1.0

def test_pipeline_end_to_end_fixture_03_inconsistencies(client, db):
    """
    Subir call_03.wav (SignalDesk) -> process -> COMPLETED/DONE
    Verify transcript text keeps the literal verbatim and insights contains seventy-five dollar gap inconsistency.
    """
    file_content = b"RIFF\x24\x08\x00\x00WAVEfmt " + b"\x00" * 100
    file_name = "call_03_signaldesk.wav"  # Filename has '03' to trigger fixture 03
    
    response = client.post(
        "/api/v1/calls",
        files={"file": (file_name, io.BytesIO(file_content), "audio/wav")}
    )
    assert response.status_code == 202
    call_id = response.json()["call_id"]
    
    # Verify call transitions to COMPLETED
    call = db.query(Call).filter(Call.id == call_id).first()
    assert call is not None
    assert call.status == "COMPLETED"
    
    # Verify transcript contains "remaining seventy-five dollar gap"
    transcript = db.query(Transcript).filter(Transcript.call_id == call_id).first()
    assert transcript is not None
    assert "remaining seventy-five dollar gap" in transcript.raw_text
    
    # Verify summary insights contain the inconsistency warning
    summary = db.query(Summary).filter(Summary.call_id == call_id).first()
    assert summary is not None
    
    inconsistencies = summary.insights.get("inconsistencies", [])
    assert any("seventy-five dollar gap" in i for i in inconsistencies)
