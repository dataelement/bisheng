"""Platform-only private object storage; readers stream and always close responses."""

from __future__ import annotations

import asyncio
import json
from itertools import islice
from pathlib import Path

from minio.error import S3Error

from bisheng.core.storage.minio.minio_manager import get_minio_storage

BUCKET = "bisheng-apps"


class RuntimeObjectStore:
    async def _storage(self):
        storage = await get_minio_storage()
        await storage.create_bucket(BUCKET)
        try:
            policy = await asyncio.to_thread(storage.minio_client_sync.get_bucket_policy, BUCKET)
        except S3Error as exc:
            if exc.code != "NoSuchBucketPolicy":
                raise
        else:
            statements = json.loads(policy).get("Statement", [])
            for statement in statements:
                principal = statement.get("Principal")
                if statement.get("Effect") == "Allow" and (
                    principal == "*"
                    or (
                        isinstance(principal, dict)
                        and any(
                            value == "*" or (isinstance(value, list) and "*" in value) for value in principal.values()
                        )
                    )
                ):
                    raise ValueError("runtime_bucket_must_be_private")
        return storage

    async def put(self, key: str, path: Path, content_type="application/octet-stream"):
        storage = await self._storage()
        await storage.put_object(bucket_name=BUCKET, object_name=key, file=path, content_type=content_type)

    async def iter_content(self, key: str):
        storage = await self._storage()
        response = await asyncio.to_thread(storage.download_object_sync, BUCKET, key)
        try:
            while chunk := await asyncio.to_thread(response.read, 1024 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    async def stat(self, key):
        storage = await self._storage()
        try:
            result = await asyncio.to_thread(storage.minio_client_sync.stat_object, BUCKET, key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                return None
            raise
        return self._meta(result)

    @staticmethod
    def _meta(result):
        modified = getattr(result, "last_modified", None)
        return {
            "key": result.object_name,
            "size": result.size,
            "content_type": getattr(result, "content_type", None),
            "last_modified": modified.isoformat() if modified else "",
            "etag": getattr(result, "etag", ""),
        }

    async def list(self, prefix, *, start_after="", limit=1000):
        storage = await self._storage()

        def collect():
            return [
                self._meta(x)
                for x in islice(
                    storage.minio_client_sync.list_objects(
                        BUCKET, prefix=prefix, start_after=start_after, recursive=True
                    ),
                    limit,
                )
            ]

        return await asyncio.to_thread(collect)

    async def delete(self, key):
        storage = await self._storage()
        await storage.remove_object(bucket_name=BUCKET, object_name=key)
