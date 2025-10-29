from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union, BinaryIO


class BaseStorage(ABC):
    """Base class for storage backends."""

    @abstractmethod
    async def create_bucket(self, bucket_name: str) -> None:
        """Create a new storage bucket."""
        pass

    @abstractmethod
    def create_bucket_sync(self, bucket_name: str) -> None:
        """Create a new storage bucket (synchronous)."""
        pass

    @abstractmethod
    async def check_bucket_exists(self, bucket_name: str) -> bool:
        """Check if a storage bucket exists."""
        pass

    @abstractmethod
    def check_bucket_exists_sync(self, bucket_name: str) -> bool:
        """Check if a storage bucket exists (synchronous)."""
        pass

    @abstractmethod
    async def get_all_buckets(self) -> list:
        """Get a list of all storage buckets."""
        pass

    @abstractmethod
    def get_all_buckets_sync(self) -> list:
        """Get a list of all storage buckets (synchronous)."""
        pass

    @abstractmethod
    async def remove_bucket(self, bucket_name: str) -> None:
        """Remove a storage bucket."""
        pass

    @abstractmethod
    def remove_bucket_sync(self, bucket_name: str) -> None:
        """Remove a storage bucket (synchronous)."""
        pass

    @abstractmethod
    async def put_object(self, bucket_name: str, object_name: str, file: Union[bytes, BinaryIO, Path, str],
                         content_type: str = None, **kwargs) -> None:
        """Upload an object to a storage bucket."""
        pass

    @abstractmethod
    def put_object_sync(self, bucket_name: str, object_name: str, file: Union[bytes, BinaryIO, Path, str],
                        content_type: str = None, **kwargs) -> None:
        """Upload an object to a storage bucket (synchronous)."""
        pass

    @abstractmethod
    async def get_object(self, bucket_name: str, object_name: str) -> bytes:
        """Download an object from a storage bucket."""
        pass

    @abstractmethod
    def get_object_sync(self, bucket_name: str, object_name: str) -> bytes:
        """Download an object from a storage bucket (synchronous)."""
        pass

    @abstractmethod
    async def object_exists(self, bucket_name: str, object_name: str) -> bool:
        """Check if an object exists in a storage bucket."""
        pass

    def object_exists_sync(self, bucket_name: str, object_name: str) -> bool:
        """Check if an object exists in a storage bucket (synchronous)."""
        pass

    @abstractmethod
    async def copy_object(self, source_bucket: str, source_object: str,
                          dest_bucket: str, dest_object: str) -> None:
        """Copy an object from one storage bucket to another."""
        pass

    @abstractmethod
    def copy_object_sync(self, source_bucket: str, source_object: str,
                         dest_bucket: str, dest_object: str) -> None:
        """Copy an object from one storage bucket to another (synchronous)."""
        pass

    @abstractmethod
    async def remove_object(self, bucket_name: str, object_name: str) -> None:
        """Remove an object from a storage bucket."""
        pass

    @abstractmethod
    def remove_object_sync(self, bucket_name: str, object_name: str) -> None:
        """Remove an object from a storage bucket (synchronous)."""
        pass
