from datetime import datetime, timedelta
from typing import Optional, List

from bisheng.database.models.tts_cache import TTSCache, TTSCacheDao
from bisheng.api.errcode.base import NotFoundError
from loguru import logger


class TTSCacheService:
    @classmethod
    def get_cache(cls, md5: str, model_id: int, after_time: Optional[datetime] = None) -> Optional[TTSCache]:
        """根据 md5 + model_id 查询缓存，默认查 7 天内的，早于也会截断"""
        try:
            min_time = datetime.now() - timedelta(days=7)
            if after_time is None or after_time < min_time:
                after_time = min_time

            return TTSCacheDao.get_by_md5_model_after(md5=md5, model_id=model_id, after_time=after_time)
        except Exception as e:
            logger.warning(f"获取 TTS 缓存失败: {e}")
            return None

    @classmethod
    def create_cache(cls, text: str, md5: str, model_id: int, voice_url: str) -> TTSCache:
        """创建一条新的 TTS 缓存记录"""
        try:
            new_cache = TTSCache(
                msg=text,
                md5=md5,
                model_id=model_id,
                voice_url=voice_url
            )
            return TTSCacheDao.insert_one(new_cache)
        except Exception as e:
            logger.error(f"TTS 缓存创建失败: {e}")
            raise e

    @classmethod
    def batch_create_cache(cls, cache_list: List[TTSCache]) -> List[TTSCache]:
        """批量插入 TTS 缓存"""
        try:
            return TTSCacheDao.insert_batch(cache_list)
        except Exception as e:
            logger.error(f"TTS 批量缓存创建失败: {e}")
            raise

    @classmethod
    def get_all_by_model(cls, model_id: str) -> List[TTSCache]:
        """获取某个模型下的所有缓存记录"""
        return TTSCacheDao.get_by_model_id(model_id=model_id)
