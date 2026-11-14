"""DetailStore over MinIO (design decision 3).

Detail bodies are immutable objects at ``memory/{tenant_id}/{user_id}/{item_id}.md``
in the platform bucket. The bucket's anonymous-read policy only covers
``knowledge/images/*`` and ``tmp/images/*``, so ``memory/`` objects are private.
"""

from __future__ import annotations

from bisheng.memory.domain.ports import MemoryContext, detail_object_key


class MinioDetailStore:
    def __init__(self, storage=None):
        self._storage = storage

    async def _get_storage(self):
        if self._storage is None:
            from bisheng.core.storage.minio.minio_manager import get_minio_storage

            self._storage = await get_minio_storage()
        return self._storage

    async def put(self, ctx: MemoryContext, item_id: str, text: str) -> str:
        key = detail_object_key(ctx.tenant_id, ctx.user_id, item_id)
        storage = await self._get_storage()
        await storage.put_object(object_name=key, file=text.encode("utf-8"), content_type="text/markdown")
        return key

    async def get(self, key: str) -> str:
        storage = await self._get_storage()
        data = await storage.get_object(object_name=key)
        if data is None:
            raise FileNotFoundError(key)
        return data.decode("utf-8")

    async def delete(self, key: str) -> None:
        storage = await self._get_storage()
        await storage.remove_object(object_name=key)

    async def list_keys(self, ctx: MemoryContext) -> list[str]:
        storage = await self._get_storage()
        prefix = f"memory/{ctx.tenant_id}/{ctx.user_id}/"
        objects = storage.minio_client.list_objects(storage.bucket, prefix=prefix, recursive=True)
        return [obj.object_name async for obj in objects]

    async def delete_user(self, ctx: MemoryContext) -> None:
        for key in await self.list_keys(ctx):
            await self.delete(key)
