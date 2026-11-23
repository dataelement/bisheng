"""History preview runs native after facts without SQL/FGA mutation."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlmodel import select

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.permission.domain.models import ResourcePermissionMode
from test.knowledge_unification import test_history_upgrade_defaults as original

resource_native, native, history = original.resource_native, original.native, original.history


async def test_preview_projects_initialization_and_purge_without_native_writes(history):
    from bisheng.knowledge.application.unification_history import apreview_history

    await original.seed(history)
    before = history.fga.writes
    runtime = SimpleNamespace(sessions=history.sessions, history_client=history.fga)
    preview = await apreview_history(
        runtime,
        run_id="history-view",
        writer_contract_version="f118-v1",
        environment="test",
        artifacts=None,
        planned_at=datetime(2026, 11, 20, 10),
        operator_id=7,
    )
    try:
        assert not preview.diagnostics
        assert preview.history_sha256
        with tenant_execution_scope(101):
            async with history.sessions() as session, session.begin():
                modes = await preview.read_ports.permissions.alist_resource_modes(session, limit=200)
                after = next(mode for mode in modes if mode.resource_id == "91")
                assert (after.mode, after.version, after.projection_state) == ("INHERIT", 1, "CURRENT")
                assert not any(mode.resource_id == "999" for mode in modes)
                actual = (
                    await session.exec(select(ResourcePermissionMode).where(ResourcePermissionMode.resource_id == "91"))
                ).first()
                assert actual is None
        assert history.fga.writes == before
        assert ("user:*", "permission_enabled", "knowledge_file:91") in preview.fact_view.graph_writes
    finally:
        await preview.aclose()


def test_projection_effect_uses_final_multiphase_tuple_state():
    from bisheng.permission.application.migration_history import terminal_graph_effect
    from bisheng.permission.domain.services.projection_plan import ProjectionTupleDelta

    key = ("user:*", "permission_enabled", "knowledge_file:1")
    writes, deletes = terminal_graph_effect(
        (
            ProjectionTupleDelta("STAGE", 0, "DELETE", *key),
            ProjectionTupleDelta("COMMIT", 1, "WRITE", *key),
        )
    )
    assert writes == frozenset({key}) and not deletes


def test_dirty_after_is_checked_even_when_before_has_no_violation():
    from bisheng.knowledge.domain.repositories.unification_history_view_repository import HistoryFactView

    view = HistoryFactView()
    try:
        view.replace(
            "knowledgefile",
            {"id": 5, "tenant_id": 101, "knowledge_id": 10, "file_type": 1},
            {"id": 5, "tenant_id": 999, "knowledge_id": 10, "file_type": 1},
        )
        problems = view.validate_file_after({10: {"id": 10, "tenant_id": 101}})
        assert problems and problems[0]["reason"] == "file_parent_invalid"
    finally:
        view.close()


async def test_shared_replay_executes_original_intent_and_maps_real_generated_ids(history):
    from bisheng.knowledge.application.unification_history import apply_history, apreview_history, assert_history_after
    from bisheng.permission.domain.models import PermissionProjectionOperation

    await original.seed(history)
    runtime = SimpleNamespace(sessions=history.sessions, history_client=history.fga, history_runtime=history.runtime)
    preview = await apreview_history(
        runtime,
        run_id="mapped-history",
        writer_contract_version="f118-v1",
        environment="test",
        artifacts=None,
        planned_at=datetime(2026, 11, 20, 10),
    )
    try:
        before = preview.history_sha256
        # An unrelated durable audit row consumes a SQL-generated identity.
        # The history operation's actual id must not equal its preview id.
        async with original.script.global_session(history.sessions) as session:
            session.add(
                PermissionProjectionOperation(
                    id=8000,
                    tenant_id=101,
                    idempotency_key="unrelated-audit",
                    request_checksum="0" * 64,
                    operation_type="RESOURCE_DELETE",
                    scope_type="resource",
                    scope_key="tool:8000",
                    expected_version=0,
                    target_version=1,
                    store_id="store",
                    model_id="model",
                    status="FINALIZED",
                    before_checksum="0" * 64,
                    after_checksum="0" * 64,
                    operator_id=7,
                )
            )
        result = await apply_history(runtime, replay_plan=preview.replay_plan, operator_id=7)
        assert result["preparation_complete"]
        receipt = await assert_history_after(runtime, preview.replay_plan, preview.semantic_manifest, 7)
        assert receipt["complete"] and receipt["history_sha256"] == before
        assert any(
            row["table"] == "permission_projection_operation" and row["actual_id"] != row["preview_id"]
            for row in receipt["logical_id_map"]
        )
        from bisheng.knowledge.application.unification_history import verified_history_after_ports

        normalized = await verified_history_after_ports(
            runtime, preview.replay_plan, preview.semantic_manifest, receipt, 7
        )
        try:
            with tenant_execution_scope(101):
                async with history.sessions() as session, session.begin():
                    wanted = await preview.read_ports.permissions.alist_resource_modes(session, limit=200)
                    actual = await normalized.read_ports.permissions.alist_resource_modes(session, limit=200)
                    assert actual == wanted
        finally:
            await normalized.aclose()
        # Replaying consumes the same original journal; no new graph writes.
        writes = history.fga.writes
        await apply_history(runtime, replay_plan=preview.replay_plan, operator_id=7)
        assert history.fga.writes == writes
    finally:
        await preview.aclose()


async def test_bound_replay_preview_reuses_original_after_when_before_and_after_mix(history):
    from bisheng.knowledge.application.unification_history import apply_history, apreview_history

    await original.seed(history)
    runtime = SimpleNamespace(sessions=history.sessions, history_client=history.fga, history_runtime=history.runtime)
    arguments = {
        "run_id": "recover-preview",
        "writer_contract_version": "f118-v1",
        "environment": "test",
        "artifacts": None,
        "planned_at": datetime(2026, 11, 20, 10),
    }
    preview = await apreview_history(runtime, **arguments)
    try:
        for execute in (False, True):
            if execute:
                await apply_history(runtime, replay_plan=preview.replay_plan, operator_id=7)
            writes = history.fga.writes
            recovered = await apreview_history(
                runtime,
                **arguments,
                replay_plan=preview.replay_plan,
                expected_semantics=preview.semantic_manifest,
                operator_id=7,
            )
            try:
                assert recovered.semantic_manifest == preview.semantic_manifest
                assert recovered.history_sha256 == preview.history_sha256
                with tenant_execution_scope(101):
                    async with history.sessions() as session, session.begin():
                        expected = await preview.read_ports.permissions.alist_resource_modes(session, limit=200)
                        actual = await recovered.read_ports.permissions.alist_resource_modes(session, limit=200)
                        assert actual == expected
                assert history.fga.writes == writes
            finally:
                await recovered.aclose()
    finally:
        await preview.aclose()


async def test_shared_replay_rejects_changed_action_without_writing(history):
    from copy import deepcopy

    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.knowledge.application.unification_history import apply_history, apreview_history

    await original.seed(history)
    runtime = SimpleNamespace(sessions=history.sessions, history_client=history.fga, history_runtime=history.runtime)
    preview = await apreview_history(
        runtime,
        run_id="tampered-history",
        writer_contract_version="f118-v1",
        environment="test",
        artifacts=None,
        planned_at=datetime(2026, 11, 20, 10),
        operator_id=7,
    )
    try:
        replay = deepcopy(preview.replay_plan)
        replay["plan"]["initializations"][0]["file"]["history_row"]["identity"]["id"] = 999
        before = history.fga.writes
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await apply_history(runtime, replay_plan=replay, operator_id=7)
        assert history.fga.writes == before
    finally:
        await preview.aclose()


@pytest.mark.parametrize("kind", ["delete_closure", "builtin_recovery", "empty_root"])
async def test_native_after_matches_preview_for_every_permission_repair_kind(history, kind, monkeypatch):
    from bisheng.knowledge.application.unification_history import apply_history, apreview_history, assert_history_after
    from test.knowledge_unification import test_history_delete_closure as closure
    from test.knowledge_unification import test_history_pending_projection as pending

    if kind == "delete_closure":
        await closure.seed(history)
    elif kind == "builtin_recovery":
        await original.seed(history)
        await pending.seed_builtin(history)
    else:
        from bisheng.knowledge.domain.models.knowledge import Knowledge

        await original.seed(history)
        await history.db.insert(Knowledge, [closure.original.resources.resource(15000, model=None)])
    runtime = SimpleNamespace(sessions=history.sessions, history_client=history.fga, history_runtime=history.runtime)
    before = history.fga.writes
    preview = await apreview_history(
        runtime,
        run_id="all-known-" + kind,
        writer_contract_version="f118-v1",
        environment="test",
        artifacts=None,
        planned_at=datetime(2026, 11, 20, 10),
    )
    try:
        assert not preview.diagnostics
        assert history.fga.writes == before
        from bisheng.knowledge.application import unification_history_materials as material
        from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
        from bisheng.knowledge.application.unification_upgrade_materials import canonical
        from test.knowledge_unification.test_history_material_pages import Storage

        monkeypatch.setattr(material, "_LIMIT", 100)
        store = UnificationArtifactStore(Storage())
        restored = []
        for page_kind, body in (("history_replay", preview.replay_plan), ("verification", preview.semantic_manifest)):
            ref = await material.aput_history_record(
                store, run_id=preview.semantic_manifest["run_id"], kind=page_kind, record=body
            )
            loaded = await material.aload_history_record(
                store, ref, run_id=preview.semantic_manifest["run_id"], kind=page_kind
            )
            assert canonical(loaded) == canonical(body)
            restored.append(loaded)
        await apply_history(runtime, replay_plan=restored[0], operator_id=7)
        assert (await assert_history_after(runtime, restored[0], restored[1], 7))["complete"]
    finally:
        await preview.aclose()


async def test_unknown_native_commit_does_not_become_a_replay_preview(history):
    from sqlalchemy import update

    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.knowledge.application.unification_history import apply_history, apreview_history
    from bisheng.permission.domain.models import PermissionProjectionOperation

    await original.seed(history)
    runtime = SimpleNamespace(sessions=history.sessions, history_client=history.fga, history_runtime=history.runtime)
    arguments = {
        "run_id": "unknown-preview",
        "writer_contract_version": "f118-v1",
        "environment": "test",
        "artifacts": None,
        "planned_at": datetime(2026, 11, 20, 10),
    }
    preview = await apreview_history(runtime, **arguments)
    try:
        await apply_history(runtime, replay_plan=preview.replay_plan, operator_id=7)
        async with original.script.global_session(history.sessions) as session:
            await session.execute(
                update(PermissionProjectionOperation)
                .where(PermissionProjectionOperation.idempotency_key.startswith("history-initialize:"))
                .values(status="COMMIT_UNKNOWN")
            )
        writes = history.fga.writes
        with pytest.raises(KnowledgeOperationPlanConflictError) as error:
            await apreview_history(
                runtime,
                **arguments,
                replay_plan=preview.replay_plan,
                expected_semantics=preview.semantic_manifest,
                operator_id=7,
            )
        assert error.value.kwargs["reason"] == "history_prepare_replay_preview_commit_unknown"
        assert history.fga.writes == writes
    finally:
        await preview.aclose()


async def test_preview_identity_is_stable_for_reordered_fga_and_private_backup(history, tmp_path):
    import json
    import stat

    from bisheng.knowledge.application.unification_history import apreview_history

    await original.seed(history)
    scans = 0

    async def reordered(*, consistency):
        nonlocal scans
        assert consistency == "HIGHER_CONSISTENCY"
        scans += 1
        for user, relation, obj in sorted(history.fga.present, reverse=bool(scans % 2)):
            yield {"user": user, "relation": relation, "object": obj}

    history.fga.iter_tuples = reordered
    runtime = SimpleNamespace(sessions=history.sessions, history_client=history.fga)
    arguments = {
        "run_id": "stable-preview",
        "writer_contract_version": "f118-v1",
        "environment": "test",
        "artifacts": SimpleNamespace(root=tmp_path),
        "planned_at": datetime(2026, 11, 20, 10),
    }
    first, second = await apreview_history(runtime, **arguments), await apreview_history(runtime, **arguments)
    try:
        assert first.history_sha256 == second.history_sha256
        assert first.semantic_manifest == second.semantic_manifest
        assert first.replay_plan == second.replay_plan
        from pathlib import Path

        backup = Path(first.private_backup_path)
        assert backup == Path(second.private_backup_path)
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600
        assert json.loads(backup.read_text())["plan"] == first.history_plan
    finally:
        await first.aclose()
        await second.aclose()


@pytest.mark.parametrize("removed", ["grant", "mode"])
async def test_inverse_permission_edges_cannot_hide_behind_original_sql_join(history, removed):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.knowledge.domain.repositories.unification_history_view_repository import HistoryFactView
    from bisheng.permission.domain.models import PermissionGrant, PermissionGrantAssignee

    async with original.script.global_session(history.sessions) as session:
        grant = PermissionGrant(
            id=3000,
            tenant_id=101,
            resource_type="knowledge_file",
            resource_id="30",
            model_key="readonly",
            state="ACTIVE",
            projection_state="CURRENT",
        )
        child = PermissionGrantAssignee(
            id=3001,
            tenant_id=101,
            grant_id=3000,
            subject_type="user",
            subject_id="7",
            source_type="manual",
            source_ref="user:7",
            source_locator="manual:7",
            source_fingerprint="a" * 64,
            projected_subject="user:7",
            state="ACTIVE",
        )
        session.add_all([grant, child])
        await session.flush()
        await session.refresh(grant)
        before = (
            grant.model_dump() if removed == "grant" else (await session.get(ResourcePermissionMode, 30)).model_dump()
        )
    view = HistoryFactView()
    try:
        view.replace("permission_grant" if removed == "grant" else "resource_permission_mode", before, None)
        with tenant_execution_scope(101):
            async with history.sessions() as session, session.begin():
                with pytest.raises(KnowledgeOperationPlanConflictError) as error:
                    await view.validate_permission_global(session)
        assert error.value.kwargs["reason"] in {
            "history_view_dirty_assignee_parent_invalid",
            "history_view_dirty_removed_scope_has_remaining_mirror",
        }
    finally:
        view.close()


async def test_corrected_workflow_owner_passes_global_after_tenant_probe(history):
    from bisheng.database.models.assistant import AssistantLink
    from bisheng.database.models.flow import Flow
    from bisheng.database.models.flow_version import FlowVersion
    from bisheng.knowledge.domain.repositories.unification_history_view_repository import HistoryFactView
    from bisheng.knowledge.domain.repositories.unification_inventory_repository import UnificationInventoryRepository

    async with history.db.engine.begin() as connection:
        await connection.run_sync(lambda conn: AssistantLink.__table__.create(conn, checkfirst=True))
    async with original.script.global_session(history.sessions) as session:
        session.add(Flow(id="dirty-owner", tenant_id=101, name="workflow", user_id=7, flow_type=10))
        version = FlowVersion(id=3301, tenant_id=999, flow_id="dirty-owner", name="version", flow_type=10)
        session.add(version)
        await session.flush()
        await session.refresh(version)
        before = version.model_dump()
    view = HistoryFactView()
    try:
        view.replace("flowversion", before, {**before, "tenant_id": 101})
        with tenant_execution_scope(101):
            async with history.sessions() as session, session.begin():
                repository = UnificationInventoryRepository(fact_view=view)
                await repository.avalidate_history_prepared(session)
                await repository.avalidate_registered_source_tenants(session)
                page = await repository.alist_workflow_versions(session)
                assert next(row for row in page.items if row.id == 3301).tenant_id == 101
    finally:
        view.close()
