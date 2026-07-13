from abc import ABC, abstractmethod
from typing import BinaryIO, Optional

class StorageBackend(ABC):
    @abstractmethod
    def save(self, fileobj, filename: str) -> str:
        """
        Save the file object and return the storage path identifier.
        """
        pass

    @abstractmethod
    def open(self, storage_path: str) -> BinaryIO:
        """
        Open the file from the storage path and return a binary file-like object.
        """
        pass

    @abstractmethod
    def get_url(self, storage_path: str, expires_in: int = 900) -> Optional[str]:
        """
        Return a presigned GET URL for the storage path, or None if local.
        """
        pass

    @abstractmethod
    def delete(self, storage_path: str) -> None:
        """
        Delete the file from the storage path.
        """
        pass

    @abstractmethod
    def exists(self, storage_path: str) -> bool:
        """
        Return True if the file exists at the given storage path.
        """
        pass

