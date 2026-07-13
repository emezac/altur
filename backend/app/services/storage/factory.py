from app.core.config import settings
from app.services.storage.base import StorageBackend
from app.services.storage.local import LocalDiskStorage

_storage_instance = None

def get_storage_backend() -> StorageBackend:
    global _storage_instance
    if _storage_instance is None:
        if settings.STORAGE_BACKEND == "s3":
            # Lazy import to avoid unnecessary dependency on boto3 in local development
            from app.services.storage.s3 import S3CompatibleStorage
            _storage_instance = S3CompatibleStorage()
        else:
            _storage_instance = LocalDiskStorage()
    return _storage_instance
