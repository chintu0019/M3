"""
M3 File Storage — MinIO (S3-compatible) wrapper.

All operations are async via asyncio.to_thread since the minio client is sync.
"""

import asyncio
import io
from datetime import timedelta

from minio import Minio
from minio.commonconfig import CopySource

from m3.config import StorageSettings


class FileStore:
    def __init__(self, settings: StorageSettings):
        self.client = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.secure,
        )
        self.bucket = settings.bucket

    async def ensure_bucket(self) -> None:
        """Create the storage bucket if it doesn't exist."""
        exists = await asyncio.to_thread(self.client.bucket_exists, self.bucket)
        if not exists:
            await asyncio.to_thread(self.client.make_bucket, self.bucket)

    async def upload(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Upload bytes to the given path. Returns the path."""
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            path,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )
        return path

    async def download(self, path: str) -> bytes:
        """Download file contents as bytes."""
        response = await asyncio.to_thread(self.client.get_object, self.bucket, path)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def get_url(self, path: str, expires: timedelta = timedelta(hours=1)) -> str:
        """Get a presigned URL for the file."""
        return await asyncio.to_thread(
            self.client.presigned_get_object, self.bucket, path, expires=expires
        )

    async def rename(self, old_path: str, new_path: str) -> None:
        """Rename a file by copying to the new key then deleting the old one."""
        await asyncio.to_thread(
            self.client.copy_object,
            self.bucket,
            new_path,
            CopySource(self.bucket, old_path),
        )
        await asyncio.to_thread(self.client.remove_object, self.bucket, old_path)

    async def delete(self, path: str) -> None:
        """Delete a file."""
        await asyncio.to_thread(self.client.remove_object, self.bucket, path)
