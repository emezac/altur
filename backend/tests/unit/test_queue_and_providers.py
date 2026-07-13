import json
import pytest
from unittest.mock import patch

# --- Queue tests ---

def test_get_queue_returns_sync_queue_when_no_redis_url():
    """When REDIS_URL is blank, queue must be synchronous (is_async=False)."""
    # Reset cached connection so it picks up the monkeypatched setting
    import app.workers.queue as queue_mod
    queue_mod._redis_connection = None

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.REDIS_URL = ""
        from rq import Queue as RQQueue
        import fakeredis
        conn = fakeredis.FakeStrictRedis()
        q = RQQueue("default", connection=conn, is_async=False)
        assert q.is_async is False

    # Restore
    queue_mod._redis_connection = None


def test_get_queue_not_async_in_local_mode(monkeypatch):
    """get_queue() creates a synchronous queue when REDIS_URL is not set."""
    from app.core.config import settings
    import app.workers.queue as queue_mod
    queue_mod._redis_connection = None

    monkeypatch.setattr(settings, "REDIS_URL", "")
    q = queue_mod.get_queue()
    assert q.is_async is False

    # Cleanup
    queue_mod._redis_connection = None


# --- FakeSTTProvider tests ---

def test_fake_stt_call01():
    from app.services.stt.fake import FakeSTTProvider
    provider = FakeSTTProvider()
    result = provider.transcribe("/data/audio/uuid_call_01.wav")
    assert result.language == "es"
    assert result.provider == "fake"
    assert result.model == "fake-stt-1"
    assert len(result.turns) > 0
    # First turn must be the agent greeting from Nube Ventas
    assert "Nube Ventas" in result.turns[0].text

def test_fake_stt_call02():
    from app.services.stt.fake import FakeSTTProvider
    provider = FakeSTTProvider()
    result = provider.transcribe("/data/audio/uuid_call_02.wav")
    assert result.language == "es"
    # Roberto call: agent mentions Altura CRM
    full_text = " ".join(t.text for t in result.turns)
    assert "Altura CRM" in full_text

def test_fake_stt_call03():
    from app.services.stt.fake import FakeSTTProvider
    provider = FakeSTTProvider()
    result = provider.transcribe("/data/audio/uuid_call_03.wav")
    assert result.language == "en"
    full_text = " ".join(t.text for t in result.turns)
    # The critical verbatim line must be preserved exactly
    assert "remaining seventy-five dollar gap" in full_text

def test_fake_stt_generic_fallback():
    from app.services.stt.fake import FakeSTTProvider
    provider = FakeSTTProvider()
    result = provider.transcribe("/data/audio/unknown_audio.wav")
    # Falls back to generic 4-turn transcript
    assert len(result.turns) == 4


# --- FakeLLMProvider tests ---

def test_fake_llm_analysis01():
    from app.services.llm.fake import FakeLLMProvider
    provider = FakeLLMProvider()
    transcript_text = "Laura de Nube Ventas llama a Carlos para agendar una demo."
    raw = provider.complete_json("You are an analyzer", transcript_text)
    data = json.loads(raw)
    assert data["summary"]["sentiment"] == "positive"
    assert data["tags"]["next_step"] == "demo_scheduled"
    assert data["tags"]["compliance_flag"] == "none"

def test_fake_llm_analysis02():
    from app.services.llm.fake import FakeLLMProvider
    provider = FakeLLMProvider()
    transcript_text = "Mariana de Altura CRM llama a Roberto sobre precio 4900."
    raw = provider.complete_json("You are an analyzer", transcript_text)
    data = json.loads(raw)
    assert data["tags"]["objection"] == "price_budget"
    assert data["tags"]["compliance_flag"] == "possible_sensitive_data"

def test_fake_llm_analysis03():
    from app.services.llm.fake import FakeLLMProvider
    provider = FakeLLMProvider()
    transcript_text = "Maya Chen from SignalDesk talks to Daniel about support automation."
    raw = provider.complete_json("You are an analyzer", transcript_text)
    data = json.loads(raw)
    # Critical inconsistency must be present
    inconsistencies = data["summary"]["insights"]["inconsistencies"]
    assert any("seventy-five dollar gap" in i for i in inconsistencies)
    assert data["summary"]["sentiment"] == "mixed"

def test_fake_llm_generic_fallback():
    from app.services.llm.fake import FakeLLMProvider
    provider = FakeLLMProvider()
    raw = provider.complete_json("system", "Hello there, random conversation.")
    data = json.loads(raw)
    assert data["tags"]["outcome"] == "no_decision"
