"""Real workflow read facts and original authorization. 覆盖 AC: AC-68, AC-79, AC-83, AC-87, AC-89, AC-91."""

import json
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, set_visible_tenant_ids, visible_tenant_ids
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.public_endpoints.domain.context import (
    PublicApiPrincipal,
    reset_current_public_api_principal,
    set_current_public_api_principal,
)
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.application.source_contracts import (
    SourceReadRequest,
    TransientTargetRequest,
    canonical_payload_json,
)
from bisheng.workflow.application import reference_source_owner as module
from bisheng.workflow.application.reference_source_owner import WorkflowReferenceSourceOwner, normalize_execution_graph
from test.knowledge_unification import test_wf_transaction as fixtures

store = fixtures.store
tenant = fixtures.tenant


@pytest.fixture
def identity():
    return UserPayload(user_id=11, user_name="caller", tenant_id=101, user_role=[])


@pytest.fixture
def authorization(monkeypatch):
    auth = AsyncMock()
    monkeypatch.setattr(module, "require_business_action", auth)
    return auth


def request(version=None, **kwargs):
    return SourceReadRequest(SourceType.WORKFLOW_VERSION, "wf", version, **kwargs)


async def test_real_current_snapshot_is_canonical_and_no_managed_entities(store, identity, authorization):
    async_engine, _ = store
    async with AsyncSession(async_engine) as session, session.begin():
        owner = WorkflowReferenceSourceOwner()
        snapshot = await owner.aresolve_source(session, request(), identity)
        assert snapshot.source_key.source_version == "1" and snapshot.source_key.tenant_id == 101
        payload = json.loads(snapshot.payload_json)
        assert payload["graph"] == {"nodes": [], "edges": []}
        assert payload["root"]["id"] == "wf" and payload["version"]["id"] == 1
        assert snapshot.payload_json == canonical_payload_json(payload)
        assert not session.identity_map and not session.new and not session.dirty
        authorization.assert_awaited_once_with(identity, resource_type="workflow", resource_id="wf", action="visible")


async def test_noncurrent_requires_original_edit_but_version_type_is_not_new_gate(store, identity, authorization):
    engine, sync = store
    with sync.begin() as connection:
        connection.execute(sa.update(FlowVersion).where(FlowVersion.id == 2).values(flow_type=5))
    async with AsyncSession(engine) as session, session.begin():
        snapshot = await WorkflowReferenceSourceOwner().aresolve_source(session, request("2"), identity)
        assert snapshot.source_key.source_version == "2"
    assert [call.kwargs["action"] for call in authorization.await_args_list] == ["visible", "edit"]
    assert all(call.args[0] is identity for call in authorization.await_args_list)


async def test_public_cannot_select_noncurrent(store, identity, authorization):
    engine, _ = store
    token = set_current_public_api_principal(
        PublicApiPrincipal(
            tenant_id=101, operator_user_id=11, operator_name="guest", resource_type="workflow", resource_id="wf"
        )
    )
    try:
        async with AsyncSession(engine) as session, session.begin():
            with pytest.raises(ResourceReferenceInvalidError):
                await WorkflowReferenceSourceOwner().aresolve_source(session, request("2"), identity)
    finally:
        reset_current_public_api_principal(token)


async def test_targets_then_revalidation_reads_current_and_reauthorizes(store, identity, authorization):
    engine, sync = store
    owner = WorkflowReferenceSourceOwner()
    async with AsyncSession(engine) as session, session.begin():
        before = await owner.aresolve_source(session, request(), identity)
        with sync.begin() as connection:
            connection.execute(sa.update(Flow).where(Flow.id == "wf").values(status=2))
        after = await owner.arevalidate_source(session, request(), identity, before)
        assert before.configuration_digest != after.configuration_digest
        assert json.loads(after.payload_json)["root"]["status"] == 2
        assert not session.identity_map
    assert authorization.await_count == 2


async def test_revoked_authorization_blocks_revalidation(store, identity, authorization):
    engine, _ = store
    async with AsyncSession(engine) as session, session.begin():
        owner = WorkflowReferenceSourceOwner()
        before = await owner.aresolve_source(session, request(), identity)
        authorization.side_effect = UnAuthorizedError()
        with pytest.raises(UnAuthorizedError):
            await owner.arevalidate_source(session, request(), identity, before)


@pytest.mark.parametrize(
    "change", ["deleted_root", "deleted_version", "wrong_parent", "duplicate_current", "mirror_drift"]
)
async def test_invalid_persistent_source_never_becomes_a_snapshot(store, identity, authorization, change):
    engine, sync = store
    with sync.begin() as connection:
        if change == "deleted_root":
            connection.execute(sa.update(Flow).where(Flow.id == "wf").values(is_delete=1))
        elif change == "deleted_version":
            connection.execute(sa.update(FlowVersion).where(FlowVersion.id == 1).values(is_delete=1))
        elif change == "wrong_parent":
            connection.execute(sa.update(FlowVersion).where(FlowVersion.id == 1).values(flow_id="other"))
        elif change == "duplicate_current":
            connection.execute(sa.update(FlowVersion).where(FlowVersion.id == 2).values(is_current=1))
        else:
            connection.execute(
                sa.update(Flow)
                .where(Flow.id == "wf")
                .values(data={"nodes": [{"data": {"id": "new", "type": "start"}}], "edges": []})
            )
    async with AsyncSession(engine) as session, session.begin():
        with pytest.raises((NotFoundError, ReferenceCoverageNotReadyError)):
            await WorkflowReferenceSourceOwner().aresolve_source(session, request(), identity)


async def test_automatic_candidate_root_visibility_still_requires_business_authorization(
    store, identity, authorization
):
    engine, sync = store
    with sync.begin() as connection:
        connection.execute(sa.update(Flow).where(Flow.id == "other").values(tenant_id=1))
        connection.execute(
            sa.insert(FlowVersion).values(
                id=9, flow_id="other", name="root", tenant_id=1, is_current=1, data={"nodes": [], "edges": []}
            )
        )
    token = set_visible_tenant_ids(frozenset({101, 1}))
    authorization.side_effect = UnAuthorizedError()
    try:
        async with AsyncSession(engine) as session, session.begin():
            with pytest.raises(UnAuthorizedError):
                await WorkflowReferenceSourceOwner().aresolve_source(
                    session, SourceReadRequest(SourceType.WORKFLOW_VERSION, "other"), identity
                )
            assert not session.identity_map
    finally:
        visible_tenant_ids.reset(token)


async def test_ambient_bypass_is_not_source_authority(store, identity, authorization):
    engine, _ = store
    async with AsyncSession(engine) as session, session.begin():
        with bypass_tenant_filter(), pytest.raises(ResourceReferenceInvalidError):
            await WorkflowReferenceSourceOwner().aresolve_source(session, request(), identity)


async def test_transient_is_root_edit_and_never_has_source_key(store, identity, authorization):
    engine, _ = store
    req = TransientTargetRequest(
        "workflow", "wf", canonical_payload_json({"graph": {"nodes": [], "edges": []}, "node_input": {"value": "x"}})
    )
    async with AsyncSession(engine) as session, session.begin():
        snapshot = await WorkflowReferenceSourceOwner().aresolve_transient(session, req, identity)
        assert snapshot.resource_id == "wf" and snapshot.owner_tenant_id == 101
        assert not hasattr(snapshot, "source_key") and not session.identity_map
        assert json.loads(snapshot.payload_json)["node_input"] == {"value": "x"}
        authorization.assert_awaited_once_with(identity, resource_type="workflow", resource_id="wf", action="edit")


def test_graph_normalization_keeps_all_execution_content_order_and_fresh_copy():
    graph = {
        "nodes": [{"data": {"id": "b", "prompt": "one"}}, {"data": {"id": "a"}}],
        "edges": [{"id": "z"}, {"id": "a"}],
        "viewport": {"x": 5},
        "name": "ui",
    }
    normalized = normalize_execution_graph(graph)
    assert list(normalized) == ["nodes", "edges"]
    assert normalized == {"nodes": graph["nodes"], "edges": graph["edges"]}
    normalized["nodes"][0]["data"]["prompt"] = "changed"
    assert graph["nodes"][0]["data"]["prompt"] == "one"


@pytest.mark.parametrize("version", ["3", "999", "not-number"])
async def test_missing_or_malformed_version_is_not_current_fallback(store, identity, authorization, version):
    engine, _ = store
    async with AsyncSession(engine) as session, session.begin():
        with pytest.raises((NotFoundError, ResourceReferenceInvalidError)):
            await WorkflowReferenceSourceOwner().aresolve_source(session, request(version), identity)


async def test_preview_knowledge_kind_candidate_unlocked_final_current_read(
    store, identity, authorization, monkeypatch
):
    """The final authorization must use the locked target's actual current kind."""
    engine, sync = store
    metadata = sa.MetaData()
    knowledge = sa.Table(
        "knowledge",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer),
        sa.Column("type", sa.Integer),
    )
    metadata.create_all(sync)
    with sync.begin() as connection:
        connection.execute(knowledge.insert().values(id=7, tenant_id=101, type=0))
    graph = {
        "nodes": [
            {
                "data": {
                    "id": "retrieve",
                    "type": "knowledge_retriever",
                    "group_params": [
                        {"params": [{"key": "knowledge", "value": {"type": "space", "value": [{"key": 7}]}}]}
                    ],
                }
            }
        ],
        "edges": [],
    }
    req = TransientTargetRequest("workflow", "wf", canonical_payload_json({"graph": graph}))
    locks = []
    async with AsyncSession(engine) as session, session.begin():
        scalar = session.scalar

        async def record(query, *args, **kwargs):
            if "knowledge.type" in str(query):
                locks.append(query._for_update_arg is not None)
            return await scalar(query, *args, **kwargs)

        monkeypatch.setattr(session, "scalar", record)
        owner = WorkflowReferenceSourceOwner()
        before = await owner.aresolve_transient(session, req, identity)
        with sync.begin() as connection:
            connection.execute(knowledge.update().where(knowledge.c.id == 7).values(type=3))
        await owner.arevalidate_transient(session, req, identity, before)
    assert locks == [False, True]
    knowledge_auth = [
        call.kwargs for call in authorization.await_args_list if call.kwargs["resource_type"].startswith("knowledge_")
    ]
    assert knowledge_auth == [
        {"resource_type": "knowledge_library", "resource_id": "7", "action": "visible"},
        {"resource_type": "knowledge_space", "resource_id": "7", "action": "visible"},
    ]
