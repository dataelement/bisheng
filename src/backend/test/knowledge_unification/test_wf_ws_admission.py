"""Real WS adapters bind trusted resource and original actor. 覆盖 AC: AC-68, AC-79, AC-83, AC-91."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from bisheng.api.v1 import workflow as ordinary
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.interfaces.resource_execution import WorkflowExecutionPort
from bisheng.public_endpoints.api.endpoints import workflow as public
from bisheng.workflow.application.execution_port import BoundWorkflowExecutionPort


async def test_ordinary_real_adapter_injects_bound_identity_root_and_keeps_lease(monkeypatch):
    identity = UserPayload(user_id=11, user_name="actor", tenant_id=101, user_role=[])
    websocket = SimpleNamespace(close=AsyncMock())
    dispatch = AsyncMock()
    monkeypatch.setattr(ordinary, "require_business_action", AsyncMock())
    monkeypatch.setattr(ordinary.chat_manager, "dispatch_client", dispatch)
    await ordinary.workflow_ws(
        workflow_id="wf", websocket=websocket, chat_id="chat", flow_lease_id="lease", login_user=identity
    )
    kwargs = dispatch.await_args.kwargs
    assert "workflow_execution_port" in kwargs
    port = kwargs["workflow_execution_port"]
    assert isinstance(port, WorkflowExecutionPort) and isinstance(port, BoundWorkflowExecutionPort)
    assert port._identity is identity and port._allow_preview is True
    assert kwargs["flow_lease_id"] == "lease" and dispatch.await_args.args[3] is identity
    with pytest.raises(ResourceReferenceInvalidError):
        await port.prepare_initial(claimed_flow_id="other", graph=None, chat_id="chat")


async def test_public_real_adapter_binds_normalized_id_and_preserves_guest_subject_snapshot(monkeypatch):
    identity = UserPayload(user_id=11, user_name="guest-operator", tenant_id=101, user_role=[])
    subject = object()
    execution = SimpleNamespace(operator=identity, session_subject=subject)
    snapshot = Mock()
    snapshot.model_copy.return_value.model_dump.return_value = {
        "channel": "public_v3",
        "credential_id": "guest",
        "mode": "S",
    }
    execution.snapshot = snapshot

    @asynccontextmanager
    async def public_execution(kind, identifier):
        assert kind == "workflow" and identifier == "12345678123456781234567812345678"
        yield execution

    monkeypatch.setattr(public, "public_execution", public_execution)
    monkeypatch.setattr(public.PublishedWorkflowService, "validate_websocket_session", AsyncMock())
    dispatch = AsyncMock()
    monkeypatch.setattr(public.chat_manager, "dispatch_client", dispatch)
    websocket = SimpleNamespace(close=AsyncMock())
    await public.workflow_ws(
        workflow_id=UUID("12345678-1234-5678-1234-567812345678"),
        websocket=websocket,
        chat_id="guest-chat",
        flow_lease_id="guest-lease",
    )
    kwargs = dispatch.await_args.kwargs
    assert "workflow_execution_port" in kwargs
    port = kwargs["workflow_execution_port"]
    assert port._identity is identity and port._allow_preview is False
    assert dispatch.await_args.args[1] == "12345678123456781234567812345678"
    assert kwargs["session_subject"] is subject and kwargs["execution_snapshot"]["channel"] == "public_v3"
    assert kwargs["flow_lease_id"] == "guest-lease"
    with pytest.raises(ResourceReferenceInvalidError):
        await port.prepare_initial(
            claimed_flow_id="12345678123456781234567812345678",
            graph={"nodes": [], "edges": []},
            chat_id="guest-chat",
            execution_mode="preview",
        )
    websocket.close.assert_not_awaited()
