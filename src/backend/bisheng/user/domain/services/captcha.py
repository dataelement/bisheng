from bisheng.core.cache.redis_manager import get_redis_client


async def verify_captcha(captcha: str, captcha_key: str):
    # check captcha
    redis_client = await get_redis_client()
    captcha_value = await redis_client.aget(captcha_key)
    if captcha_value:
        await redis_client.adelete(captcha_key)
        return captcha_value.lower() == captcha.lower()
    else:
        return False
