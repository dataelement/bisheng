import base64
import hashlib
import hmac
import os
import uuid

import orjson


def orjson_dumps(v, *, default=None, sort_keys=False, indent_2=True):
    option = orjson.OPT_SORT_KEYS if sort_keys else None
    if indent_2:
        # orjson.dumps returns bytes, to match standard json.dumps we need to decode
        # option
        # To modify how data is serialized, specify option. Each option is an integer constant in orjson.
        # To specify multiple options, mask them together, e.g., option=orjson.OPT_STRICT_INTEGER | orjson.OPT_NAIVE_UTC
        if option is None:
            option = orjson.OPT_INDENT_2
        else:
            option |= orjson.OPT_INDENT_2
    if default is None:
        return orjson.dumps(v, option=option).decode()
    return orjson.dumps(v, default=default, option=option).decode()


def generate_short_high_entropy_string(length=32):
    """
    生成指定长度的高熵短字符串（默认32字符）

    参数:
        length: 目标长度
    """
    # 根据目标长度计算需要的原始字节数（Base64每字符对应6比特）
    byte_length = (length * 6 + 7) // 8  # 向上取整

    # 生成加密级随机密钥
    key = os.urandom(16)  # 128位密钥

    # 生成基础随机数据（UUID的128位足够作为源）
    base_random = uuid.uuid4().bytes

    # HMAC加密混合增强随机性
    h = hmac.new(key, base_random, hashlib.sha256)
    hmac_bytes = h.digest()

    # 截取所需长度的字节
    combined = hmac_bytes[:byte_length]

    # 转换为URL安全Base64并截断到目标长度（去除填充符）
    short_str = base64.urlsafe_b64encode(combined).decode().rstrip('=')[:length]

    return short_str
