import json
import pytest
from unittest.mock import MagicMock, call as mock_call
from app.models.call import Call
from app.models.transcript import Transcript
from app.models.summary import Summary
from app.workers.tasks import analyze_call

def _make_call_and_transcript(db):
    c = Call(
        filename="test_llm.wav",
        storage_path="path/test_llm.wav",
        mime_type="audio/wav",
        file_size_bytes=1024,
        status="TRANSCRIBED"
    )
    db.add(c)
    db.commit()
    
    t = Transcript(
        call_id=c.id,
        language="es",
        raw_text="Hola, soy agente de ventas",
        turns=[{"speaker": "agent", "start": 0.0, "end": 2.0, "text": "Hola, soy agente de ventas"}],
        stt_confidence=0.9,
        stt_provider="fake",
        stt_model="fake-stt"
    )
    db.add(t)
    db.commit()
    db.refresh(c)
    return c

_VALID_RESPONSE = {
    "summary": {
        "executive_summary": "Successful parse summary",
        "key_points": ["point 1"],
        "sentiment": "positive",
        "sentiment_score": 0.95,
        "purchase_intent": "high",
        "intent_score": 0.9,
        "insights": {
            "buying_signals": ["wants demo"],
            "risks": [],
            "inconsistencies": [],
            "tone_notes": "very positive"
        }
    },
    "tags": {
        "outcome": "won_deal_closed",
        "outcome_confidence": 0.9,
        "next_step": "demo_scheduled",
        "next_step_confidence": 0.9,
        "objection": "no_objections_raised",
        "objection_confidence": 1.0,
        "compliance_flag": "none",
        "product_interest": ["Pro Plan"]
    }
}

def test_llm_parse_success(db, monkeypatch):
    call = _make_call_and_transcript(db)
    
    fake_llm = MagicMock()
    fake_llm.complete_json.return_value = json.dumps(_VALID_RESPONSE)
    monkeypatch.setattr("app.workers.tasks.get_llm_provider", lambda: fake_llm)
    
    analyze_call(call.id)
    
    db.refresh(call)
    assert call.status == "COMPLETED"
    assert call.summary is not None
    assert call.summary.summary_text == "Successful parse summary"
    assert call.summary.insights.get("needs_review") is not True

def test_llm_parse_malformed_triggers_self_repair(db, monkeypatch):
    call = _make_call_and_transcript(db)
    
    fake_llm = MagicMock()
    # First return is invalid JSON, second is valid JSON
    fake_llm.complete_json.side_effect = [
        "THIS IS NOT VALID JSON!!!",
        json.dumps(_VALID_RESPONSE)
    ]
    monkeypatch.setattr("app.workers.tasks.get_llm_provider", lambda: fake_llm)
    
    analyze_call(call.id)
    
    db.refresh(call)
    assert call.status == "COMPLETED"
    assert call.summary is not None
    assert call.summary.summary_text == "Successful parse summary"
    
    # Assert complete_json was called twice (first attempt + self-repair attempt)
    assert fake_llm.complete_json.call_count == 2
    # Second prompt must contain self-repair warning instructions
    second_prompt = fake_llm.complete_json.call_args_list[1][0][0]
    assert "FAILED TO PARSE AS VALID JSON" in second_prompt

def test_llm_parse_double_failure_fallback_needs_review(db, monkeypatch):
    call = _make_call_and_transcript(db)
    
    fake_llm = MagicMock()
    # Both returns are invalid JSON
    fake_llm.complete_json.side_effect = [
        "INVALID JSON 1",
        "INVALID JSON 2"
    ]
    monkeypatch.setattr("app.workers.tasks.get_llm_provider", lambda: fake_llm)
    
    analyze_call(call.id)
    
    db.refresh(call)
    # The pipeline must complete successfully without exception, but status must be COMPLETED
    assert call.status == "COMPLETED"
    assert call.summary is not None
    assert "Review Required" in call.summary.summary_text
    assert "INVALID JSON 2" in call.summary.summary_text
    assert call.summary.insights.get("needs_review") is True
