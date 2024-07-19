from bisheng.cache.redis import redis_client
from bisheng.utils.minio_client import MinioClient


class BaseService:
    @classmethod
    def get_logo_share_link(cls, logo_path: str):
        if not logo_path:
            return ''
        cache_key = f'logo_cache:{logo_path}'
        # 先尝试从缓存中获取
        share_url = redis_client.get(cache_key)
        if share_url:
            return share_url

        minio_client = MinioClient()
        share_url = minio_client.get_share_link(logo_path)
        # 缓存一天
        redis_client.set(cache_key, share_url, 3600 * 24)
        return share_url
