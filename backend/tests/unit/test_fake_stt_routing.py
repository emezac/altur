"""
FakeSTTProvider fixture routing must key off the original filename, not a random
UUID prefix that storage prepends (a UUID hex can contain '01'/'02'/'03').
"""
import pytest

from app.core.config import settings
from app.services.stt.fake import FakeSTTProvider


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    monkeypatch.setattr(settings, "FAKE_PROCESSING_DELAY_SECONDS", 0)


def test_uuid_prefix_containing_02_does_not_shadow_call_03():
    # Simulated storage name: the "uuid" segment contains '02', the real file is call_03.
    path = "/data/audio/a02f1b34-dead-beef-cafe-000000000000_call_03_signaldesk.wav"
    result = FakeSTTProvider().transcribe(path)
    assert result.language == "en"  # call_03 is the English SignalDesk call
    assert any("SignalDesk" in t.text or "Daniel" in t.text or "Maya" in t.text for t in result.turns)


def test_uuid_prefix_containing_03_does_not_shadow_call_02():
    path = "/data/audio/b03c1111-0000-0000-0000-000000000000_call_02_altura.wav"
    result = FakeSTTProvider().transcribe(path)
    assert result.language == "es"  # call_02 is the Spanish Mariana/Roberto call


def test_bare_number_filename_still_routes():
    result = FakeSTTProvider().transcribe("/data/audio/01.wav")
    assert result.language in ("es", "en")
    assert len(result.turns) > 0
