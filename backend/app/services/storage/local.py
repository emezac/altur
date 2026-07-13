import os
import uuid
import shutil
from typing import BinaryIO, Optional
from app.core.config import settings
from app.services.storage.base import StorageBackend

class LocalDiskStorage(StorageBackend):
    def __init__(self, base_path: Optional[str] = None):
        self.base_path = base_path or settings.LOCAL_STORAGE_PATH
        # Ensure the directory exists
        os.makedirs(self.base_path, exist_ok=True)

    def _sanitize_filename(self, filename: str) -> str:
        # Keep alphanumeric, dots, underscores, dashes
        return "".join(c for c in filename if c.isalnum() or c in "._-").strip()

    def save(self, fileobj, filename: str) -> str:
        sanitized = self._sanitize_filename(filename)
        unique_name = f"{uuid.uuid4()}_{sanitized}"
        dest_path = os.path.join(self.base_path, unique_name)
        
        # Reset file pointer if seekable
        if hasattr(fileobj, "file") and hasattr(fileobj.file, "seek"):
            try:
                fileobj.file.seek(0)
            except Exception:
                pass
        elif hasattr(fileobj, "seek"):
            try:
                fileobj.seek(0)
            except Exception:
                pass
                
        with open(dest_path, "wb") as buffer:
            if hasattr(fileobj, "file"):
                # It is a FastAPI UploadFile
                shutil.copyfileobj(fileobj.file, buffer)
            elif hasattr(fileobj, "read"):
                # It is a standard file-like object
                shutil.copyfileobj(fileobj, buffer)
            else:
                # It is bytes or string
                buffer.write(fileobj)
                
        return os.path.normpath(dest_path)

    def open(self, storage_path: str) -> BinaryIO:
        if not os.path.exists(storage_path):
            raise FileNotFoundError(f"File not found at: {storage_path}")
        return open(storage_path, "rb")

    def get_url(self, storage_path: str, expires_in: int = 900) -> Optional[str]:
        # Return None to indicate file should be served directly through the API
        return None

    def delete(self, storage_path: str) -> None:
        if os.path.exists(storage_path):
            os.remove(storage_path)
