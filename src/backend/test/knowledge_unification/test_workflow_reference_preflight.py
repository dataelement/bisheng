"""Actual SQL/source/target preflight: unsaved selections, scope and no writes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.database import tenant_filter
from bisheng.knowledge.application.source_read_target_owner import KnowledgeSourceReadTargetOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.resource_reference.application.source_contracts import ReadIdentityFacts
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from bisheng.workflow.application import execution_admission as admission
from bisheng.workflow.application import preview_knowledge_validation as validation
from bisheng.workflow.application import reference_source_owner as source
from test.knowledge_unification import test_wf_transaction as fixtures

store = fixtures.store
tenant = fixtures.tenant


def graph(ids=(4,), count=3):
    return {
        "nodes": [
            {
                "id": f"rag_{i}",
                "data": {
                    "id": f"rag_{i}",
                    "name": f"node-{i}",
                    "type": "rag",
                    "group_params": [
                        {
                            "params": [
                                {
                                    "key": "knowledge",
                                    "value": {
                                        "type": "space",
                                        "value": [{"key": ident, "label": f"saved-{ident}"} for ident in ids],
                                    },
                                }
                            ]
                        }
                    ],
                },
            }
            for i in range(count)
        ],
        "edges": [],
    }


class IdentityPort:
    async def acapture(self, identity):
        return ReadIdentityFacts(101, (identity.user_id, "original-request"))


@pytest.fixture
async def preflight(store, monkeypatch):
    engine, sync = store
    tables = [Knowledge.__table__, KnowledgeFile.__table__, ResourceReferenceTombstone.__table__]
    for table in tables:
        table.create(sync, checkfirst=True)
    names = tenant_filter._tenant_aware_tables | {table.name for table in tables}
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    with sync.begin() as connection:
        connection.execute(
            sa.insert(Knowledge),
            [
                {"id": 1, "name": "local", "tenant_id": 101, "user_id": 11, "type": 3},
                {"id": 2, "name": "foreign-secret", "tenant_id": 202, "user_id": 21, "type": 3},
                {"id": 3, "name": "qa", "tenant_id": 101, "user_id": 11, "type": 1},
            ],
        )
    authorize = AsyncMock()
    visible = AsyncMock(side_effect=lambda identity, **kwargs: {str(i): {"visible"} for i in kwargs["resource_ids"]})
    monkeypatch.setattr(source, "require_business_action", authorize)
    monkeypatch.setattr(validation, "batch_check_business_actions", visible)
    verifier = SourceReadVerifier({"workflow_version": source.WorkflowReferenceSourceOwner()}, IdentityPort())
    targets = KnowledgeSourceReadTargetOwner(verifier)
    runtime = ReferenceSourceReadRuntime(verifier, SourceReadRepository(verifier), {"knowledge_space": targets})
    monkeypatch.setattr(admission, "get_reference_read_runtime", AsyncMock(return_value=runtime))
    return SimpleNamespace(
        engine=engine,
        sync=sync,
        runtime=runtime,
        authorize=authorize,
        visible=visible,
        user=UserPayload(user_id=11, user_name="ordinary-editor", tenant_id=101, user_role=[]),
    )


async def inspect(ctx, data, workflow="wf"):
    async with AsyncSession(ctx.engine) as session, session.begin():
        return await admission.preflight_preview(ctx.user, workflow, data, reference_session=session)


async def test_unsaved_missing_selection_marks_all_nodes_and_never_writes(preflight):
    before = fixtures.snapshot(preflight.sync)
    statements = []
    sa.event.listen(preflight.engine.sync_engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    result = await inspect(preflight, graph(count=8))
    assert not result["valid"] and len(result["errors"]) == 8
    assert {row["node_id"] for row in result["errors"]} == {f"rag_{i}" for i in range(8)}
    assert all(
        row["target_id"] == "4" and row["state"] == "unavailable" and row["parameter_key"] == "knowledge"
        for row in result["errors"]
    )
    assert fixtures.snapshot(preflight.sync) == before
    assert not any(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements)
    assert not any("business_resource_reference" in statement for statement in statements)
    # Each distinct target is read as a batch, never once per referencing node.
    type_queries = [
        statement
        for statement in statements
        if statement.startswith("SELECT knowledge.id, knowledge.type") and "knowledge.id IN" in statement
    ]
    assert len(type_queries) == 2  # initial source issuance + mandatory revalidation


async def test_existing_target_passes_using_original_identity_and_visible_action(preflight):
    assert await inspect(preflight, graph((1,))) == {"valid": True, "errors": []}
    assert all(
        call.args[0] is preflight.user and call.kwargs["action"] == "edit"
        for call in preflight.authorize.await_args_list
    )
    assert all(call.args[0] is preflight.user for call in preflight.visible.await_args_list)


async def test_visibility_denial_is_unavailable_and_includes_all_repeated_slots(preflight):
    preflight.visible.side_effect = lambda identity, **kwargs: {}
    result = await inspect(preflight, graph((1, 4)))
    assert not result["valid"] and len(result["errors"]) == 6
    assert {row["state"] for row in result["errors"]} == {"unavailable"}


async def test_foreign_target_cannot_pass_or_disclose_its_name(preflight):
    result = await inspect(preflight, graph((2,)))
    assert not result["valid"]
    assert all(row["state"] in {"invalid_scope", "unavailable"} for row in result["errors"])
    assert "foreign-secret" not in str(result)


async def test_no_workflow_edit_permission_stops_before_target_lookup(preflight):
    preflight.authorize.side_effect = UnAuthorizedError()
    with pytest.raises(UnAuthorizedError):
        await inspect(preflight, graph())
    preflight.visible.assert_not_awaited()


async def test_foreign_workflow_is_not_discovered(preflight):
    with pytest.raises(NotFoundError):
        await inspect(preflight, graph(), workflow="other")
    preflight.authorize.assert_not_awaited()
    preflight.visible.assert_not_awaited()


async def test_target_deleted_after_preflight_is_still_rejected_at_execution(preflight):
    assert (await inspect(preflight, graph((1,))))["valid"]
    with preflight.sync.begin() as connection:
        connection.execute(sa.delete(Knowledge).where(Knowledge.id == 1))
    async with AsyncSession(preflight.engine) as session, session.begin():
        with pytest.raises(ResourceReferenceInvalidError) as error:
            await admission.prepare_preview(preflight.user, "wf", graph((1,)), reference_session=session)
        assert error.value.kwargs["reference_errors"][0]["target_id"] == "1"


async def test_qa_selection_uses_library_authorization_and_parameter_location(preflight):
    data = graph((3,), count=1)
    node = data["nodes"][0]["data"]
    node["type"] = "qa_retriever"
    node["group_params"] = [{"params": [{"key": "qa_knowledge_id", "value": [{"key": 3, "label": "qa"}]}]}]
    preflight.visible.side_effect = lambda identity, **kwargs: {}
    result = await inspect(preflight, data)
    assert result["errors"][0]["resource_type"] == "qa_knowledge"
    assert result["errors"][0]["parameter_key"] == "qa_knowledge_id"
    assert preflight.visible.await_args.kwargs["resource_type"] == "knowledge_library"


async def test_permission_service_failure_is_not_relabelled_as_missing(preflight):
    preflight.visible.side_effect = RuntimeError("authorization unavailable")
    with pytest.raises(RuntimeError, match="authorization unavailable"):
        await inspect(preflight, graph((1,)))
