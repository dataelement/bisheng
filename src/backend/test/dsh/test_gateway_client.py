"""F062 service authentication contracts. 覆盖 AC: AC-02, AC-13, AC-25, AC-31, AC-32."""

import hashlib
import hmac

import httpx
import pytest

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError, DshInvalidAccessTokenError
from bisheng.dsh.infrastructure.gateway_client import GatewayClient
from bisheng.dsh.infrastructure.service_auth import ServiceAuth, ServiceKey


class Nonces:
    def __init__(self):
        self.seen = set()

    async def claim(self, key, ttl):
        assert ttl == 120
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


def auth(now=1000):
    return ServiceAuth(ServiceKey("instance-test", "python-test", b"a" * 32), Nonces(), lambda: now)


@pytest.mark.parametrize(
    "installation,key_id", [("a.b", "valid"), ("a" * 65, "valid"), ("valid", "key:one"), ("valid", "a" * 129)]
)
def test_python_service_key_uses_gateway_registration_alphabet(installation, key_id):
    with pytest.raises(ValueError):
        ServiceKey(installation, key_id, b"a" * 32)


async def test_exact_body_signature_and_replay():
    service = auth()
    body = b'{"token":"test-only"}'
    headers = service.sign("POST", "/api/internal/dsh/introspect", body)
    canonical = "\n".join(
        [
            "POST",
            "/api/internal/dsh/introspect",
            hashlib.sha256(body).hexdigest(),
            "instance-test",
            "python-test",
            "1000",
            headers["X-DSH-Nonce"],
        ]
    )
    assert headers["X-DSH-Signature"] == hmac.new(b"a" * 32, canonical.encode(), hashlib.sha256).hexdigest()
    assert await service.verify("POST", "/api/internal/dsh/introspect", body, headers) == "instance-test"
    with pytest.raises(DshInvalidAccessTokenError):
        await service.verify("POST", "/api/internal/dsh/introspect", body, headers)


async def test_bad_signatures_do_not_consume_nonce_and_clock_is_bounded():
    service = auth()
    path = "/api/internal/dsh/introspect"
    headers = service.sign("POST", path, b"{}")
    for mutated in (
        {**headers, "X-DSH-Installation-Id": "other"},
        {**headers, "X-DSH-Key-Id": "other"},
        {**headers, "X-DSH-Timestamp": "1"},
    ):
        with pytest.raises(DshInvalidAccessTokenError):
            await service.verify("POST", path, b"{}", mutated)
    with pytest.raises(DshInvalidAccessTokenError):
        await service.verify("POST", path, b'{"different":true}', headers)
    assert await service.verify("POST", path, b"{}", headers) == "instance-test"
    with pytest.raises(DshInvalidAccessTokenError):
        await auth(1061).verify("POST", path, b"{}", headers)
    for path in ("/api/../admin", "/api//admin", "/api/%2fadmin", "/api/internal?nonce=x"):
        with pytest.raises(ValueError):
            service.sign("POST", path, b"{}")


@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_http_uses_fixed_origin_and_does_not_follow_redirects(scheme):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://evil.example/"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = GatewayClient(f"{scheme}://gateway.example", auth(), transport)
        with pytest.raises(DshAuthorizationUnavailableError):
            await client.introspect("test-token")
    assert len(seen) == 1 and seen[0].url.host == "gateway.example"
    assert seen[0].headers["x-dsh-key-id"] == "python-test"
    with pytest.raises(ValueError):
        GatewayClient("ftp://gateway.example", auth(), None)


@pytest.mark.parametrize(
    "response",
    [
        {"status_code": 500, "data": {"active": True}},
        {"active": "true"},
        {},
        {"active": True, "seat_id": "1", "session_id": "s", "grant_version": True},
    ],
)
async def test_legacy_200_error_or_malformed_active_is_not_accepted(response):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    ) as transport:
        with pytest.raises(DshAuthorizationUnavailableError):
            await GatewayClient("https://gateway.example", auth(), transport).introspect("test-token")


async def test_valid_introspection_and_timeout():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "active": True,
                    "seat_id": "42",
                    "session_id": "session-1",
                    "grant_version": 2,
                    "reason": None,
                },
            )
        )
    ) as transport:
        result = await GatewayClient("https://gateway.example", auth(), transport).introspect("test-token")
        assert result.active and result.grant_version == 2

    def timeout(request):
        raise httpx.ReadTimeout("test", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as transport:
        with pytest.raises(DshAuthorizationUnavailableError):
            await GatewayClient("https://gateway.example", auth(), transport).introspect("test-token")


async def test_nonce_claim_is_shared_and_atomic_on_real_redis(dsh_redis_url):
    import asyncio

    from redis.asyncio import Redis

    from bisheng.dsh.infrastructure.service_auth import RedisNonceStore

    redis = Redis.from_url(dsh_redis_url)
    services = [
        ServiceAuth(ServiceKey("instance-test", "python-test", b"a" * 32), RedisNonceStore(redis)) for _ in range(8)
    ]
    headers = services[0].sign("POST", "/api/internal/dsh/introspect", b"{}")
    results = await asyncio.gather(
        *(service.verify("POST", "/api/internal/dsh/introspect", b"{}", headers) for service in services),
        return_exceptions=True,
    )
    assert results.count("instance-test") == 1
    assert sum(isinstance(result, DshInvalidAccessTokenError) for result in results) == 7
    await redis.aclose()


@pytest.mark.parametrize(
    "operation,status,code,kind,rejected",
    [
        ("revoke", 409, "authorization_conflict", "conflict_error", True),
        ("reassign", 409, "authorization_conflict", "conflict_error", True),
        ("operation", 409, "authorization_conflict", "conflict_error", False),
        ("revoke", 503, "authorization_conflict", "conflict_error", False),
        ("revoke", 409, "authorization_unavailable", "conflict_error", False),
        ("revoke", 409, "authorization_conflict", "server_error", False),
    ],
)
async def test_only_explicit_command_intent_conflict_is_definitive(operation, status, code, kind, rejected):
    from bisheng.dsh.infrastructure.gateway_client import GatewayCommandRejected

    response = {"error": {"code": code, "type": kind, "message": "test"}, "request_id": "trace"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=response))
    ) as transport:
        client = GatewayClient("https://gateway.example", auth(), transport)
        with pytest.raises(GatewayCommandRejected if rejected else DshAuthorizationUnavailableError):
            await client.request(operation, {})
