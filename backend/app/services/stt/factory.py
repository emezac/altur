from app.core.config import settings
from app.services.stt.base import STTProvider
from app.services.stt.fake import FakeSTTProvider

_stt_instance = None

def get_stt_provider() -> STTProvider:
    global _stt_instance
    if _stt_instance is None:
        if settings.STT_PROVIDER == "openai":
            from app.services.stt.openai_stt import OpenAIWhisperProvider
            _stt_instance = OpenAIWhisperProvider()
        else:
            _stt_instance = FakeSTTProvider()
    return _stt_instance
