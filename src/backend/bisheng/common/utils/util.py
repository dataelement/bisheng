import base64
import contextvars
import functools
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
    Generate a short string of high entropy of the specified length (default32characters. 

    Parameters:
        length: Target Length
    """
    # Calculate the required number of raw bytes based on the target length (Base64Corresponds to each character6bit
    byte_length = (length * 6 + 7) // 8  # Round Up

    # Generate Encryption-Level Random Keys
    key = os.urandom(16)  # 128Bit Key

    # Generate basic random data (UUIDright of privacy128bits are sufficient as a source)
    base_random = uuid.uuid4().bytes

    # HMACCrypto Hybrid Enhanced Randomness
    h = hmac.new(key, base_random, hashlib.sha256)
    hmac_bytes = h.digest()

    # Truncate bytes of desired length
    combined = hmac_bytes[:byte_length]

    # Convert ToURLSAFETYBase64and truncate to target length (without padding)
    short_str = base64.urlsafe_b64encode(combined).decode().rstrip('=')[:length]

    return short_str


# --- Define decorator ---
def transfer_trace_id(func):
    """
    Decorator: Automatically convert the current context (including trace_id) into the execution environment of the decorated function.
    Available for Thread OR Executor。
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 1. The code here is still executing in the parent thread, capturing the context
        ctx = contextvars.copy_context()
        # 2. Use ctx.run Run the original function in the captured context
        return ctx.run(func, *args, **kwargs)

    return wrapper
