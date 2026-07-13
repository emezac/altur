from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.fake import FakeLLMProvider

_llm_instance = None

def get_llm_provider() -> LLMProvider:
    global _llm_instance
    if _llm_instance is None:
        provider = (settings.LLM_PROVIDER or "fake").lower()
        if provider == "openai":
            from app.services.llm.openai_llm import OpenAILLMProvider
            _llm_instance = OpenAILLMProvider()
        elif provider == "qwen":
            from app.services.llm.qwen_llm import QwenLLMProvider
            _llm_instance = QwenLLMProvider()
        else:
            _llm_instance = FakeLLMProvider()
    return _llm_instance
