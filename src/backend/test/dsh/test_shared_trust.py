"""Shared deployment secret, separate protocols and fixed HS256 verification."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError
from bisheng.dsh.domain.services.access import DshAccessService
from bisheng.dsh.infrastructure.shared_trust import (
    ACCESS_KEY_ID,
    INBOUND_KEY_ID,
    OUTBOUND_KEY_ID,
    GatewayKeys,
    access_issuer,
    derive_key,
)


def test_single_shared_secret_is_separated_by_purpose_and_installation():
    secret = "dsh-integration-fixture-shared-secret"
    keys = {derive_key(secret, "fixture", purpose) for purpose in (ACCESS_KEY_ID, INBOUND_KEY_ID, OUTBOUND_KEY_ID)}
    assert len(keys) == 3
    assert all(len(key) == 32 for key in keys)
    assert derive_key(secret, "other", ACCESS_KEY_ID) not in keys
    with pytest.raises(ValueError):
        derive_key("", "fixture", ACCESS_KEY_ID)


async def test_shared_hmac_verification_still_requires_online_identity_and_seat():
    key = derive_key("dsh-integration-fixture-shared-secret", "fixture", ACCESS_KEY_ID)
    identities = SimpleNamespace(
        check=AsyncMock(
            return_value=SimpleNamespace(active=True, installation_id="fixture", tenant_id="2", user_id="12")
        )
    )
    gateway = SimpleNamespace(
        introspect=AsyncMock(
            return_value=SimpleNamespace(active=True, seat_id="seat", session_id="session", grant_version=1)
        )
    )
    service = DshAccessService("fixture", access_issuer("fixture"), GatewayKeys(key), identities, gateway)
    now = int(time.time())
    claims = {
        "iss": access_issuer("fixture"),
        "aud": "bisheng-dsh-model",
        "sub": "12",
        "installation_id": "fixture",
        "tenant_id": "2",
        "seat_id": "seat",
        "session_id": "session",
        "grant_version": 1,
        "iat": now,
        "exp": now + 300,
        "jti": "id",
    }
    token = jwt.encode(claims, key, algorithm="HS256", headers={"kid": ACCESS_KEY_ID, "typ": "bisheng-dsh-access+jwt"})
    assert (await service.authenticate("Bearer " + token)).user_id == "12"
    gateway.introspect.assert_awaited_once_with(token)
    for wrong_key in (
        b"other-secret-for-test-only-32bytes",
        derive_key("dsh-integration-fixture-shared-secret", "fixture", OUTBOUND_KEY_ID),
    ):
        bad = jwt.encode(
            claims, wrong_key, algorithm="HS256", headers={"kid": ACCESS_KEY_ID, "typ": "bisheng-dsh-access+jwt"}
        )
        with pytest.raises(DshInvalidAccessTokenError):
            await service.authenticate("Bearer " + bad)


async def test_model_catalog_does_not_require_a_deployment_allowlist(monkeypatch):
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
    from bisheng.dsh.admin_runtime import read_available_models
    from bisheng.llm.domain.services.llm import LLMService

    available = SimpleNamespace(
        id=17, online=True, model_type="llm", tenant_id=2, name="model 1", model_name="qwen-max"
    )
    embedding = SimpleNamespace(id=18, online=True, model_type="embedding")
    monkeypatch.setattr(
        LLMService, "get_all_llm", AsyncMock(return_value=[SimpleNamespace(models=[available, embedding])])
    )
    token = set_current_tenant_id(2)
    try:
        ids = await LLMService.get_dsh_model_ids()
        assert ids == [17]
        rows = await read_available_models(
            ids, AsyncMock(return_value=(available, SimpleNamespace(name="Bailian", type="openai")))
        )
        assert rows == [{"id": 17, "name": "Bailian / qwen-max", "is_root_shared": False}]
    finally:
        current_tenant_id.reset(token)


def test_adapter_capabilities_are_independent_of_model_id():
    from bisheng.dsh.infrastructure.model_capabilities import model_capabilities

    one = model_capabilities(SimpleNamespace(id=1), SimpleNamespace(type="openai"))
    another = model_capabilities(SimpleNamespace(id=991), SimpleNamespace(type="openai"))
    assert one == another
    assert one.streaming and one.tools


def test_billing_month_changes_at_beijing_midnight():
    from datetime import datetime

    from bisheng.dsh.api.endpoints.models import billing_period
    from bisheng.dsh.config import DshSettings

    timezone = DshSettings().billing_timezone
    before = billing_period(datetime.fromisoformat("2026-09-30T15:59:59+00:00"), timezone)
    after = billing_period(datetime.fromisoformat("2026-09-30T16:00:00+00:00"), timezone)
    assert before != after
