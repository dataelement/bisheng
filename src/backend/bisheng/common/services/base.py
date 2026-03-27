from bisheng.core.cache import InMemoryCache
from bisheng.core.cache.redis_manager import get_redis_client_sync, get_redis_client
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync, get_minio_storage


class BaseService:
    LogoMemoryCache = InMemoryCache(max_size=200, expiration_time=3600 * 24)

    @classmethod
    def get_logo_share_link(cls, logo_path: str):

        redis_client = get_redis_client_sync()
        if not logo_path:
            return ''
        cache_key = f'logo_cache_new:{logo_path}'
        # Fetch from memory first
        share_url = cls.LogoMemoryCache.get(cache_key)
        if share_url:
            return share_url

        # Then fromredisFetch in cache
        share_url = redis_client.get(cache_key)
        if share_url:
            cls.LogoMemoryCache.set(cache_key, share_url)
            return share_url

        minio_client = get_minio_storage_sync()
        share_url = minio_client.get_share_link_sync(logo_path)

        # Ceacle5Day. Temporary link is valid for7 days
        redis_client.set(cache_key, share_url, 3600 * 120)
        cls.LogoMemoryCache.set(cache_key, share_url)
        return share_url

    @classmethod
    async def get_logo_share_link_async(cls, logo_path: str):

        redis_client = await get_redis_client()
        if not logo_path:
            return ''
        cache_key = f'logo_cache_new:{logo_path}'
        # Fetch from memory first
        share_url = cls.LogoMemoryCache.get(cache_key)
        if share_url:
            return share_url

        # Then fromredisFetch in cache
        share_url = await redis_client.aget(cache_key)
        if share_url:
            cls.LogoMemoryCache.set(cache_key, share_url)
            return share_url

        minio_client = await get_minio_storage()
        share_url = await minio_client.get_share_link(logo_path)

        # Ceacle5Day. Temporary link is valid for7 days
        await redis_client.aset(cache_key, share_url, 3600 * 120)
        cls.LogoMemoryCache.set(cache_key, share_url)
        return share_url
