"""
Ingestion service for the provider-agnostic webhook.

Two modes:
  * transcript-first  -> the provider already transcribed the call. We persist the
    Transcript directly, skip STT entirely, and move the call straight to
    TRANSCRIBED so analyze_call can run our own 7-category analysis on real content.
  * audio-first       -> only recorded audio is available. We register the call
    pointing at the audio URL and defer to transcribe_call (the STT provider must
    support URL fetch — see the adapter seam noted in the endpoint).
"""
import logging
import uuid
from typing import Tuple

from sqlalchemy.orm import Session

from app.models.call import Call
from app.models.event import CallEvent
from app.models.transcript import Transcript
from app.services.state_machine import transition
from app.schemas.webhook import WebhookIngestRequest

logger = logging.getLogger(__name__)

# Normalize any provider's speaker label to the two roles our schema/analysis use.
_SPEAKER_MAP = {
    "bot": "agent", "agent": "agent", "assistant": "agent", "rep": "agent",
    "user": "customer", "customer": "customer", "caller": "customer", "callee": "customer",
}


def _normalize_speaker(label: str) -> str:
    return _SPEAKER_MAP.get((label or "").strip().lower(), "unknown")


def ingest_from_webhook(db: Session, payload: WebhookIngestRequest) -> Tuple[Call, str]:
    """Registers a Call from a webhook payload. Returns (call, mode)."""
    mode = "transcript" if payload.transcript_turns else "audio"
    short = uuid.uuid4().hex[:8]

    db_call = Call(
        filename=f"{payload.source}-{short}",
        # Audio mode stores the fetchable URL; transcript mode has no media.
        storage_path=payload.audio_url or f"webhook://{payload.source}",
        mime_type="audio/mpeg" if mode == "audio" else "application/json",
        file_size_bytes=0,
        status="PENDING",
        owner_id=payload.owner_id,
    )
    db.add(db_call)
    db.flush()  # generates db_call.id

    db.add(CallEvent(call_id=db_call.id, event_type="STATUS_CHANGE",
                     payload={"from_status": None, "to_status": "PENDING"}))
    # Audit the ingest source + caller metadata rather than trusting it silently.
    db.add(CallEvent(call_id=db_call.id, event_type="WEBHOOK_INGEST",
                     payload={"source": payload.source, "mode": mode, "metadata": payload.metadata or {}}))
    db.commit()

    if mode == "audio":
        logger.info(f"[call_id={db_call.id}] Ingested audio-first from '{payload.source}' -> transcribe_call")
        return db_call, mode

    # transcript-first: persist the transcript and jump to TRANSCRIBED (no STT).
    turns_list = [
        {
            "speaker": _normalize_speaker(t.speaker),
            "start": float(t.offset_seconds) if t.offset_seconds is not None else 0.0,
            "end": None,
            "text": t.text,
        }
        for t in payload.transcript_turns
    ]
    raw_text = " ".join(t.text for t in payload.transcript_turns)

    db.add(Transcript(
        call_id=db_call.id,
        language=payload.language or "und",
        raw_text=raw_text,
        turns=turns_list,
        stt_confidence=None,
        stt_provider=f"external:{payload.source}",
        stt_model="external",
    ))
    db.flush()

    if not transition(db, db_call.id, "PENDING", "TRANSCRIBED"):
        logger.error(f"[call_id={db_call.id}] Could not transition PENDING->TRANSCRIBED for ingested transcript")

    logger.info(f"[call_id={db_call.id}] Ingested transcript-first from '{payload.source}' -> analyze_call")
    return db_call, mode
