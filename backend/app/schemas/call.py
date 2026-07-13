from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List, Dict, Any

class CallUploadResponse(BaseModel):
    call_id: str
    status: str
    filename: str
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CallListResponse(BaseModel):
    id: str
    filename: str
    mime_type: str
    file_size_bytes: int
    status: str
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TurnSchema(BaseModel):
    speaker: str
    text: str
    start: float
    end: float

class TranscriptSchema(BaseModel):
    id: str
    language: str
    raw_text: str
    turns: List[TurnSchema]
    stt_provider: str
    stt_model: str
    stt_confidence: Optional[float]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SummarySchema(BaseModel):
    id: str
    summary_text: str
    key_points: List[str]
    insights: Dict[str, Any]
    llm_provider: str
    llm_model: str
    prompt_version: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TagSchema(BaseModel):
    tag_category: str
    tag_value: str
    confidence: float
    reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class EventSchema(BaseModel):
    id: str
    event_type: str
    payload: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CallDetailResponse(BaseModel):
    id: str
    filename: str
    mime_type: str
    file_size_bytes: int
    status: str
    duration_seconds: Optional[float] = None
    uploaded_at: datetime

    transcript: Optional[TranscriptSchema] = None
    summary: Optional[SummarySchema] = None
    tags: List[TagSchema] = []
    events: List[EventSchema] = []

    model_config = ConfigDict(from_attributes=True)

