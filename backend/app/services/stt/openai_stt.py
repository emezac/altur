import logging
from typing import Optional
from app.core.config import settings
from app.services.stt.base import STTProvider, TranscriptResult, Turn

logger = logging.getLogger(__name__)

class OpenAIWhisperProvider(STTProvider):
    def transcribe(self, audio_path: str, language_hint: Optional[str] = None) -> TranscriptResult:
        from openai import OpenAI
        
        api_key = settings.OPENAI_API_KEY
        model = settings.OPENAI_STT_MODEL or "whisper-1"
        
        logger.info(f"OpenAIWhisperProvider: transcribing '{audio_path}' using model={model}")
        
        client = OpenAI(api_key=api_key)
        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                response_format="verbose_json"
            )
            
        turns = []
        lang = getattr(transcript, "language", "es")
        
        # Verbose JSON provides segments
        segments = getattr(transcript, "segments", [])
        if segments:
            for seg in segments:
                turns.append(Turn(
                    speaker="agent",
                    start=float(seg.get("start", 0.0)),
                    end=float(seg.get("end", 0.0)),
                    text=seg.get("text", "").strip()
                ))
        else:
            text = getattr(transcript, "text", "")
            turns.append(Turn(
                speaker="agent",
                start=0.0,
                end=10.0,
                text=text.strip()
            ))
            
        return TranscriptResult(
            language=lang,
            stt_confidence=1.0,
            turns=turns,
            provider="openai",
            model=model
        )
