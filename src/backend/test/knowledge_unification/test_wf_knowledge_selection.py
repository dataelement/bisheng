"""New knowledge bindings require visibility without blocking old-slot repair.

覆盖 AC: AC-37, AC-68, AC-87, AC-88. Workflow/Knowledge/REF persistence and
Knowledge target Owner are real; only the sole permission transport is a test
boundary. It retains the authenticated actor and credential data scope.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel import Session

from bisheng.api.services import flow as flow_service
from bisheng.api.v1.schemas import FlowVersionCreate
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.database import tenant_filter
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.permission.application import business_authorization as authorization
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_PERSONAL
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from bisheng.workflow.domain.repositories.workflow_version_repository import WorkflowVersionRepository
from test.knowledge_unification import test_wf_create as create_fixtures
from test.knowledge_unification import test_wf_save as save_fixtures
from test.knowledge_unification.test_wf_extract import graph, node, selection

store = create_fixtures.store
tenant = create_fixtures.tenant
bindings = create_fixtures.bindings
saved = save_fixtures.saved
rows = create_fixtures.rows


@pytest.fixture
async def knowledge(saved, monkeypatch):
    Knowledge.__table__.create(saved.sync_engine)
    names = tenant_filter._tenant_aware_tables | {
        "knowledge",
        "flow",
        "flowversion",
        "business_reference_set",
        "business_resource_reference",
        "resource_reference_tombstone",
    }
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    tenant_filter.register_tenant_filter_events()
    with Session(saved.sync_engine) as session:
        session.add(Knowledge(id=31, tenant_id=101, user_id=22, name="selected", type=3))
        session.add(Knowledge(id=32, tenant_id=101, user_id=11, name="replacement", type=3))
        session.commit()
    model_table = sa.Table("wf_test_target", sa.MetaData(), autoload_with=saved.sync_engine)
    knowledge_owner = KnowledgeReferenceTargetOwner()
    verifier = ReferenceTargetVerifier(
        {
            "model": create_fixtures.SqlTargetOwner(model_table),
            "knowledge_space": knowledge_owner,
            "knowledge_file": knowledge_owner,
        }
    )
    saved.repository = ReferenceRepository(verifier=verifier)
    saved.runtime = ReferenceBindingRuntime(saved.repository, verifier)
    monkeypatch.setattr(flow_service, "get_reference_binding_runtime", AsyncMock(return_value=saved.runtime))
    saved.hidden = set()
    saved.permission_calls = []
    saved.actor = PermissionActor(tenant_id=101, user_id=11)

    async def resolve(*, resource_type, resource_id, actor, action):
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=101,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=1,
            context_version="knowledge-selection",
        )

    async def check(actor, target, action):
        assert actor is saved.actor
        if target.resource_type == "workflow":
            return True
        assert target.resource_type in {"knowledge_library", "knowledge_space"}
        assert action == "visible"
        return int(target.resource_id) not in saved.hidden and not (
            actor.data_scope == DATA_SCOPE_PERSONAL and target.resource_id == "31"
        )

    async def gate(user, **kwargs):
        assert user is saved.user
        saved.permission_calls.append((kwargs["resource_type"], str(kwargs["resource_id"]), kwargs["action"]))
        return await authorization.require_business_action(user, **kwargs)

    monkeypatch.setattr(authorization, "resolve_permission_actor", AsyncMock(side_effect=lambda user: saved.actor))
    monkeypatch.setattr(
        authorization, "get_f048_resource_registry", AsyncMock(return_value=SimpleNamespace(resolve=resolve))
    )
    monkeypatch.setattr(authorization, "get_f048_runtime", AsyncMock(return_value=SimpleNamespace(check_action=check)))
    monkeypatch.setattr(flow_service, "require_business_action", gate)
    return saved


def selected(*node_ids, target=31):
    # Intentionally keep the historical UI label; the actual SQL Knowledge.type
    # decides which permission resource kind is checked after target locking.
    return graph(*(node(node_id, "rag", knowledge=selection(target, kind="knowledge")) for node_id in node_ids))


def state(context):
    return {
        table: rows(context, table)
        for table in ("flow", "flowversion", "business_reference_set", "business_resource_reference")
    }


def knowledge_calls(context):
    return [call for call in context.permission_calls if call[0].startswith("knowledge_")]


@pytest.mark.parametrize("kind", [0, 1, 3])
@pytest.mark.parametrize("operation", ["create_root", "create_version", "save"])
async def test_new_hidden_knowledge_binding_is_denied_and_rolls_back_every_business_row(knowledge, kind, operation):
    async with knowledge.session_factory() as session, session.begin():
        row = await session.get(Knowledge, 31)
        row.type = kind
    knowledge.hidden.add(31)
    before = state(knowledge)
    with pytest.raises(UnAuthorizedError):
        if operation == "create_root":
            await create_fixtures.create(knowledge, name="hidden-copy", saved_data=selected("r"))
        elif operation == "create_version":
            await flow_service.FlowService.create_new_version(
                knowledge.user, "wf", FlowVersionCreate(name="hidden-copy", data=selected("r"), original_version_id=1)
            )
        else:
            await save_fixtures.save(knowledge, 2, selected("r"))
    assert state(knowledge) == before
    assert knowledge_calls(knowledge) == [("knowledge_space" if kind == 3 else "knowledge_library", "31", "visible")]


@pytest.mark.parametrize("kind", [0, 1, 3])
async def test_visible_selection_uses_the_current_real_knowledge_kind(knowledge, kind):
    async with knowledge.session_factory() as session, session.begin():
        row = await session.get(Knowledge, 31)
        row.type = kind
    assert (await save_fixtures.save(knowledge, 2, selected("r"))).status_code == 200
    assert knowledge_calls(knowledge) == [("knowledge_space" if kind == 3 else "knowledge_library", "31", "visible")]


async def test_retaining_and_removing_same_hidden_slot_do_not_add_new_visibility_gate(knowledge):
    await save_fixtures.save(knowledge, 2, selected("r"))
    knowledge.hidden.add(31)
    knowledge.permission_calls.clear()
    assert (await save_fixtures.save(knowledge, 2, selected("r"), name="keep hidden")).status_code == 200
    assert (await save_fixtures.save(knowledge, 2, graph())).status_code == 200
    assert knowledge_calls(knowledge) == []
    assert not rows(knowledge, "business_resource_reference")


async def test_new_slot_to_same_hidden_target_is_still_new_binding(knowledge):
    await save_fixtures.save(knowledge, 2, selected("r"))
    knowledge.hidden.add(31)
    before = state(knowledge)
    with pytest.raises(UnAuthorizedError):
        await save_fixtures.save(knowledge, 2, selected("r", "new-slot"))
    assert state(knowledge) == before


async def test_new_version_cannot_borrow_older_version_selection_permission(knowledge):
    await save_fixtures.save(knowledge, 2, selected("r"))
    knowledge.hidden.add(31)
    before = state(knowledge)
    with pytest.raises(UnAuthorizedError):
        await flow_service.FlowService.create_new_version(
            knowledge.user, "wf", FlowVersionCreate(name="copy", data=selected("r"), original_version_id=2)
        )
    assert state(knowledge) == before


async def test_partial_repair_checks_only_new_target_and_keeps_other_hidden_slot(knowledge):
    await save_fixtures.save(knowledge, 2, selected("a", "b"))
    knowledge.hidden.add(31)
    knowledge.permission_calls.clear()
    next_data = graph(
        node("a", "rag", knowledge=selection(32)),
        node("b", "rag", knowledge=selection(31)),
    )
    assert (await save_fixtures.save(knowledge, 2, next_data)).status_code == 200
    assert knowledge_calls(knowledge) == [("knowledge_space", "32", "visible")]
    assert {(row["slot_key"], row["target_id"]) for row in rows(knowledge, "business_resource_reference")} == {
        ("node:a.knowledge", "32"),
        ("node:b.knowledge", "31"),
    }


async def test_original_invalid_slot_can_still_be_retained_and_removed_without_visibility_gate(knowledge):
    await save_fixtures.save(knowledge, 2, selected("r"))
    async with knowledge.session_factory() as session, session.begin():
        await session.delete(await session.get(Knowledge, 31))
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_type="knowledge_space",
                target_id="31",
                target_tenant_id=101,
                operation_id="delete-knowledge-31",
                operation_type="force_delete",
                stage="deleted",
                actor_type="user",
                actor_id="11",
            )
        )
    knowledge.hidden.add(31)
    knowledge.permission_calls.clear()
    assert (await save_fixtures.save(knowledge, 2, selected("r"))).status_code == 200
    assert (await save_fixtures.save(knowledge, 2, graph())).status_code == 200
    assert knowledge_calls(knowledge) == []


async def test_narrowed_admin_actor_is_not_replaced_while_selecting_visible_knowledge(knowledge):
    knowledge.actor = PermissionActor(tenant_id=101, user_id=11, super_admin=True, data_scope=DATA_SCOPE_PERSONAL)
    before = state(knowledge)
    with pytest.raises(UnAuthorizedError):
        await save_fixtures.save(knowledge, 2, selected("r"))
    assert state(knowledge) == before
    assert knowledge_calls(knowledge) == [("knowledge_space", "31", "visible")]


async def test_empty_draft_has_no_knowledge_selection_gate(knowledge):
    knowledge.hidden.update({31, 32})
    assert (await create_fixtures.create(knowledge, name="blank", saved_data={})).status_code == 200
    assert knowledge_calls(knowledge) == []


async def test_restore_historical_hidden_selection_is_a_new_binding(knowledge):
    from bisheng.database.models.flow_version import FlowVersion

    async with knowledge.session_factory() as session, session.begin():
        version = await session.get(FlowVersion, 3)
        version.data = selected("historical")
    knowledge.hidden.add(31)
    before = state(knowledge)
    with pytest.raises(UnAuthorizedError):
        await save_fixtures.save(knowledge, 3, None)
    assert state(knowledge) == before


async def test_real_kind_lookup_uses_same_locked_transaction_and_current_sql(knowledge, monkeypatch):
    lock_root = WorkflowVersionRepository.alock_root
    original_lookup = getattr(WorkflowVersionRepository, "aget_knowledge_resource_type", None)
    checked = []

    async def mark_root(session, *args, **kwargs):
        root = await lock_root(session, *args, **kwargs)
        session.sync_session.info["wf_root_locked"] = True
        return root

    async def current_lookup(session, knowledge_id):
        assert session.sync_session.info.get("wf_root_locked") is True
        scalar = session.scalar

        async def capture(statement, *args, **kwargs):
            assert getattr(statement, "_for_update_arg", None) is not None
            checked.append(knowledge_id)
            return await scalar(statement, *args, **kwargs)

        monkeypatch.setattr(session, "scalar", capture)
        try:
            return await original_lookup(session, knowledge_id)
        finally:
            monkeypatch.setattr(session, "scalar", scalar)

    monkeypatch.setattr(WorkflowVersionRepository, "alock_root", mark_root)
    monkeypatch.setattr(WorkflowVersionRepository, "aget_knowledge_resource_type", current_lookup, raising=False)
    assert (await save_fixtures.save(knowledge, 2, selected("r"))).status_code == 200
    assert checked == [31]
