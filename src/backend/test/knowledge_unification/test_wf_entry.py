"""WF consumers against the frozen read Port (not Core integration). 覆盖 AC: AC-37, AC-68, AC-79, AC-82, AC-83, AC-91."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.workflow.application import execution_admission as module
from bisheng.workflow.application import reference_source_owner as owner_module
from bisheng.workflow.application.execution_port import BoundWorkflowExecutionPort
from test.knowledge_unification import test_wf_transaction as fixtures

store = fixtures.store
tenant = fixtures.tenant


@pytest.fixture
async def admission(store, monkeypatch):
    engine, _ = store
    identity = UserPayload(user_id=11, user_name="actor", tenant_id=101, user_role=[])
    authorize = AsyncMock()
    monkeypatch.setattr(owner_module, "require_business_action", authorize)
    owner = owner_module.WorkflowReferenceSourceOwner()
    issued, required, transient = [], [], []

    async def issue(session, request, user):
        assert user is identity and session.in_transaction()
        scope = SimpleNamespace(snapshot=await owner.aresolve_source(session, request, user), request=request)
        issued.append(scope)
        return scope

    async def require(session, scope, user):
        assert user is identity and session.in_transaction()
        required.append(scope)
        return SimpleNamespace(snapshot=await owner.arevalidate_source(session, scope.request, user, scope.snapshot))

    async def issue_transient(session, request, user):
        assert user is identity and session.in_transaction()
        transient.append(request)
        return SimpleNamespace(snapshot=await owner.aresolve_transient(session, request, user), request=request)

    async def require_transient(session, scope, user):
        return SimpleNamespace(snapshot=await owner.arevalidate_transient(session, scope.request, user, scope.snapshot))

    runtime = SimpleNamespace(
        verifier=SimpleNamespace(
            aissue_scope=AsyncMock(side_effect=issue), aissue_transient_scope=AsyncMock(side_effect=issue_transient)
        ),
        arequire_source_valid=AsyncMock(side_effect=require),
        arequire_transient_valid=AsyncMock(side_effect=require_transient),
    )
    monkeypatch.setattr(module, "get_reference_read_runtime", AsyncMock(return_value=runtime))

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(module, "get_async_db_session", session_factory)
    return SimpleNamespace(
        identity=identity,
        engine=engine,
        authorize=authorize,
        issued=issued,
        required=required,
        transient=transient,
        runtime=runtime,
    )


async def test_saved_uses_real_version_original_identity_and_fresh_result_graph(admission):
    result = await module.prepare_saved(admission.identity, "wf", version_id=2)
    assert result.source_key.source_type == SourceType.WORKFLOW_VERSION and result.source_key.source_version == "2"
    assert len(admission.issued) == len(admission.required) == 1
    assert result.configuration_digest == admission.required[0].snapshot.configuration_digest
    graph = result.graph
    graph["nodes"].append({"data": {"id": "mutated"}})
    assert result.graph == {"nodes": [], "edges": []}
    assert "edit" in [call.kwargs["action"] for call in admission.authorize.await_args_list]


async def test_borrowed_transaction_is_not_owned_or_committed(admission, monkeypatch):
    async with AsyncSession(admission.engine) as session, session.begin():
        transaction = session.get_transaction()
        monkeypatch.setattr(session, "begin", lambda: pytest.fail("borrowed begin"))
        monkeypatch.setattr(session, "commit", AsyncMock(side_effect=AssertionError("borrowed commit")))
        monkeypatch.setattr(session, "rollback", AsyncMock(side_effect=AssertionError("borrowed rollback")))
        await module.prepare_saved(admission.identity, "wf", reference_session=session)
        assert session.get_transaction() is transaction


async def test_full_graph_comparison_rejects_nonreference_changes(admission):
    graph = {"nodes": [{"data": {"id": "prompt", "type": "start", "prompt": "arbitrary"}}], "edges": []}
    with pytest.raises(ResourceReferenceInvalidError):
        await module.prepare_saved(admission.identity, "wf", supplied_graph=graph)


async def test_supplied_graph_outer_ui_metadata_is_compatible(admission):
    result = await module.prepare_saved(
        admission.identity, "wf", supplied_graph={"nodes": [], "edges": [], "viewport": {"x": 9}, "name": "UI"}
    )
    assert result.graph == {"nodes": [], "edges": []}


async def test_transient_and_node_preview_have_no_source_identity(admission):
    graph = {"nodes": [{"data": {"id": "code", "type": "code", "group_params": []}}], "edges": []}
    preview = await module.prepare_preview(admission.identity, "wf", graph, version_hint=999)
    node = await module.prepare_node_preview(admission.identity, "wf", graph["nodes"][0], {"x": 1})
    assert preview.source_key is None and node.source_key is None
    assert not admission.issued and not admission.required
    assert node.node_data == graph["nodes"][0] and node.node_input == {"x": 1}
    node.node_input["x"] = 9
    assert node.node_input == {"x": 1}
    assert all(call.kwargs["action"] == "edit" for call in admission.authorize.await_args_list)


async def test_bound_port_rejects_rebinding_before_any_read(admission):
    port = BoundWorkflowExecutionPort("wf", admission.identity)
    with pytest.raises(ResourceReferenceInvalidError):
        await port.prepare_initial(claimed_flow_id="other", graph={"nodes": [], "edges": []}, chat_id=None)
    assert not admission.issued and not admission.transient


async def test_legacy_matching_graph_uses_saved_but_different_graph_uses_edit_preview(admission):
    port = BoundWorkflowExecutionPort("wf", admission.identity)
    assert await port.prepare_initial(claimed_flow_id="wf", graph={"nodes": [], "edges": []}, chat_id=None) == {
        "nodes": [],
        "edges": [],
    }
    assert len(admission.required) == 1
    arbitrary = {"nodes": [{"data": {"id": "code", "type": "code"}}], "edges": []}
    assert await port.prepare_initial(claimed_flow_id="wf", graph=arbitrary, chat_id=None) == arbitrary
    assert len(admission.required) == 1 and len(admission.transient) == 1


async def test_legacy_different_graph_does_not_require_invalid_current_targets(admission):
    admission.runtime.arequire_source_valid.side_effect = ResourceReferenceInvalidError()
    port = BoundWorkflowExecutionPort("wf", admission.identity)
    graph = {"nodes": [{"data": {"id": "code", "type": "code"}}], "edges": []}
    assert await port.prepare_initial(claimed_flow_id="wf", graph=graph, chat_id=None) == graph
    admission.runtime.arequire_source_valid.assert_not_awaited()


@pytest.mark.parametrize(
    "mode,graph", [("preview", {"nodes": [], "edges": []}), (None, {"nodes": [{"data": {"id": "code"}}], "edges": []})]
)
async def test_public_port_never_downgrades_to_preview(admission, mode, graph):
    port = BoundWorkflowExecutionPort("wf", admission.identity, allow_preview=False)
    with pytest.raises(ResourceReferenceInvalidError):
        await port.prepare_initial(claimed_flow_id="wf", graph=graph, chat_id="guest", execution_mode=mode)
    assert not admission.transient


@pytest.mark.parametrize("mode,version", [("unknown", None), ("saved", "bad"), ("saved", True)])
async def test_mode_and_version_are_validated_claims(admission, mode, version):
    with pytest.raises(ResourceReferenceInvalidError):
        await BoundWorkflowExecutionPort("wf", admission.identity).prepare_initial(
            claimed_flow_id="wf",
            graph={"nodes": [], "edges": []},
            chat_id=None,
            execution_mode=mode,
            version_hint=version,
        )
