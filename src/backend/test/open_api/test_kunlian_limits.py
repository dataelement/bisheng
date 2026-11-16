"""Distributed request gate uses one atomic Redis script, never local counters."""

import importlib
from types import SimpleNamespace

import pytest


def module():
    name = "bisheng.open_api.application.kunlian_limits"
    assert importlib.util.find_spec(name) is not None, "Kunlian distributed limiter missing"
    return importlib.import_module(name)


class Redis:
    def __init__(self):
        self.calls = []
        self.counts = {}
        self.failure = False

    async def eval(self, script, numkeys, key, window_seconds):
        assert numkeys == 1
        assert "INCR" in script and "EXPIRE" in script
        self.calls.append((key, window_seconds))
        if self.failure:
            raise RuntimeError("unavailable with secret transport text")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


async def test_limit_is_shared_per_key_and_fails_closed():
    api = module()
    from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError

    redis = Redis()
    access = SimpleNamespace(credential=SimpleNamespace(credential_id=3), user=SimpleNamespace(tenant_id=7))
    await api.check_request(access, redis=redis, limit=2)
    access.user.tenant_id = 8  # aggregate across tenants, not per selected user
    await api.check_request(access, redis=redis, limit=2)
    from bisheng.common.errcode.open_api import OpenApiKunlianRateLimitedError

    with pytest.raises(OpenApiKunlianRateLimitedError) as failure:
        await api.check_request(access, redis=redis, limit=2)
    assert failure.value.code == 26074 and failure.value.http_status == 429
    assert len({key for key, _ in redis.calls}) == 1
    assert "3" in redis.calls[0][0]
    access.credential.credential_id = 4
    await api.check_request(access, redis=SimpleNamespace(async_connection=redis), limit=2)
    redis.failure = True
    with pytest.raises(KunlianAccessError, match="UNAVAILABLE"):
        await api.check_request(access, redis=redis)


@pytest.mark.parametrize("options", [{"limit": 0}, {"limit": True}, {"window_seconds": 0}, {"window_seconds": -1}])
async def test_invalid_server_policy_does_not_call_redis(options):
    api = module()
    from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError

    redis = Redis()
    with pytest.raises(KunlianAccessError, match="INVALID_INPUT"):
        await api.check_request(SimpleNamespace(credential=SimpleNamespace(credential_id=1)), redis=redis, **options)
    assert not redis.calls
