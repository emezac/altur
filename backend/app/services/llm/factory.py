from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.fake import FakeLLMProvider

_llm_instance = None

def get_llm_provider() -> LLMProvider:
    global _llm_instance
    if _llm_instance is None:
        if settings.LLM_PROVIDER == "openai":
            from app.services.llm.openai_llm import OpenAILLMProvider
            _llm_instance = OpenAILLMProvider()
        else:
            _llm_instance = FakeLLMProvider()
    return _llm_instance
