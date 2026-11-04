"""T033 覆盖 AC-02, AC-13, AC-25。新签名协议不复用旧 F014。"""

from hashlib import sha256
from importlib import import_module
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.sso_sync import KunlianTrustRejectedError

BODY = b'{"connection_id":"fixture"}'
PATH = "/api/v1/internal/kunlian/login"
SIGNATURE = "2b7fb6d89fa70501ffa9627fc9df7d3ce852f33dc69c903abe9c111ef0505b9a"


@pytest.fixture
def trust():
    try:
        module = import_module("bisheng.sso_sync.domain.services.kunlian_login")
    except ModuleNotFoundError as exc:
        if exc.name != "bisheng.sso_sync.domain.services.kunlian_login":
            raise
        pytest.fail("T034 internal trust verifier is not implemented", pytrace=False)
    from pydantic import SecretStr

    nonces = set()

    async def reserve(key, ttl):
        assert ttl >= 121
        if key in nonces:
            return False
        nonces.add(key)
        return True

    storage = AsyncMock(side_effect=reserve)
    verifier = module.KunlianInternalTrust(
        key_id="fixture-key",
        secret=SecretStr("fixture-only-shared-signing-key"),
        reserve_nonce=storage,
        clock=lambda: 1800000000,
    )
    headers = {
        "X-Kunlian-Key-Id": "fixture-key",
        "X-Kunlian-Timestamp": "1800000000",
        "X-Kunlian-Nonce": "0123456789abcdefghijklmnop",
        "X-Kunlian-Signature": SIGNATURE,
    }
    return verifier, headers, storage


async def test_fixed_vector_acceptance_and_atomic_replay_rejection(trust):
    verifier, headers, storage = trust
    receipt = await verifier.verify_internal_request("POST", PATH, BODY, headers, source_allowed=True)
    assert receipt.body_digest == sha256(BODY).hexdigest()
    assert BODY.decode() not in repr(receipt)
    with pytest.raises(KunlianTrustRejectedError):
        await verifier.verify_internal_request("POST", PATH, BODY, headers, source_allowed=True)
    assert storage.await_count == 2


@pytest.mark.parametrize(
    "change", ["body", "method", "path", "key", "timestamp", "nonce", "signature", "source", "unicode"]
)
async def test_signed_context_is_bound_before_nonce_consumption(trust, change):
    verifier, headers, storage = trust
    body, method, path, allowed = BODY, "POST", PATH, True
    if change == "body":
        body = b'{ "connection_id": "fixture" }'
    elif change == "method":
        method = "GET"
    elif change == "path":
        path += "?other=1"
    elif change == "source":
        allowed = False
    elif change == "unicode":
        headers["X-Kunlian-Signature"] = "昆" * 64
    else:
        header = {"key": "Key-Id", "timestamp": "Timestamp", "nonce": "Nonce", "signature": "Signature"}[change]
        headers["X-Kunlian-" + header] = {
            "key": "other",
            "timestamp": "1799999939",
            "nonce": "bad\nnonce",
            "signature": "0" * 64,
        }[change]
    with pytest.raises(KunlianTrustRejectedError):
        await verifier.verify_internal_request(method, path, body, headers, source_allowed=allowed)
    storage.assert_not_awaited()


async def test_nonce_store_failure_rejects_without_exposing_payload(trust):
    verifier, headers, storage = trust
    from redis.exceptions import ConnectionError

    storage.side_effect = ConnectionError("fixture-private-payload")
    with pytest.raises(KunlianTrustRejectedError) as caught:
        await verifier.verify_internal_request("POST", PATH, BODY, headers, source_allowed=True)
    assert "fixture-private-payload" not in str(caught.value)


async def test_real_redis_adapter_uses_one_atomic_nx_expiry(monkeypatch):
    from bisheng.sso_sync.domain.services import kunlian_login as module

    if not hasattr(module, "reserve_internal_nonce"):
        pytest.fail("T034 Redis nonce adapter is not implemented", pytrace=False)
    from bisheng.core.cache import redis_manager

    connection = AsyncMock()
    connection.set.return_value = True
    from types import SimpleNamespace

    monkeypatch.setattr(
        redis_manager, "get_redis_client", AsyncMock(return_value=SimpleNamespace(async_connection=connection))
    )
    assert await module.reserve_internal_nonce("kunlian:fixture", 121) is True
    connection.set.assert_awaited_once_with("kunlian:fixture", "1", nx=True, ex=121)
