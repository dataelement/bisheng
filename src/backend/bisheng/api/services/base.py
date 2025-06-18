from bisheng.cache import InMemoryCache
from bisheng.cache.redis import redis_client
from bisheng.settings import settings
from bisheng.utils.minio_client import MinioClient


class BaseService:
    LogoMemoryCache = InMemoryCache(max_size=200, expiration_time=3600 * 24)

    @classmethod
    def get_logo_share_link(cls, logo_path: str):
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

        minio_client = MinioClient()
        share_url = minio_client.get_share_link(logo_path)
        # 去除前缀通过nginx访问，防止访问不到文件
        share_url = minio_client.clear_minio_share_host(share_url)

        # 缓存5天， 临时链接有效期为7天
        redis_client.set(cache_key, share_url, 3600 * 120)
        cls.LogoMemoryCache.set(cache_key, share_url)
        return share_url
