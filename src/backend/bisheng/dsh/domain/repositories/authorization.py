"""Redis persistence and atomic limits for short-lived native authorization."""

import hashlib
import json

from redis.exceptions import RedisError

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError


class DshAuthorizationRepository:
    def __init__(self, redis):
        self.redis = redis

    async def rate(self, action, peer):
        key = "{dsh}:local:rate:" + action + ":" + hashlib.sha256(peer.encode()).hexdigest()
        try:
            return await self.redis.eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
                1,
                key,
            )
        except RedisError as error:
            raise DshAuthorizationUnavailableError() from error

    async def save(self, auth_id, payload):
        try:
            saved = await self.redis.set("{dsh}:local:authorization:" + auth_id, json.dumps(payload), ex=300, nx=True)
        except RedisError as error:
            raise DshAuthorizationUnavailableError() from error
        if not saved:
            raise DshAuthorizationUnavailableError()

    async def read(self, auth_id):
        try:
            result = await self.redis.eval(
                "local p=redis.call('GET',KEYS[1]); if not p then return {} end; return {p,redis.call('TTL',KEYS[1])}",
                1,
                "{dsh}:local:authorization:" + auth_id,
            )
            if not result or int(result[1]) < 1:
                return None
            return json.loads(result[0]), min(int(result[1]), 300)
        except (RedisError, ValueError, TypeError, IndexError) as error:
            raise DshAuthorizationUnavailableError() from error
