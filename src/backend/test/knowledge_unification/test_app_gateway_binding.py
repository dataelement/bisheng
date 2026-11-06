"""T446: cached resolution never reaches a provider before current UUID binding.

覆盖 AC: AC-68, AC-71, AC-87, AC-88, AC-89, AC-92
The real APP SQL admission has separate tests; provider effects are forbidden here.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.model_face import ModelFaceCatalogUnavailableError, ModelFaceModelRevokedError
from bisheng.llm.domain.services.model_catalog import ModelRange, ResolvedModel
from bisheng.open_api.domain.schemas.model_gateway import ChatCompletionRequest
from bisheng.open_api.domain.services import model_gateway_service as gateway
from bisheng.open_api.domain.services import model_range_policy as policy
from test.open_api.model_gateway_fixtures import hosted_app_principal, service_account_principal

MODEL = ResolvedModel(10, 1, "gpt-4o", "azure", "openai", "azure/gpt-4o")


@pytest.mark.parametrize(
    "error,expected",
    [
        (ReferenceCoverageNotReadyError(reason="source_not_indexed"), ModelFaceCatalogUnavailableError),
        (ResourceReferenceInvalidError(reason="reference_target_invalid"), ModelFaceModelRevokedError),
        (KnowledgeOperationPlanConflictError(reason="model_binding_identity_changed"), ModelFaceModelRevokedError),
        (RuntimeError("backend unavailable"), ModelFaceCatalogUnavailableError),
    ],
)
async def test_binding_failures_stop_provider_and_preserve_original_principal(monkeypatch, error, expected):
    principal = hosted_app_principal()
    admitted = AsyncMock(side_effect=error)
    monkeypatch.setattr(policy, "_declaration_port", SimpleNamespace(assert_model_binding=admitted))
    monkeypatch.setattr(
        gateway, "resolve_range_and_subject", AsyncMock(return_value=(ModelRange(), policy.ResolvedSubject("app_self")))
    )
    monkeypatch.setattr(gateway, "resolve_model_name", AsyncMock(return_value=MODEL))
    instantiate = AsyncMock(side_effect=AssertionError("provider must not be initialized"))
    monkeypatch.setattr(gateway.ModelGatewayService, "_instantiate", instantiate)
    monkeypatch.setattr(gateway.ModelGatewayService, "_start_record", Mock(return_value=SimpleNamespace()))
    finish = Mock()
    monkeypatch.setattr(gateway.ModelGatewayService, "_finish_record", finish)
    request = ChatCompletionRequest(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    with pytest.raises(expected) as raised:
        await gateway.ModelGatewayService.complete(principal, None, request)
    assert raised.value.__cause__ is error
    admitted.assert_awaited_once_with(principal, "gpt-4o", MODEL)
    instantiate.assert_not_awaited()
    finish.assert_called_once()


async def test_admission_occurs_immediately_before_provider_initialization(monkeypatch):
    principal = hosted_app_principal()
    events = []

    async def admit(identity, requested, resolved):
        assert identity is principal and resolved is MODEL and requested == "gpt-4o"
        events.append("admit")

    monkeypatch.setattr(policy, "_declaration_port", SimpleNamespace(assert_model_binding=admit))
    monkeypatch.setattr(
        gateway, "resolve_range_and_subject", AsyncMock(return_value=(ModelRange(), policy.ResolvedSubject("app_self")))
    )
    monkeypatch.setattr(gateway, "resolve_model_name", AsyncMock(return_value=MODEL))
    monkeypatch.setattr(gateway.ModelGatewayService, "_start_record", Mock(return_value=SimpleNamespace()))

    async def instantiate(identity, resolved, request):
        events.append("instantiate")
        raise RuntimeError("stop at provider boundary")

    monkeypatch.setattr(gateway.ModelGatewayService, "_instantiate", instantiate)
    with pytest.raises(RuntimeError, match="stop at provider boundary"):
        await gateway.ModelGatewayService.complete(
            principal, None, ChatCompletionRequest(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
        )
    assert events == ["admit", "instantiate"]


@pytest.mark.parametrize(
    "port", [SimpleNamespace(), SimpleNamespace(assert_model_binding=AsyncMock(return_value=True))]
)
async def test_missing_or_incomplete_binding_port_is_not_a_model_permit(monkeypatch, port):
    monkeypatch.setattr(policy, "_declaration_port", port)
    with pytest.raises(ModelFaceCatalogUnavailableError):
        await policy.assert_hosted_model_binding(hosted_app_principal(), "gpt-4o", MODEL)


async def test_ordinary_service_account_keeps_original_model_path(monkeypatch):
    port = SimpleNamespace(assert_model_binding=AsyncMock(side_effect=AssertionError("not hosted")))
    monkeypatch.setattr(policy, "_declaration_port", port)
    await policy.assert_hosted_model_binding(service_account_principal(), "gpt-4o", MODEL)
    port.assert_model_binding.assert_not_awaited()
