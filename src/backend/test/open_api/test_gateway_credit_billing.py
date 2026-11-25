from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.dsh import DshMonthlyTokenLimitExceededError
from bisheng.common.errcode.model_face import ModelFaceAccessTokenRefusedError
from bisheng.common.services.config_service import settings
from bisheng.dsh.domain.services import chat_credits
from bisheng.open_api.api.exception_handlers import render_openai_error
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot, OpenApiPrincipal
from bisheng.open_api.domain.http_status import open_api_http_status
from bisheng.open_api.domain.models.model_call_record import RESULT_LIMIT_EXCEEDED
from bisheng.open_api.domain.schemas.model_gateway import ChatCompletionRequest
from bisheng.open_api.domain.services.access_context import open_api_access_context
from bisheng.open_api.domain.services.execution_context import restore_execution_context
from bisheng.open_api.domain.services.model_gateway_service import ModelGatewayService
from bisheng.open_api.domain.services.model_range_policy import (
    ACCESS_TOKEN_HEADER,
    ModelRange,
    ResolvedSubject,
)


async def test_non_hosted_open_api_context_and_execution_snapshot_are_unbilled(monkeypatch):
    monkeypatch.setattr(settings.credit_billing, "enabled", True)

    for actor_kind, auth_kind in (("service_account", "service_account"), ("natural_person", "user")):
        principal = OpenApiPrincipal(
            credential_id=1,
            tenant_id=1,
            actor_kind=actor_kind,
            actor_id=50,
            actor_name="caller",
            authorization_subject_type=auth_kind,
            authorization_subject_id=50,
            resource_owner_user_id=50,
            effective_user_id=50,
            mode="S",
            scopes=frozenset({"chat:invoke"}),
        )

        monkeypatch.setattr(
            "bisheng.open_api.domain.services.access_context.resolve_request_identity",
            AsyncMock(return_value=principal),
        )
        monkeypatch.setattr(
            "bisheng.open_api.domain.services.access_context.validate_bearer",
            AsyncMock(return_value=principal),
        )
        monkeypatch.setattr(
            "bisheng.open_api.domain.services.access_context.assert_no_removed_identity_headers",
            lambda headers: None,
        )
        monkeypatch.setattr(
            "bisheng.utils.http_middleware._check_is_global_super",
            AsyncMock(return_value=False),
        )
        monkeypatch.setattr(
            "bisheng.permission.application.relation_api.is_tenant_admin",
            AsyncMock(return_value=False),
        )
        monkeypatch.setattr(
            "bisheng.open_api.domain.services.tenant_setting_service.TenantSettingService.get_policy_sync",
            lambda tenant_id: SimpleNamespace(data_scope="ALL", enabled=True),
            raising=False,
        )
        monkeypatch.setattr(
            "bisheng.open_api.domain.services.access_context.TenantSettingService.get_policy",
            AsyncMock(return_value=SimpleNamespace(data_scope="ALL", enabled=True)),
        )

        marker = SimpleNamespace(scope=None, modes=frozenset({"S"}), hosted_app=False)
        async with open_api_access_context(
            authorization="Bearer bs-test",
            headers=(),
            marker=marker,
            on_behalf_of=None,
            end_user=None,
            credential_validator=AsyncMock(return_value=principal),
            tenant_setting_service=SimpleNamespace(
                get_policy=AsyncMock(return_value=SimpleNamespace(data_scope="ALL", enabled=True))
            ),
        ) as admitted:
            assert admitted.actor_kind == actor_kind
            assert chat_credits.is_open_api_unbilled() is True
            assert chat_credits.governed(SimpleNamespace(app_type=ApplicationTypeEnum.ASSISTANT)) is False
            assert chat_credits.governed(SimpleNamespace(app_type=ApplicationTypeEnum.WORKFLOW)) is False
            assert chat_credits.governed(SimpleNamespace(app_type=ApplicationTypeEnum.LINSIGHT)) is False

        snapshot = OpenApiExecutionSnapshot(
            tenant_id=1,
            actor_kind=actor_kind,
            actor_id=50,
            authorization_subject_type=auth_kind,
            authorization_subject_id=50,
            resource_owner_user_id=50,
            effective_user_id=50,
            mode="S",
            credential_id=1,
            trace_id="trace-1",
            channel="open_api_v2",
        ).model_dump()
        monkeypatch.setattr(
            "bisheng.open_api.domain.services.execution_context.validate_execution_snapshot",
            lambda snap: None,
        )
        with restore_execution_context(snapshot):
            assert chat_credits.is_open_api_unbilled() is True
            assert chat_credits.governed(SimpleNamespace(app_type=ApplicationTypeEnum.WORKFLOW)) is False


@pytest.mark.parametrize(
    ("scenario", "header_token", "preview_session_id", "expected_billing_user_id"),
    [
        ("obo_visitor", "valid-obo", None, 2001),
        ("no_token_app_owner", None, None, 1001),
        ("preview_reviewer_bills_owner", "preview-obo", "preview-sess-1", 1001),
    ],
)
async def test_hosted_app_billing_user_routing_and_admin_selected(
    monkeypatch, scenario, header_token, preview_session_id, expected_billing_user_id
):
    monkeypatch.setattr(settings.credit_billing, "enabled", True)
    instantiated_calls = []
    observed_context = []

    principal = OpenApiPrincipal(
        credential_id=9,
        tenant_id=1,
        actor_kind="hosted_app",
        actor_id=1001,
        actor_name="demo-app",
        authorization_subject_type="service_account",
        authorization_subject_id=1001,
        resource_owner_user_id=1001,
        effective_user_id=1001,
        mode="S",
        scopes=frozenset({"model:chat"}),
        subject_ref="app-uuid-1",
        preview_session_id=preview_session_id,
        preview_viewer_user_id=3001 if preview_session_id else None,
        preview_capability_user_id=1001 if preview_session_id else None,
    )

    subject = (
        ResolvedSubject(subject_kind="user", subject_id=2001 if not preview_session_id else 3001, app_id="app-uuid-1")
        if header_token
        else ResolvedSubject(subject_kind="app_self", app_id="app-uuid-1")
    )

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.model_gateway_service.resolve_range_and_subject",
        AsyncMock(return_value=(ModelRange(kind="tenant"), subject)),
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.model_gateway_service.resolve_model_name",
        AsyncMock(
            return_value=SimpleNamespace(
                model_id=7,
                server_id=3,
                model_name="gpt-4o",
                server_name="openai",
                server_type="openai",
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.model_gateway_service.assert_hosted_model_binding",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.model_gateway_service.model_call_record_writer",
        SimpleNamespace(enqueue=lambda record: None),
    )

    class FakeLLM:
        async def ainvoke(self, messages, **kwargs):
            observed_context.append((chat_credits.is_open_api_unbilled(), chat_credits.current_billing_source()))
            return SimpleNamespace(id="resp-1", content="ok", usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})

    async def fake_get_bisheng_llm(**kwargs):
        instantiated_calls.append(kwargs)
        return FakeLLM()

    monkeypatch.setattr("bisheng.llm.domain.services.llm.LLMService.get_bisheng_llm", fake_get_bisheng_llm)

    headers = {ACCESS_TOKEN_HEADER: header_token} if header_token else {}
    req_obj = SimpleNamespace(headers=headers, scope={})
    body = ChatCompletionRequest(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=False)

    resp = await ModelGatewayService.complete(principal, req_obj, body)
    assert resp.choices[0].message.content == "ok"
    assert len(instantiated_calls) == 1
    assert instantiated_calls[0]["user_id"] == expected_billing_user_id
    assert instantiated_calls[0]["admin_selected"] is True
    assert observed_context == [(False, ("hosted_app", "app-uuid-1"))]


async def test_hosted_app_expired_or_forged_token_raises_26504_and_quota_exhausted_returns_429(monkeypatch):
    monkeypatch.setattr(settings.credit_billing, "enabled", True)
    recorded = []

    principal = OpenApiPrincipal(
        credential_id=9,
        tenant_id=1,
        actor_kind="hosted_app",
        actor_id=1001,
        actor_name="demo-app",
        authorization_subject_type="service_account",
        authorization_subject_id=1001,
        resource_owner_user_id=1001,
        effective_user_id=1001,
        mode="S",
        scopes=frozenset({"model:chat"}),
        subject_ref="app-uuid-1",
    )

    # 1. Invalid OBO token raises 26504 (never falls back to owner)
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.model_range_policy._access_subject_verifier",
        SimpleNamespace(verify=lambda *args, **kwargs: None),
    )
    req_invalid = SimpleNamespace(headers={ACCESS_TOKEN_HEADER: "bad-token"}, scope={})
    body = ChatCompletionRequest(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=False)
    with pytest.raises(ModelFaceAccessTokenRefusedError) as exc_info:
        await ModelGatewayService.complete(principal, req_invalid, body)
    assert exc_info.value.code == 26504

    # 2. HTTP status & OpenAI error envelope for 26121
    err = DshMonthlyTokenLimitExceededError()
    assert open_api_http_status(err) == 429
    rendered = render_openai_error(err)
    assert rendered.status_code == 429
    payload = json.loads(rendered.body.decode())
    assert payload["error"]["type"] == "rate_limit_error"
    assert payload["error"]["code"] == "credit_exhausted"
    assert payload["error"]["bisheng_code"] == 26121

    # 3. ModelGatewayService re-raises DshMonthlyTokenLimitExceededError and records RESULT_LIMIT_EXCEEDED
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.model_gateway_service.resolve_range_and_subject",
        AsyncMock(
            return_value=(
                ModelRange(kind="tenant"),
                ResolvedSubject(subject_kind="user", subject_id=2001, app_id="app-uuid-1"),
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.model_gateway_service.resolve_model_name",
        AsyncMock(
            return_value=SimpleNamespace(
                model_id=7,
                server_id=3,
                model_name="gpt-4o",
                server_name="openai",
                server_type="openai",
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.model_gateway_service.assert_hosted_model_binding",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.model_gateway_service.model_call_record_writer",
        SimpleNamespace(enqueue=lambda record: recorded.append(record)),
    )

    class ExhaustedLLM:
        async def ainvoke(self, messages, **kwargs):
            raise DshMonthlyTokenLimitExceededError()

    monkeypatch.setattr(
        "bisheng.llm.domain.services.llm.LLMService.get_bisheng_llm",
        AsyncMock(return_value=ExhaustedLLM()),
    )

    req_valid = SimpleNamespace(headers={ACCESS_TOKEN_HEADER: "ok-token"}, scope={})
    with pytest.raises(DshMonthlyTokenLimitExceededError):
        await ModelGatewayService.complete(principal, req_valid, body)

    assert len(recorded) == 1
    assert recorded[0].result == RESULT_LIMIT_EXCEEDED
    assert recorded[0].error_code == 26121
    assert recorded[0].http_status == 429
