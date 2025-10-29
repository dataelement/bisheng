from bisheng.core.cache import InMemoryCache
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync


class BaseService:
    LogoMemoryCache = InMemoryCache(max_size=200, expiration_time=3600 * 24)

    @classmethod
    def get_logo_share_link(cls, logo_path: str):

        redis_client = get_redis_client_sync()
        if not logo_path:
            return ''
        cache_key = f'logo_cache:{logo_path}'
        # 先从内存中获取
        share_url = cls.LogoMemoryCache.get(cache_key)
        if share_url:
            return share_url

        # 再从redis缓存中获取
        share_url = redis_client.get(cache_key)
        if share_url:
            cls.LogoMemoryCache.set(cache_key, share_url)
            return share_url

        minio_client = get_minio_storage_sync()
        share_url = minio_client.get_share_link(logo_path)
        # 去除前缀通过nginx访问，防止访问不到文件
        share_url = minio_client.clear_minio_share_host(share_url)

        # 缓存5天， 临时链接有效期为7天
        redis_client.set(cache_key, share_url, 3600 * 120)
        cls.LogoMemoryCache.set(cache_key, share_url)
        return share_url
