import json
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, File, UploadFile, Form, Request, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.exceptions import AppError
from app.schemas.call import (
    CallUploadResponse,
    CallDetailResponse,
    PaginatedCallsResponse,
)
from app.schemas.tag_schema import TagUpdateRequest
from app.models.call import Call
from app.services.file_validator import validate_file_size, validate_file_format
from app.services.calls_service import (
    create_call,
    list_calls,
    get_call_detail,
    apply_tag_override,
    retry_failed_call,
    get_call_export,
    PROGRESS_MAP,
)
from app.workers.queue import get_queue
from app.workers.tasks import transcribe_call
from app.services.storage.factory import get_storage_backend
from app.api.health import check_queue_available

router = APIRouter(prefix="/calls")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /calls — Ingest audio file
# ---------------------------------------------------------------------------
@router.post("", response_model=CallUploadResponse, status_code=202)
async def upload_call(
    request: Request,
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Accepts an audio file upload, validates its extension, actual format, size,
    saves it to disk/storage, and persists the PENDING record in the database.

    Pre-flight: returns 503 if the job queue (Redis) is unreachable, so the call
    is never accepted without a worker that can process it.
    """
    # 0. Pre-flight queue check — fail fast before any file I/O or DB writes
    if not check_queue_available():
        raise AppError(
            "QUEUE_UNAVAILABLE",
            "The job queue is currently unavailable. Please try again later.",
            503,
        )

    # 1. Size check via Content-Length header (fast path)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            validate_file_size(int(content_length))
        except ValueError:
            pass

    # 2. Size check via UploadFile object (if populated)
    if file.size is not None:
        validate_file_size(file.size)

    # 3. Format signature check
    header = await file.read(2048)
    await file.seek(0)
    validate_file_format(file.filename, header)

    # Parse optional metadata
    metadata_dict = None
    if metadata:
        try:
            metadata_dict = json.loads(metadata)
        except json.JSONDecodeError:
            raise AppError("VALIDATION_ERROR", "Metadata form field must be a valid JSON string.", 400)

    actual_size = file.size if file.size is not None else (int(content_length) if content_length else 0)

    # 4. Ingest file and register call
    db_call = create_call(
        db=db,
        fileobj=file,
        filename=file.filename,
        mime_type=file.headers.get("content-type", "audio/mpeg"),
        file_size=actual_size,
        metadata=metadata_dict,
    )

    # Capture scalar values before enqueuing (fakeredis burst mode may expire the session)
    call_id = db_call.id
    call_status = db_call.status
    call_filename = db_call.filename
    call_uploaded_at = db_call.uploaded_at

    # 5. Enqueue background transcription task
    queue = get_queue()
    queue.enqueue(transcribe_call, call_id)
    logger.info(f"[call_id={call_id}] Enqueued transcribe_call")

    return CallUploadResponse(
        call_id=call_id,
        status=call_status,
        filename=call_filename,
        uploaded_at=call_uploaded_at,
    )


# ---------------------------------------------------------------------------
# GET /calls — Paginated + filtered list
# ---------------------------------------------------------------------------
@router.get("", response_model=PaginatedCallsResponse)
def list_calls_endpoint(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by call status"),
    tag: Optional[str] = Query(None, description="Filter by tag value"),
    date_from: Optional[datetime] = Query(None, description="Filter calls uploaded after this datetime (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="Filter calls uploaded before this datetime (ISO 8601)"),
    q: Optional[str] = Query(None, description="Full-text search in filename or summary"),
    db: Session = Depends(get_db),
):
    """
    Returns a paginated, filterable list of calls.
    """
    return list_calls(
        db=db,
        page=page,
        page_size=page_size,
        status=status,
        tag=tag,
        date_from=date_from,
        date_to=date_to,
        q=q,
    )


# ---------------------------------------------------------------------------
# GET /calls/{call_id} — Full call detail
# ---------------------------------------------------------------------------
@router.get("/{call_id}", response_model=CallDetailResponse)
def get_call_detail_endpoint(call_id: str, db: Session = Depends(get_db)):
    """
    Returns the complete structured metadata, transcript, summary, tags, and audit events.
    """
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call record not found.")
    return call


# ---------------------------------------------------------------------------
# GET /calls/{call_id}/status — Lightweight status poll
# ---------------------------------------------------------------------------
@router.get("/{call_id}/status")
def get_call_status(call_id: str, db: Session = Depends(get_db)):
    """
    Returns the current processing status and progress percentage for a call.
    Designed as a lightweight polling endpoint for the frontend.
    """
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call record not found.")

    progress = PROGRESS_MAP.get(call.status, 0)

    # Surface the most recent error event message if FAILED
    error_message = None
    if call.status == "FAILED":
        error_events = [e for e in call.events if e.event_type in ("TRANSCRIPTION_ERROR", "ANALYSIS_ERROR", "PROCESSING_ERROR")]
        if error_events:
            last_error = max(error_events, key=lambda e: e.created_at)
            error_message = last_error.payload.get("error") if last_error.payload else None

    return {
        "call_id": call.id,
        "status": call.status,
        "progress": progress,
        "error_message": error_message,
    }


# ---------------------------------------------------------------------------
# PATCH /calls/{call_id}/tags — Override tag values
# ---------------------------------------------------------------------------
@router.patch("/{call_id}/tags", status_code=204)
def update_call_tags(
    call_id: str,
    body: TagUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Applies human override tags for a call.
    Override tags take precedence over model-generated tags in all views.
    An immutable audit record is created for every change.
    """
    apply_tag_override(
        db=db,
        call_id=call_id,
        category=body.category,
        value=body.value,
        reason=body.reason,
    )
    return None


# ---------------------------------------------------------------------------
# POST /calls/{call_id}/retry — Re-enqueue a FAILED call
# ---------------------------------------------------------------------------
@router.post("/{call_id}/retry")
def retry_call(call_id: str, db: Session = Depends(get_db)):
    """
    Re-enqueues a FAILED call for reprocessing.
    Resumes from the last successful stage (transcription or analysis).
    """
    new_status = retry_failed_call(db=db, call_id=call_id)
    return {"call_id": call_id, "status": new_status}


# ---------------------------------------------------------------------------
# GET /calls/{call_id}/export — Full data export as JSON
# ---------------------------------------------------------------------------
@router.get("/{call_id}/export")
def export_call(call_id: str, db: Session = Depends(get_db)):
    """
    Exports the complete call data as a self-contained JSON document.
    Includes transcript, summary, all tags (model + overrides + effective), and audit events.
    """
    data = get_call_export(db=db, call_id=call_id)
    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": f'attachment; filename="call_{call_id}_export.json"'
        },
    )


# ---------------------------------------------------------------------------
# GET /calls/{call_id}/audio — Stream raw audio file
# ---------------------------------------------------------------------------
@router.get("/{call_id}/audio")
def get_call_audio(call_id: str, db: Session = Depends(get_db)):
    """
    Streams the raw ingested audio file from storage.
    """
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call record not found.")

    storage = get_storage_backend()
    if not storage.exists(call.storage_path):
        raise HTTPException(status_code=404, detail="Audio file not found in storage.")

    # Object storage (S3/MinIO) returns a short-lived presigned URL; redirect the
    # browser straight to it so the API never streams the audio itself. Local disk
    # returns None from get_url(), so we serve the file directly.
    presigned_url = storage.get_url(call.storage_path)
    if presigned_url:
        return RedirectResponse(url=presigned_url, status_code=307)

    media_type = call.mime_type or "audio/mpeg"
    return FileResponse(call.storage_path, media_type=media_type)
