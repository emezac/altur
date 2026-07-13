import json
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, File, UploadFile, Form, Request, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.exceptions import AppError
from app.schemas.call import CallUploadResponse, CallListResponse, CallDetailResponse
from app.models.call import Call
from app.services.file_validator import validate_file_size, validate_file_format
from app.services.calls_service import create_call
from app.workers.queue import get_queue
from app.workers.tasks import transcribe_call
from app.services.storage.factory import get_storage_backend

router = APIRouter(prefix="/calls")
logger = logging.getLogger(__name__)

@router.post("", response_model=CallUploadResponse, status_code=202)
async def upload_call(
    request: Request,
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Accepts audio file upload, validates its extension, actual format, size,
    saves it to disk/storage, and persists the PENDING record in the database.
    """
    # 1. Size check via Content-Length header
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
    # Read the first 2048 bytes for format detection
    header = await file.read(2048)
    await file.seek(0)  # Reset pointer back to the beginning

    validate_file_format(file.filename, header)

    # Parse optional metadata
    metadata_dict = None
    if metadata:
        try:
            metadata_dict = json.loads(metadata)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON string in metadata form field.")
            raise AppError("VALIDATION_ERROR", "Metadata form field must be a valid JSON string.", 400)

    # Determine file size
    actual_size = file.size if file.size is not None else (int(content_length) if content_length else 0)
    
    # 4. Ingest file and register call
    db_call = create_call(
        db=db,
        fileobj=file,
        filename=file.filename,
        mime_type=file.headers.get("content-type", "audio/mpeg"),
        file_size=actual_size,
        metadata=metadata_dict
    )

    # Capture scalar values before enqueuing — synchronous inline tasks
    # (fakeredis is_async=False) may cause the session to expire the object.
    call_id = db_call.id
    call_status = db_call.status
    call_filename = db_call.filename
    call_uploaded_at = db_call.uploaded_at

    # 5. Enqueue background transcription task
    queue = get_queue()
    queue.enqueue(transcribe_call, call_id)
    logger.info(f"Enqueued transcribe_call for call_id={call_id}")

    return CallUploadResponse(
        call_id=call_id,
        status=call_status,
        filename=call_filename,
        uploaded_at=call_uploaded_at
    )

@router.get("", response_model=List[CallListResponse])
def list_calls(db: Session = Depends(get_db)):
    """
    Returns list of all calls registered in DB, sorted by upload time descending.
    """
    return db.query(Call).order_by(Call.uploaded_at.desc()).all()

@router.get("/{call_id}", response_model=CallDetailResponse)
def get_call_detail(call_id: str, db: Session = Depends(get_db)):
    """
    Returns the complete structured metadata, transcript, summary, tags, and audit events.
    """
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call record not found.")
    return call

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
    
    media_type = call.mime_type or "audio/mpeg"
    return FileResponse(call.storage_path, media_type=media_type)

