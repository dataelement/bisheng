from bisheng.cache.redis import redis_client


async def verify_captcha(captcha: str, captcha_key: str):
    # check captcha
    captcha_value = redis_client.get(captcha_key)
    if captcha_value:
        redis_client.delete(captcha_key)
        return captcha_value.lower() == captcha.lower()
    else:
        return False
