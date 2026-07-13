import os
import logging
from app.core.config import settings
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a"}
ALLOWED_MIME_TYPES = {
    "audio/wav", "audio/x-wav",
    "audio/mpeg", "audio/mp3", "audio/x-mp3", "audio/mpeg3", "audio/x-mpeg3",
    "audio/mp4", "audio/x-m4a", "audio/m4a"
}

def validate_file_size(file_size_bytes: int) -> None:
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if file_size_bytes > max_bytes:
        logger.warning(f"File upload rejected: size {file_size_bytes} bytes exceeds limit of {max_bytes} bytes")
        raise AppError("FILE_TOO_LARGE", f"File size exceeds limit of {settings.MAX_UPLOAD_MB}MB", 413)

def validate_file_format(filename: str, file_header: bytes) -> None:
    # 1. Verify extension
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        logger.warning(f"File upload rejected: extension {ext} not in {ALLOWED_EXTENSIONS}")
        raise AppError("INVALID_FILE", "Invalid file extension. Only WAV, MP3 and M4A are supported.", 400)
    
    # 2. Verify Mime-type using magic if available
    detected_mime = None
    try:
        import magic
        # Read the first 2048 bytes of file header to determine mime-type
        detected_mime = magic.from_buffer(file_header, mime=True)
        logger.debug(f"Magic detected mime type: {detected_mime}")
    except Exception as e:
        logger.debug(f"python-magic failed to run or import: {e}. Using byte signature fallback.")
        
        # Fallback manual byte signatures
        if file_header.startswith(b"RIFF") and b"WAVE" in file_header[8:16]:
            detected_mime = "audio/wav"
        elif file_header.startswith(b"ID3") or file_header.startswith(b"\xff\xfb") or file_header.startswith(b"\xff\xf3") or file_header.startswith(b"\xff\xf2"):
            detected_mime = "audio/mpeg"
        elif b"ftyp" in file_header[4:12]:
            detected_mime = "audio/mp4"

    if not detected_mime or detected_mime.lower() not in ALLOWED_MIME_TYPES:
        logger.warning(f"File upload rejected: invalid mime-type {detected_mime or 'unknown'}")
        raise AppError("INVALID_FILE", "Invalid file format or signature. Only WAV, MP3 and M4A are supported.", 400)
