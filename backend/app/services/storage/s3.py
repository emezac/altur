import uuid
import logging
from typing import BinaryIO, Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class S3CompatibleStorage(StorageBackend):
    """
    S3-compatible object storage (AWS S3 or any S3 API such as MinIO / GCS).

    The `storage_path` persisted on the Call is the object **key** (not a
    filesystem path). Audio is served to the browser via a short-lived
    presigned GET URL (`get_url`), so the API never streams large files itself —
    this is what makes the stateless, ephemeral-filesystem Heroku deploy work.

    The concrete endpoint is chosen by config: leave `S3_ENDPOINT_URL` empty for
    real AWS, or point it at `http://minio:9000` for the docker-compose MinIO.
    """

    def __init__(self):
        self.bucket = settings.S3_BUCKET_NAME
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            # s3v4 is required for presigned URLs against MinIO and most regions.
            config=Config(signature_version="s3v4"),
        )

    def _sanitize_filename(self, filename: str) -> str:
        return "".join(c for c in filename if c.isalnum() or c in "._-").strip()

    def _stream(self, fileobj):
        """Return the underlying binary stream, rewound to the start."""
        stream = fileobj.file if hasattr(fileobj, "file") else fileobj
        try:
            stream.seek(0)
        except Exception:
            pass
        return stream

    def save(self, fileobj, filename: str) -> str:
        key = f"{uuid.uuid4()}_{self._sanitize_filename(filename)}"
        self._client.upload_fileobj(self._stream(fileobj), self.bucket, key)
        logger.info(f"Uploaded object to s3://{self.bucket}/{key}")
        return key

    def open(self, storage_path: str) -> BinaryIO:
        try:
            obj = self._client.get_object(Bucket=self.bucket, Key=storage_path)
            return obj["Body"]
        except ClientError as e:
            raise FileNotFoundError(f"Object not found: {storage_path}") from e

    def get_url(self, storage_path: str, expires_in: int = 900) -> Optional[str]:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": storage_path},
            ExpiresIn=expires_in,
        )

    def delete(self, storage_path: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=storage_path)

    def exists(self, storage_path: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=storage_path)
            return True
        except ClientError:
            return False
