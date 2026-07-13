from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel, Field

class Turn(BaseModel):
    speaker: str = Field(description="Can be 'agent' or 'customer'")
    start: float = Field(description="Start time of the turn in seconds")
    end: float = Field(description="End time of the turn in seconds")
    text: str = Field(description="Transcribed spoken text")

class TranscriptResult(BaseModel):
    language: str = Field(description="Detected language code (e.g. 'es', 'en')")
    stt_confidence: float = Field(description="Transcription confidence score from 0.0 to 1.0")
    turns: List[Turn] = Field(description="Chronological list of speaker turns")
    provider: str = Field(description="The provider name that performed the STT (e.g. 'fake', 'openai')")
    model: str = Field(description="The specific model used (e.g. 'fake-stt-1', 'whisper-1')")

class STTProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str, language_hint: Optional[str] = None) -> TranscriptResult:
        """
        Transcribes the audio file located at audio_path.
        """
        pass
