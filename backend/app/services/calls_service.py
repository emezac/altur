import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.call import Call
from app.models.event import CallEvent
from app.models.transcript import Transcript
from app.models.tag import CallTag, CallTagOverride
from app.schemas.call import CallListItem, PaginatedCallsResponse, TagOverrideSchema
from app.core.exceptions import AppError
from app.services.storage.factory import get_storage_backend

logger = logging.getLogger(__name__)


def create_call(
    db: Session,
    fileobj,
    filename: str,
    mime_type: str,
    file_size: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> Call:
    """
    Creates a Call record in the database and writes its audio file to storage.
    If the database operation fails, the stored file is deleted (atomic rollback).
    """
    storage = get_storage_backend()
    storage_path = None

    try:
        # 1. Save file to storage
        storage_path = storage.save(fileobj, filename)
        logger.info(f"Saved file '{filename}' to storage: {storage_path}")

        # 2. Register call in database
        db_call = Call(
            filename=filename,
            storage_path=storage_path,
            mime_type=mime_type,
            file_size_bytes=file_size,
            status="PENDING",
        )
        db.add(db_call)
        db.flush()  # Generates db_call.id

        # Create initial status change event
        event = CallEvent(
            call_id=db_call.id,
            event_type="STATUS_CHANGE",
            payload={"from_status": None, "to_status": "PENDING"},
        )
        db.add(event)

        db.commit()
        logger.info(f"Successfully registered call {db_call.id} in DB with status PENDING")
        return db_call

    except Exception as e:
        logger.error(f"Failed to save call to database: {e}. Executing atomic rollback.")
        db.rollback()

        if storage_path:
            try:
                storage.delete(storage_path)
                logger.info(f"Cleaned up file at storage path: {storage_path}")
            except Exception as clean_err:
                logger.error(f"Failed to delete stored file during rollback: {clean_err}")

        raise e


PROGRESS_MAP = {
    "PENDING": 5,
    "TRANSCRIBING": 35,
    "TRANSCRIBED": 60,
    "ANALYZING": 85,
    "COMPLETED": 100,
    "DONE": 100,
    "FAILED": 100,
}


def _effective_tags(all_tags):
    """
    Computes the effective tag for each category.
    Override tags take precedence over model tags.
    Returns a dict {category -> CallTag}.
    """
    effective = {}
    for t in all_tags:
        cat = t.tag_category
        if cat not in effective or t.source == "override":
            effective[cat] = t
    return effective


def get_call_or_404(db: Session, call_id: str) -> Call:
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        raise AppError("NOT_FOUND", f"Call '{call_id}' not found.", 404)
    return call


def list_calls(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    tag: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    q: Optional[str] = None,
) -> PaginatedCallsResponse:
    from app.models.summary import Summary

    query = db.query(Call)

    if status:
        query = query.filter(Call.status == status)
    if date_from:
        query = query.filter(Call.uploaded_at >= date_from)
    if date_to:
        query = query.filter(Call.uploaded_at <= date_to)
    if q:
        query = (
            query.outerjoin(Summary)
            .filter(
                (Call.filename.ilike(f"%{q}%"))
                | (Summary.summary_text.ilike(f"%{q}%"))
            )
        )
    if tag:
        query = query.join(CallTag, CallTag.call_id == Call.id).filter(
            CallTag.tag_value == tag
        )

    total = query.count()
    calls = (
        query.order_by(Call.uploaded_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for call in calls:
        effective = _effective_tags(call.tags)
        sentiment_tag = effective.get("sentiment")
        items.append(
            CallListItem(
                id=call.id,
                filename=call.filename,
                uploaded_at=call.uploaded_at,
                file_size_bytes=call.file_size_bytes,
                duration_seconds=call.duration_seconds,
                status=call.status,
                sentiment=sentiment_tag.tag_value if sentiment_tag else None,
            )
        )

    return PaginatedCallsResponse(items=items, page=page, page_size=page_size, total=total)


def get_call_detail(db: Session, call_id: str) -> dict:
    call = get_call_or_404(db, call_id)
    effective = _effective_tags(call.tags)

    from app.core.config import settings
    from app.services.storage.factory import get_storage_backend

    storage = get_storage_backend()
    audio_url = storage.get_url(call.storage_path) or f"/api/v1/calls/{call.id}/audio"

    return {
        "id": call.id,
        "filename": call.filename,
        "mime_type": call.mime_type,
        "file_size_bytes": call.file_size_bytes,
        "status": call.status,
        "duration_seconds": call.duration_seconds,
        "uploaded_at": call.uploaded_at,
        "audio_url": audio_url,
        "transcript": call.transcript,
        "summary": call.summary,
        "tags": list(effective.values()),
        "overrides": call.overrides,
        "events": call.events,
    }


def apply_tag_override(
    db: Session, call_id: str, category: str, value: str, reason: Optional[str]
) -> None:
    call = get_call_or_404(db, call_id)

    # Find existing model tag for this category to record previous_value
    model_tag = next(
        (t for t in call.tags if t.tag_category == category and t.source == "model"),
        None,
    )
    previous_value = model_tag.tag_value if model_tag else None
    action = "changed" if previous_value else "added"

    # Upsert call_tag with source=override
    override_tag = next(
        (t for t in call.tags if t.tag_category == category and t.source == "override"),
        None,
    )
    if override_tag:
        override_tag.tag_value = value
        override_tag.confidence = 1.0
        override_tag.reason = reason
    else:
        override_tag = CallTag(
            call_id=call_id,
            tag_category=category,
            tag_value=value,
            confidence=1.0,
            reason=reason,
            source="override",
        )
        db.add(override_tag)

    # Always insert a new override audit record
    audit = CallTagOverride(
        call_id=call_id,
        tag_category=category,
        previous_value=previous_value,
        new_value=value,
        action=action,
        reason=reason,
    )
    db.add(audit)
    db.commit()


def retry_failed_call(db: Session, call_id: str) -> str:
    """
    Re-enqueues the appropriate task for a FAILED call.
    Returns the new status.
    """
    call = get_call_or_404(db, call_id)
    if call.status != "FAILED":
        raise AppError("INVALID_STATE", f"Call is in state '{call.status}', not FAILED.", 409)

    from app.workers.queue import get_queue
    from app.workers.tasks import transcribe_call, analyze_call
    from app.services.state_machine import transition

    # Determine resume stage: if transcript already exists, skip to analyzing
    has_transcript = call.transcript is not None

    if has_transcript:
        ok = transition(db, call_id, "FAILED", "TRANSCRIBED")
        if ok:
            get_queue().enqueue(analyze_call, call_id)
        return "TRANSCRIBED"
    else:
        ok = transition(db, call_id, "FAILED", "PENDING")
        if ok:
            get_queue().enqueue(transcribe_call, call_id)
        return "PENDING"


def get_call_export(db: Session, call_id: str) -> dict:
    call = get_call_or_404(db, call_id)
    effective = _effective_tags(call.tags)

    model_tags = [t for t in call.tags if t.source == "model"]
    override_tags = [t for t in call.tags if t.source == "override"]

    def tag_to_dict(t):
        return {
            "category": t.tag_category,
            "value": t.tag_value,
            "confidence": t.confidence,
            "reason": t.reason,
            "source": t.source,
        }

    transcript_data = None
    if call.transcript:
        tr = call.transcript
        transcript_data = {
            "language": tr.language,
            "raw_text": tr.raw_text,
            "turns": tr.turns,
            "stt_provider": tr.stt_provider,
            "stt_model": tr.stt_model,
            "stt_confidence": tr.stt_confidence,
        }

    summary_data = None
    if call.summary:
        s = call.summary
        summary_data = {
            "summary_text": s.summary_text,
            "key_points": s.key_points,
            "insights": s.insights,
            "llm_provider": s.llm_provider,
            "llm_model": s.llm_model,
            "prompt_version": s.prompt_version,
        }

    return {
        "call_id": call.id,
        "filename": call.filename,
        "status": call.status,
        "mime_type": call.mime_type,
        "file_size_bytes": call.file_size_bytes,
        "duration_seconds": call.duration_seconds,
        "uploaded_at": call.uploaded_at.isoformat() if call.uploaded_at else None,
        "transcript": transcript_data,
        "summary": summary_data,
        "tags_model": [tag_to_dict(t) for t in model_tags],
        "tags_override": [tag_to_dict(t) for t in override_tags],
        "tags_effective": [tag_to_dict(effective[c]) for c in effective],
        "overrides": [
            {
                "category": o.tag_category,
                "previous_value": o.previous_value,
                "new_value": o.new_value,
                "action": o.action,
                "reason": o.reason,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in call.overrides
        ],
        "events": [
            {
                "event_type": e.event_type,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in call.events
        ],
    }
