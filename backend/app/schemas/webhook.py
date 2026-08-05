"""
Provider-agnostic ingestion contract.

CALL-E (and other telephony providers) push terminal call events as a transcript,
not raw audio — see docs/api_contract_findings.md. This schema is the single entry
point for ANY source: pass `transcript_turns` when the provider already transcribed
the call (CALL-E, Aircall), or `audio_url` when only recorded audio is available
(Twilio, a call-recording bucket). CALL-E is the first connector, not the only input.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, model_validator


class IngestTurn(BaseModel):
    speaker: str = Field(description="Provider speaker label; normalized to agent/customer/unknown")
    text: str = Field(min_length=1)
    offset_seconds: Optional[float] = Field(
        default=None, ge=0, description="Seconds from call start; None when the source had no timestamp"
    )


class WebhookIngestRequest(BaseModel):
    source: str = Field(min_length=1, max_length=100, description="Originating provider, e.g. 'calle', 'twilio'")
    language: Optional[str] = Field(default=None, description="ISO code if known; else left for detection")
    audio_url: Optional[str] = Field(default=None, description="HTTPS URL to recorded audio (audio-first sources)")
    transcript_turns: Optional[List[IngestTurn]] = Field(
        default=None, description="Turn-level transcript (transcript-first sources like CALL-E)"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Caller-owned correlation keys (workflow id, external call id, tenant)"
    )
    owner_id: Optional[str] = Field(default=None, description="Tenant/owner for multi-tenant analysis")

    @model_validator(mode="after")
    def _require_one_input(self) -> "WebhookIngestRequest":
        if not self.transcript_turns and not self.audio_url:
            raise ValueError("Provide either transcript_turns or audio_url.")
        return self


class WebhookIngestResponse(BaseModel):
    call_id: str
    status: str
    source: str
    mode: str  # "transcript" (STT skipped) | "audio" (STT required)
