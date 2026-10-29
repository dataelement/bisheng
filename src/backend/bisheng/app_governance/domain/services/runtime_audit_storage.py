"""Private artifact bytes. No public URL or API-host filesystem dependency."""

from bisheng.core.storage.minio.minio_manager import get_minio_storage

BUCKET = "bisheng-apps"


class RuntimeAuditStorage:
    async def put(self, key, value):
        storage = await get_minio_storage()
        await storage.create_bucket(BUCKET)
        await storage.put_object(bucket_name=BUCKET, object_name=key, file=value)

    async def get(self, key):
        storage = await get_minio_storage()
        return await storage.get_object(bucket_name=BUCKET, object_name=key)

    async def remove(self, key):
        storage = await get_minio_storage()
        await storage.remove_object(bucket_name=BUCKET, object_name=key)

    async def remove_prefix(self, prefix):
        import asyncio

        storage = await get_minio_storage()
        # Enumerate one page at a time; only the server-generated job prefix is accepted.
        client = storage.minio_client_sync
        iterator = client.list_objects(BUCKET, prefix=prefix, recursive=True)

        def next_page():
            from itertools import islice

            return list(islice(iterator, 100))

        while page := await asyncio.to_thread(next_page):
            for obj in page:
                await storage.remove_object(bucket_name=BUCKET, object_name=obj.object_name)
