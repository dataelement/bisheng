"""Public display graphs never replace the current server execution graph."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import current_tenant_id
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.public_endpoints.api.endpoints import flow, workflow
from bisheng.public_endpoints.domain.context import (
    PublicApiPrincipal,
    reset_current_public_api_principal,
    set_current_public_api_principal,
)
from bisheng.workflow.application.execution_port import BoundWorkflowExecutionPort
from test.knowledge_unification import test_wf_entry as fixtures

store, tenant = fixtures.store, fixtures.tenant
admission, real_core = fixtures.admission, fixtures.real_core


@pytest.mark.parametrize("graph", [None, {}, "untrusted", {"nodes": [{"data": {"code": "client-code"}}]}])
async def test_endpoint_bound_published_policy_ignores_browser_graph_and_validates_saved_source(admission, graph):
    port = BoundWorkflowExecutionPort("wf", admission.identity, published_only=True)
    result = await port.prepare_initial(claimed_flow_id="wf", graph=graph, chat_id="guest")
    assert result == {"nodes": [], "edges": []}
    assert len(admission.issued) == len(admission.required) == 1
    assert admission.issued[0].request.source_version is None
    assert not admission.transient


@pytest.mark.parametrize("mode", ["preview", "unknown", [], True])
async def test_published_policy_rejects_preview_or_invalid_modes_before_reads(admission, mode):
    with pytest.raises(ResourceReferenceInvalidError):
        await BoundWorkflowExecutionPort("wf", admission.identity, published_only=True).prepare_initial(
            claimed_flow_id="wf", graph=None, chat_id=None, execution_mode=mode
        )
    assert not admission.issued and not admission.transient


@pytest.mark.parametrize("version", ["bad", True, "01", 0])
async def test_published_policy_preserves_version_claim_validation(admission, version):
    with pytest.raises(ResourceReferenceInvalidError):
        await BoundWorkflowExecutionPort("wf", admission.identity, published_only=True).prepare_initial(
            claimed_flow_id="wf", graph=None, chat_id="guest", version_hint=version
        )
    assert not admission.issued and not admission.transient


async def test_published_policy_rejects_a_historical_version_even_without_public_context(admission):
    with pytest.raises(ResourceReferenceInvalidError) as caught:
        await BoundWorkflowExecutionPort("wf", admission.identity, published_only=True).prepare_initial(
            claimed_flow_id="wf", graph=None, chat_id="guest", version_hint=2
        )
    assert caught.value.kwargs["reason"] == "public_workflow_current_version_required"
    assert admission.issued[0].snapshot.source_key.source_version == "1"
    assert not admission.required and not admission.transient


async def test_published_policy_accepts_a_matching_current_version_hint(admission):
    await BoundWorkflowExecutionPort("wf", admission.identity, published_only=True).prepare_initial(
        claimed_flow_id="wf", graph=None, chat_id="guest", execution_mode="saved", version_hint=1
    )
    assert len(admission.required) == 1


async def test_published_policy_keeps_invalid_resource_refusal(admission):
    error = ResourceReferenceInvalidError(reason="reference_target_invalid")
    admission.runtime.arequire_source_valid.side_effect = error
    with pytest.raises(ResourceReferenceInvalidError) as caught:
        await BoundWorkflowExecutionPort("wf", admission.identity, published_only=True).prepare_initial(
            claimed_flow_id="wf", graph=None, chat_id="guest"
        )
    assert caught.value is error
    assert not admission.transient


async def test_published_policy_never_rebinds_to_a_message_workflow(admission):
    with pytest.raises(ResourceReferenceInvalidError) as caught:
        await BoundWorkflowExecutionPort("wf", admission.identity, published_only=True).prepare_initial(
            claimed_flow_id="other", graph=None, chat_id="guest"
        )
    assert caught.value.kwargs["reason"] == "workflow_connection_root_mismatch"
    assert not admission.issued


async def test_published_policy_never_reads_another_tenants_workflow(admission):
    token = current_tenant_id.set(202)
    try:
        with pytest.raises(NotFoundError):
            await BoundWorkflowExecutionPort("wf", admission.identity, published_only=True).prepare_initial(
                claimed_flow_id="wf", graph=None, chat_id="guest"
            )
    finally:
        current_tenant_id.reset(token)
    assert not admission.required and not admission.transient


async def test_published_policy_reads_the_latest_current_version_on_each_admission(admission):
    port = BoundWorkflowExecutionPort("wf", admission.identity, published_only=True)
    await port.prepare_initial(claimed_flow_id="wf", graph=None, chat_id="guest")
    replacement = {"nodes": [{"data": {"id": "current", "type": "code", "code": "new saved code"}}], "edges": []}
    async with AsyncSession(admission.engine) as session, session.begin():
        await session.execute(sa.update(Flow).where(Flow.id == "wf", Flow.tenant_id == 101).values(data=replacement))
        await session.execute(
            sa.update(FlowVersion).where(FlowVersion.flow_id == "wf", FlowVersion.tenant_id == 101).values(is_current=0)
        )
        await session.execute(
            sa.update(FlowVersion)
            .where(FlowVersion.id == 2, FlowVersion.tenant_id == 101)
            .values(is_current=1, data=replacement)
        )
    assert await port.prepare_initial(claimed_flow_id="wf", graph={}, chat_id="guest") == replacement
    assert [scope.snapshot.source_key.source_version for scope in admission.required] == ["1", "2"]
    assert not admission.transient


async def test_public_http_projection_then_ws_admission_uses_complete_sql_current_graph(real_core, monkeypatch):
    fid = UUID(int=41).hex
    saved = {
        "nodes": [{"id": "code_1", "data": {"id": "code_1", "name": "Code", "type": "code", "code": "SERVER_ONLY"}}],
        "edges": [],
    }
    async with AsyncSession(real_core.engine) as session, session.begin():
        await session.execute(
            sa.update(Flow).where(Flow.id == "wf", Flow.tenant_id == 101).values(id=fid, status=2, data=saved)
        )
        await session.execute(
            sa.update(FlowVersion).where(FlowVersion.flow_id == "wf", FlowVersion.tenant_id == 101).values(flow_id=fid)
        )
        await session.execute(
            sa.update(FlowVersion).where(FlowVersion.id == 1, FlowVersion.tenant_id == 101).values(data=saved)
        )

    @asynccontextmanager
    async def public_context(resource_type, resource_id):
        assert resource_type == "workflow" and resource_id == fid
        principal = PublicApiPrincipal(
            tenant_id=101, operator_user_id=11, operator_name="original", resource_type="workflow", resource_id=fid
        )
        token = set_current_public_api_principal(principal)
        try:
            # Transport snapshot serialization is not under test; source identity
            # and tenant checks use the actual principal and read runtime.
            snapshot = Mock()
            snapshot.model_copy.return_value.model_dump.return_value = {"channel": "public_v3"}
            yield SimpleNamespace(
                operator=real_core.identity,
                session_subject=SessionSubject.public_v3(tenant_id=101, operator_user_id=11, resource_id=fid),
                snapshot=snapshot,
            )
        finally:
            reset_current_public_api_principal(token)

    monkeypatch.setattr(flow, "public_execution", public_context)
    monkeypatch.setattr(workflow, "public_execution", public_context)
    monkeypatch.setattr(
        flow.FlowService,
        "get_one_flow",
        AsyncMock(return_value=resp_200(data={"id": fid, "name": "Published", "data": saved})),
    )
    session_check = AsyncMock()
    monkeypatch.setattr(workflow.PublishedWorkflowService, "validate_websocket_session", session_check)
    app = FastAPI()
    app.include_router(flow.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/flows/{fid}")
    assert response.status_code == 200 and "SERVER_ONLY" not in response.text
    display = response.json()["data"]["data"]
    assert display != saved
    received = []

    async def dispatch(*args, **kwargs):
        assert kwargs["execution_snapshot"]["channel"] == "public_v3"
        port = kwargs["workflow_execution_port"]
        received.append(await port.prepare_initial(claimed_flow_id=fid, graph=display, chat_id=None))
        received.append(
            await port.prepare_initial(
                claimed_flow_id=fid, graph={"nodes": [{"data": {"code": "CLIENT_ONLY"}}], "edges": []}, chat_id=None
            )
        )

    monkeypatch.setattr(workflow.chat_manager, "dispatch_client", dispatch)
    await workflow.workflow_ws(workflow_id=UUID(fid), websocket=AsyncMock(), chat_id=None, flow_lease_id=None)
    session_check.assert_awaited_once()
    assert received == [saved, saved]
