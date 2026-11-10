"""Digest-addressed, app-bound Desktop tickets and sessions shared by all nodes."""

import hashlib
import json
import re
import secrets

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError, DshInvalidGrantError

_CONSUME = """
local raw = redis.call('GET', KEYS[1])
if not raw then return false end
if cjson.decode(raw).slug ~= ARGV[1] then return false end
redis.call('DEL', KEYS[1])
return raw
"""


class DesktopAppSessions:
    def __init__(self, redis):
        self.redis = redis

    @staticmethod
    def key(kind, token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise DshInvalidGrantError()
        return f"{{dsh-app}}:{kind}:{hashlib.sha256(token.encode()).hexdigest()}"

    async def issue(self, principal, *, app_id, slug):
        ticket = secrets.token_urlsafe(32)
        record = {"principal": principal.model_dump(), "app_id": app_id, "slug": slug}
        try:
            created = await self.redis.set(self.key("ticket", ticket), json.dumps(record), ex=60, nx=True)
            if not created:
                raise DshAuthorizationUnavailableError()
        except DshAuthorizationUnavailableError:
            raise
        except Exception as error:
            raise DshAuthorizationUnavailableError() from error
        return ticket

    async def redeem(self, ticket, slug):
        key = self.key("ticket", ticket)
        try:
            raw = await self.redis.eval(_CONSUME, 1, key, slug)
            if not raw:
                raise DshInvalidGrantError()
            record = json.loads(raw)
            token = secrets.token_urlsafe(32)
            created = await self.redis.set(self.key("session", token), json.dumps(record), ex=3600, nx=True)
            if not created:
                raise DshAuthorizationUnavailableError()
            return "bs-view-" + token
        except (DshInvalidGrantError, DshAuthorizationUnavailableError):
            raise
        except Exception as error:
            raise DshAuthorizationUnavailableError() from error

    async def resolve(self, token, slug):
        key = self.key("session", token.removeprefix("bs-view-"))
        try:
            raw = await self.redis.get(key)
            if not raw:
                raise DshInvalidGrantError()
            record = json.loads(raw)
            if record["slug"] != slug:
                raise DshInvalidGrantError()
            return record
        except DshInvalidGrantError:
            raise
        except Exception as error:
            raise DshAuthorizationUnavailableError() from error


async def desktop_app_sessions():
    from bisheng.core.cache.redis_manager import get_redis_client

    return DesktopAppSessions((await get_redis_client()).async_connection)
