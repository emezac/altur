import json
import logging
from app.core.config import settings
from app.services.llm.base import LLMProvider

logger = logging.getLogger(__name__)

class OpenAILLMProvider(LLMProvider):
    def complete_json(self, system_prompt: str, user_content: str) -> str:
        from openai import OpenAI
        
        api_key = settings.OPENAI_API_KEY
        model = settings.OPENAI_LLM_MODEL or "gpt-4o-mini"
        
        logger.info(f"OpenAILLMProvider: sending complete_json using model={model}")
        
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content
