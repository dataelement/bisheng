"""One-time OAuth state for the self-hosted WeCom SSO (F120).

State lives in Redis, not in process memory: the API runs several replicas
(constitution C8), and consuming the state must be atomic so a replayed
callback can never log a second session in.

See ``features/v3.0.1/120-wecom-sso/design.md`` decision 3.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass

from loguru import logger
from redis.exceptions import RedisError

from bisheng.common.errcode.sso_sync import WeComSsoStateInvalidError
from bisheng.core.cache.redis_manager import get_redis_client

STATE_KEY_FMT = "wecom_sso:state:{state}"

#: Redis < 6.2 has no GETDEL; this Lua form is atomic on every supported
#: version and returns nil for an unknown/expired state.
_CONSUME_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if value then
    redis.call('DEL', KEYS[1])
end
return value
"""


@dataclass(frozen=True)
class WeComLoginState:
    """What the authorize step wants the callback step to remember."""

    mode: str
    return_to: str


class WeComLoginStateStore:
    """Issue and consume the one-time ``state`` of a WeCom authorization."""

    @staticmethod
    def new_state() -> str:
        return secrets.token_urlsafe(32)

    @classmethod
    async def put(cls, state: str, *, mode: str, return_to: str, ttl: int) -> None:
        payload = json.dumps({"mode": mode, "return_to": return_to})
        client = await get_redis_client()
        await client.async_connection.set(
            STATE_KEY_FMT.format(state=state),
            payload,
            ex=ttl,
        )

    @classmethod
    async def consume(cls, state: str) -> WeComLoginState:
        """Atomically take and delete the state.

        Any failure (missing, expired, already used, unreadable payload, Redis
        outage) surfaces as ``WeComSsoStateInvalidError``: the login path is
        fail-closed on purpose — an unverifiable state must never be trusted.
        """
        if not state:
            raise WeComSsoStateInvalidError()
        try:
            client = await get_redis_client()
            raw = await client.async_connection.eval(
                _CONSUME_SCRIPT,
                1,
                STATE_KEY_FMT.format(state=state),
            )
        except RedisError as exc:
            # Fail closed: without the state store we cannot tell a genuine
            # callback from a replayed one, so refuse the login.
            logger.warning("wecom sso: state store unavailable: {!r}", exc)
            raise WeComSsoStateInvalidError() from exc
        if raw is None:
            raise WeComSsoStateInvalidError()
        try:
            data = json.loads(raw)
            return WeComLoginState(mode=str(data["mode"]), return_to=str(data["return_to"]))
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("wecom sso: unreadable state payload: {!r}", raw)
            raise WeComSsoStateInvalidError() from exc
