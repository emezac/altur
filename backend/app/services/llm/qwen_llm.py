import logging

from app.core.config import settings
from app.services.llm.base import LLMProvider

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    """
    Deep-thinking models frequently wrap their answer in a ```json ... ``` block.
    Strip a single leading/trailing fence so json.loads() sees raw JSON.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    # Drop the opening fence line (``` or ```json) and the trailing ``` line.
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


class QwenLLMProvider(LLMProvider):
    """
    Alibaba Qwen provider via the DashScope OpenAI-compatible endpoint.

    Intended for local development (OpenAI stays the production default). Qwen's
    "-plus"/"-max" tiers are deep-thinking models: DashScope emits reasoning on a
    separate `reasoning_content` channel and requires stream=True when thinking is
    enabled, so we always stream and accumulate only the visible `content`.
    """

    def complete_json(self, system_prompt: str, user_content: str) -> str:
        from openai import OpenAI

        model = settings.QWEN_MODEL
        logger.info(f"QwenLLMProvider: sending complete_json using model={model}")

        client = OpenAI(
            api_key=settings.QWEN_TOKEN,
            base_url=settings.QWEN_BASE_URL,
        )

        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            extra_body={"enable_thinking": settings.QWEN_ENABLE_THINKING},
            stream=True,
        )

        content_parts: list[str] = []
        for chunk in completion:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # reasoning_content is the model's private thinking channel — ignore it;
            # only `content` carries the final answer we want to parse as JSON.
            if getattr(delta, "content", None):
                content_parts.append(delta.content)

        raw = "".join(content_parts)
        return _strip_code_fences(raw)
