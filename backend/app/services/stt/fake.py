import json
import time
import logging
import os
from typing import Optional
from app.core.config import settings
from app.services.stt.base import STTProvider, TranscriptResult, Turn

logger = logging.getLogger(__name__)

# Resolved absolute path to the fixtures directory:
# __file__ is at app/services/stt/fake.py (relative to backend/)
# We go up 3 levels to reach backend/, then descend into tests/fixtures/transcripts/
_FIXTURES_DIR = os.path.join(
    os.path.dirname(__file__),   # app/services/stt/
    "..",                         # app/services/
    "..",                         # app/
    "..",                         # backend/
    "tests", "fixtures", "transcripts"
)

_GENERIC_TRANSCRIPT = {
    "language": "es",
    "stt_confidence": 0.80,
    "turns": [
        {"speaker": "agent", "start": 0.0, "end": 5.0, "text": "Hello, how can I help you today?"},
        {"speaker": "customer", "start": 5.5, "end": 10.0, "text": "I have a question about your product."},
        {"speaker": "agent", "start": 10.5, "end": 15.0, "text": "Of course, I will be happy to help."},
        {"speaker": "customer", "start": 15.5, "end": 20.0, "text": "Thank you very much."}
    ]
}


def _load_fixture(fixture_name: str) -> dict:
    path = os.path.normpath(os.path.join(_FIXTURES_DIR, fixture_name))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load fixture '{fixture_name}': {e}. Using generic transcript.")
        return _GENERIC_TRANSCRIPT


class FakeSTTProvider(STTProvider):
    """
    Deterministic fake STT provider for local development and testing.
    Selects a fixture based on the filename and simulates processing delay.
    """

    def transcribe(self, audio_path: str, language_hint: Optional[str] = None) -> TranscriptResult:
        filename = os.path.basename(audio_path).lower()
        logger.info(f"FakeSTTProvider: transcribing '{filename}'")

        # Simulate processing latency
        delay = getattr(settings, "FAKE_PROCESSING_DELAY_SECONDS", 0)
        if delay > 0:
            logger.debug(f"FakeSTTProvider: simulating {delay}s processing delay.")
            time.sleep(delay)

        # Route to the appropriate fixture based on filename
        if "01" in filename or "call_01" in filename:
            data = _load_fixture("call_01.json")
        elif "02" in filename or "call_02" in filename:
            data = _load_fixture("call_02.json")
        elif "03" in filename or "call_03" in filename:
            data = _load_fixture("call_03.json")
        else:
            logger.warning(f"FakeSTTProvider: no fixture matched for '{filename}'. Using generic fallback.")
            data = _GENERIC_TRANSCRIPT

        turns = [Turn(**t) for t in data["turns"]]
        return TranscriptResult(
            language=data["language"],
            stt_confidence=data["stt_confidence"],
            turns=turns,
            provider="fake",
            model="fake-stt-1"
        )
