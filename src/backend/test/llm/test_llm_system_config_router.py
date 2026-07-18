"""F022 T03 Router authz + envelope + audit tests.

Covers the router-layer wiring that the LLMService unit tests cannot
reach:

  * ``_envelope`` shape on GET responses              — AC-02 / AC-03 / AC-06
  * ``_resolve_write_target`` honors admin-scope       — AC-08 (super-scope)
  * ``_assert_can_write_system_config`` 19803 paths    — AC-10 (defense)
  * ``_audit_system_config_update`` writes audit log   — AC-29
  * Endpoint-to-Service-method wiring (DAO mocks only) — AC-04 / AC-08

Service-internal behaviour is covered by ``test_llm_system_config_
service.py`` and ``test_tenant_system_model_config_dao.py``; this file
focuses on the router's contract.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- _envelope --------------------------------------------------------------


def test_envelope_dumps_typed_config():
    from bisheng.llm.api.router import _envelope
    from bisheng.llm.domain.schemas import KnowledgeLLMConfig

    cfg = KnowledgeLLMConfig(embedding_model_id=42)
    env = _envelope(cfg, inherited=False, blocked=False)
    assert env["data"]["embedding_model_id"] == 42
    assert env["inherited_from_root"] is False
    assert env["fallback_blocked"] is False


def test_envelope_propagates_inherited_and_blocked_flags():
    from bisheng.llm.api.router import _envelope
    from bisheng.llm.domain.schemas import KnowledgeLLMConfig

    env = _envelope(KnowledgeLLMConfig(), inherited=True, blocked=False)
    assert env["inherited_from_root"] is True
    env = _envelope(KnowledgeLLMConfig(), inherited=False, blocked=True)
    assert env["fallback_blocked"] is True


# --- _resolve_write_target --------------------------------------------------


def test_resolve_write_target_uses_context_var_then_root():
    from bisheng.llm.api.router import ROOT_TENANT_ID, _resolve_write_target

    user = MagicMock(user_id=1)
    with patch("bisheng.llm.api.router.get_current_tenant_id", return_value=5):
        assert _resolve_write_target(user) == 5
    with patch("bisheng.llm.api.router.get_current_tenant_id", return_value=None):
        assert _resolve_write_target(user) == ROOT_TENANT_ID


# --- _assert_can_write_system_config ----------------------------------------


@pytest.mark.asyncio
async def test_super_admin_passes_assertion_for_any_target():
    from bisheng.llm.api.router import _assert_can_write_system_config

    user = MagicMock(user_id=1)
    user.has_tenant_admin = AsyncMock(return_value=False)  # never consulted
    with patch("bisheng.llm.api.router._check_is_global_super", new=AsyncMock(return_value=True)):
        # any target is fine for super
        await _assert_can_write_system_config(user, 1)
        await _assert_can_write_system_config(user, 5)
    user.has_tenant_admin.assert_not_awaited()


@pytest.mark.asyncio
async def test_child_admin_targeting_root_raises_19803():
    """AC-10 (defense): non-super caller cannot write Root."""
    from fastapi import HTTPException

    from bisheng.common.errcode.llm_tenant import LLMSystemConfigForbiddenError
    from bisheng.llm.api.router import _assert_can_write_system_config

    user = MagicMock(user_id=42)
    user.has_tenant_admin = AsyncMock(return_value=True)  # even with admin elsewhere
    with patch("bisheng.llm.api.router._check_is_global_super", new=AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as exc_info:
            await _assert_can_write_system_config(user, 1)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["status_code"] == LLMSystemConfigForbiddenError.Code


@pytest.mark.asyncio
async def test_child_admin_targeting_own_tenant_passes():
    """AC-11 natural path: target == own leaf, has_tenant_admin returns True."""
    from bisheng.llm.api.router import _assert_can_write_system_config

    user = MagicMock(user_id=42)
    user.has_tenant_admin = AsyncMock(return_value=True)
    with patch("bisheng.llm.api.router._check_is_global_super", new=AsyncMock(return_value=False)):
        await _assert_can_write_system_config(user, 5)
    user.has_tenant_admin.assert_awaited_once_with(5)


@pytest.mark.asyncio
async def test_caller_without_admin_grant_raises_19803():
    from fastapi import HTTPException

    from bisheng.common.errcode.llm_tenant import LLMSystemConfigForbiddenError
    from bisheng.llm.api.router import _assert_can_write_system_config

    user = MagicMock(user_id=42)
    user.has_tenant_admin = AsyncMock(return_value=False)
    with patch("bisheng.llm.api.router._check_is_global_super", new=AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as exc_info:
            await _assert_can_write_system_config(user, 5)
    assert exc_info.value.detail["status_code"] == LLMSystemConfigForbiddenError.Code


# --- _redact_payload --------------------------------------------------------


def test_redact_uses_jsonfieldmasker_for_known_sensitive_fields():
    """``_redact_payload`` routes through the project-wide ``JsonFieldMasker``,
    so any field listed in its ``sensitive_fields`` rule set gets masked.
    Custom field names not in the rule set pass through unchanged — adding
    new sensitive shapes is a JsonFieldMasker concern, not a per-feature
    redactor."""
    from bisheng.llm.api.router import _redact_payload

    payload = {
        "embedding_model_id": 1,
        "api_key": "sk-abc1234567890",  # JsonFieldMasker rule
        "password": "super-secret-password",  # JsonFieldMasker rule
        "prompt": "hello",
        "linsight_default_model_id": "5",
    }
    result = _redact_payload(payload)
    # Non-sensitive fields preserved verbatim.
    assert result["embedding_model_id"] == 1
    assert result["prompt"] == "hello"
    assert result["linsight_default_model_id"] == "5"
    # Known sensitive fields masked (output shape varies by rule but is
    # never the original cleartext value).
    assert result["api_key"] != "sk-abc1234567890"
    assert result["password"] != "super-secret-password"


def test_redact_handles_empty_payload():
    from bisheng.llm.api.router import _redact_payload

    assert _redact_payload(None) == {}
    assert _redact_payload({}) == {}


# --- _audit_system_config_update -------------------------------------------


@pytest.mark.asyncio
async def test_audit_writes_to_audit_log_dao():
    """AC-29: action / metadata fields land in audit_log."""
    from bisheng.llm.api.router import _audit_system_config_update

    user = MagicMock(user_id=42)
    insert_mock = AsyncMock()
    with (
        patch("bisheng.llm.api.router.AuditLogDao.ainsert_v2", insert_mock),
        patch("bisheng.llm.api.router.get_current_tenant_id", return_value=5),
    ):
        await _audit_system_config_update(
            user,
            "knowledge_llm",
            target_tenant_id=5,
            before={"embedding_model_id": 1},
            after={"embedding_model_id": 2},
        )

    insert_mock.assert_awaited_once()
    kwargs = insert_mock.call_args.kwargs
    assert kwargs["tenant_id"] == 5
    assert kwargs["operator_id"] == 42
    assert kwargs["operator_tenant_id"] == 5
    assert kwargs["action"] == "llm.system_config.update"
    assert kwargs["target_type"] == "llm_system_config"
    assert kwargs["target_id"] == "knowledge_llm"
    assert kwargs["metadata"]["key"] == "knowledge_llm"
    assert kwargs["metadata"]["target_tenant_id"] == 5
    assert kwargs["metadata"]["before"] == {"embedding_model_id": 1}
    assert kwargs["metadata"]["after"] == {"embedding_model_id": 2}


@pytest.mark.asyncio
async def test_audit_swallows_dao_failures():
    """audit_log must never block user action — AD-06 in F020 audit
    helper, same contract for F022."""
    from bisheng.llm.api.router import _audit_system_config_update

    user = MagicMock(user_id=42)
    boom = AsyncMock(side_effect=RuntimeError("db down"))
    with patch("bisheng.llm.api.router.AuditLogDao.ainsert_v2", boom):
        # Must not raise.
        await _audit_system_config_update(
            user,
            "knowledge_llm",
            5,
            before=None,
            after={"a": 1},
        )


# --- Endpoint wiring smoke (Service mocked) ---------------------------------


@pytest.mark.asyncio
async def test_get_knowledge_endpoint_returns_envelope():
    """AC-03 surface: the GET response body is the envelope shape."""
    from bisheng.llm.api.router import get_knowledge_llm
    from bisheng.llm.domain.schemas import KnowledgeLLMConfig

    fake_user = MagicMock()
    cfg = KnowledgeLLMConfig(embedding_model_id=11)
    with patch(
        "bisheng.llm.domain.services.llm.LLMService.aget_knowledge_llm_with_meta",
        new=AsyncMock(return_value=(cfg, True, False)),
    ):
        resp = await get_knowledge_llm(request=MagicMock(), login_user=fake_user)
    body = resp.data
    assert body["data"]["embedding_model_id"] == 11
    assert body["inherited_from_root"] is True
    assert body["fallback_blocked"] is False


@pytest.mark.asyncio
async def test_post_knowledge_endpoint_routes_target_and_audits():
    """AC-04 / AC-29 surface: POST writes to target tenant + audits."""
    from bisheng.llm.api.router import update_knowledge_llm
    from bisheng.llm.domain.schemas import KnowledgeLLMConfig

    fake_user = MagicMock(user_id=99)
    fake_user.has_tenant_admin = AsyncMock(return_value=True)
    payload = KnowledgeLLMConfig(embedding_model_id=33)

    update_mock = AsyncMock(return_value=payload)
    audit_mock = AsyncMock()
    aget_mock = AsyncMock(return_value=None)  # before snapshot empty

    with (
        patch("bisheng.llm.api.router._check_is_global_super", new=AsyncMock(return_value=False)),
        patch("bisheng.llm.api.router.get_current_tenant_id", return_value=5),
        patch("bisheng.llm.api.router.TenantSystemModelConfigDao.aget", aget_mock),
        patch("bisheng.llm.domain.services.llm.LLMService.update_knowledge_llm", update_mock),
        patch("bisheng.llm.api.router._audit_system_config_update", audit_mock),
    ):
        resp = await update_knowledge_llm(
            request=MagicMock(),
            login_user=fake_user,
            data=payload,
        )

    assert resp.data is payload
    update_mock.assert_awaited_once()
    update_kwargs = update_mock.call_args.kwargs
    assert update_kwargs["tenant_id"] == 5
    audit_mock.assert_awaited_once()
    audit_args = audit_mock.call_args
    # _audit_system_config_update(login_user, key, target, before=, after=)
    assert audit_args.args[0] is fake_user
    assert audit_args.args[1] == "knowledge_llm"
    assert audit_args.args[2] == 5
    assert audit_args.kwargs["after"]["embedding_model_id"] == 33


@pytest.mark.asyncio
async def test_post_knowledge_blocks_child_admin_targeting_root():
    """AC-10 surface end-to-end: a forged ContextVar=Root from a Child
    Admin context returns 403 + 19803."""
    from fastapi import HTTPException

    from bisheng.common.errcode.llm_tenant import LLMSystemConfigForbiddenError
    from bisheng.llm.api.router import update_knowledge_llm
    from bisheng.llm.domain.schemas import KnowledgeLLMConfig

    fake_user = MagicMock(user_id=42)
    fake_user.has_tenant_admin = AsyncMock(return_value=True)

    with (
        patch("bisheng.llm.api.router._check_is_global_super", new=AsyncMock(return_value=False)),
        patch("bisheng.llm.api.router.get_current_tenant_id", return_value=1),
    ):
        with pytest.raises(HTTPException) as exc:
            await update_knowledge_llm(
                request=MagicMock(),
                login_user=fake_user,
                data=KnowledgeLLMConfig(embedding_model_id=1),
            )
    assert exc.value.detail["status_code"] == LLMSystemConfigForbiddenError.Code
