import json
import time
import logging
import os
from app.core.config import settings
from app.services.llm.base import LLMProvider

logger = logging.getLogger(__name__)

# Resolved absolute path to the fixtures directory:
# __file__ is at app/services/llm/fake.py (relative to backend/)
# We go up 3 levels to reach backend/, then descend into tests/fixtures/analyses/
_FIXTURES_DIR = os.path.join(
    os.path.dirname(__file__),   # app/services/llm/
    "..",                         # app/services/
    "..",                         # app/
    "..",                         # backend/
    "tests", "fixtures", "analyses"
)

_GENERIC_ANALYSIS = {
    "summary": {
        "executive_summary": "A sales call was recorded and analyzed. No specific fixture matched the content.",
        "key_points": ["Call was processed by the fake LLM provider."],
        "sentiment": "neutral",
        "sentiment_score": 0.50,
        "purchase_intent": "low",
        "intent_score": 0.30,
        "insights": {
            "buying_signals": [],
            "risks": [],
            "inconsistencies": [],
            "tone_notes": "Generic analysis — no fixture matched."
        }
    },
    "tags": {
        "outcome": "no_decision",
        "outcome_confidence": 0.50,
        "next_step": "send_proposal",
        "next_step_confidence": 0.50,
        "objection": "no_objections_raised",
        "objection_confidence": 0.50,
        "compliance_flag": "none",
        "product_interest": []
    }
}


def _load_fixture(fixture_name: str) -> dict:
    path = os.path.normpath(os.path.join(_FIXTURES_DIR, fixture_name))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load analysis fixture '{fixture_name}': {e}. Using generic analysis.")
        return _GENERIC_ANALYSIS


class FakeLLMProvider(LLMProvider):
    """
    Deterministic fake LLM provider for local development and testing.
    Matches the transcript content against known keywords to select
    a canonical analysis fixture.
    """

    def complete_json(self, system_prompt: str, user_content: str) -> str:
        logger.info("FakeLLMProvider: generating fake analysis.")

        # Simulate processing latency
        delay = getattr(settings, "FAKE_PROCESSING_DELAY_SECONDS", 0)
        if delay > 0:
            logger.debug(f"FakeLLMProvider: simulating {delay}s processing delay.")
            time.sleep(delay)

        content_lower = user_content.lower()

        # Route to appropriate fixture based on transcript content keywords
        if "nube ventas" in content_lower or "nubeventas" in content_lower:
            data = _load_fixture("analysis_01.json")
            logger.debug("FakeLLMProvider: matched analysis_01 (Nube Ventas).")
        elif "altura crm" in content_lower:
            data = _load_fixture("analysis_02.json")
            logger.debug("FakeLLMProvider: matched analysis_02 (Altura CRM).")
        elif "signaldesk" in content_lower or "signal desk" in content_lower:
            data = _load_fixture("analysis_03.json")
            logger.debug("FakeLLMProvider: matched analysis_03 (SignalDesk).")
        else:
            logger.warning("FakeLLMProvider: no keyword matched transcript content. Using generic analysis.")
            data = _GENERIC_ANALYSIS

        return json.dumps(data, ensure_ascii=False)
