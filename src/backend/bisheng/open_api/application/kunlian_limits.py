"""One distributed fixed window per credential, independent of selected tenant.

The first accepted request opens a window; later requests never extend its TTL.
This is a request-rate gate, not an execution-concurrency reservation.
"""

import asyncio

from loguru import logger

from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError

_REQUEST_WINDOW = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


async def check_request(access, *, redis=None, limit=120, window_seconds=60):
    """Consume one request; trusted server configuration only, never query input.

    Redis failures deny admission with UNAVAILABLE. No process-local counters or
    non-atomic INCR/EXPIRE fallback are permitted, including in cluster mode.
    """
    credential_id = access.credential.credential_id
    if (
        type(credential_id) is not int
        or credential_id <= 0
        or type(limit) is not int
        or not 1 <= limit <= 1_000_000
        or type(window_seconds) is not int
        or not 1 <= window_seconds <= 86400
    ):
        raise KunlianAccessError("INVALID_INPUT")
    # Only a persisted numeric credential reference enters the Redis key. It
    # aggregates all selected tenants/users and never contains bearer material.
    key = f"kunlian:request-rate:{{{credential_id}}}"
    try:
        async with asyncio.timeout(3):
            client = redis if redis is not None else await get_redis_client()
            connection = getattr(client, "async_connection", client)
            count = await connection.eval(_REQUEST_WINDOW, 1, key, window_seconds)
        if type(count) is not int or count <= 0:
            raise ValueError("invalid rate-window response")
    except Exception:
        logger.error("Kunlian request rate gate unavailable; admission denied")
        raise KunlianAccessError("UNAVAILABLE") from None
    if count > limit:
        from bisheng.common.errcode.open_api import OpenApiKunlianRateLimitedError

        raise OpenApiKunlianRateLimitedError()
