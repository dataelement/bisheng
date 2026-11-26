"""F118 historical preparation and its native read-only after facts.

The unified operational CLI owns external clients and the complete preflight
artifact lifetime. This application never imports executable scripts and never
runs a repair transaction merely to roll it back for a preview.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace

from bisheng.knowledge.application.unification_progress import report_progress
from bisheng.knowledge.domain.repositories import unification_history_repository as history
from bisheng.knowledge.domain.repositories.unification_history_view_repository import build_history_view


@dataclass
class HistoryPreview:
    history_plan: dict
    history_sha256: str
    replay_plan: dict
    semantic_manifest: dict
    diagnostics: list
    read_ports: object
    reader_factory: object
    fact_view: object
    private_backup_path: str | None = None

    async def aclose(self):
        self.fact_view.close()


def _ports(view):
    from bisheng.knowledge.application.unification_preflight import UnificationPreflight
    from bisheng.knowledge.application.unification_reference_state import OriginalReferenceState
    from bisheng.knowledge.domain.repositories.unification_control_repository import UnificationControlRepository
    from bisheng.knowledge.domain.repositories.unification_inventory_repository import UnificationInventoryRepository
    from bisheng.knowledge.domain.repositories.unification_resource_repository import UnificationResourceRepository
    from bisheng.knowledge.domain.repositories.unification_space_membership_repository import (
        UnificationSpaceMembershipRepository,
    )
    from bisheng.knowledge.domain.repositories.unification_target_repository import KnowledgeMigrationTargetRepository
    from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
        PermissionMigrationSnapshotRepository,
    )
    from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository

    resources = UnificationResourceRepository(fact_view=view)
    inventory = UnificationInventoryRepository(fact_view=view)
    permissions = PermissionMigrationSnapshotRepository(fact_view=view)
    controls = UnificationControlRepository()
    memberships = UnificationSpaceMembershipRepository(fact_view=view)
    return SimpleNamespace(
        resources=resources,
        inventory=inventory,
        permissions=permissions,
        controls=controls,
        memberships=memberships,
        knowledge_targets=KnowledgeMigrationTargetRepository(fact_view=view),
        original_state=OriginalReferenceState(repository=ReferenceBackfillRepository(fact_view=view)),
        preflight=UnificationPreflight(
            resources=resources,
            inventory=inventory,
            permissions=permissions,
            controls=controls,
            memberships=memberships,
        ),
        fact_view=view,
    )


async def apreview_history(
    runtime,
    *,
    run_id,
    writer_contract_version,
    environment,
    artifacts,
    planned_at,
    operator_id=None,
    replay_plan=None,
    expected_semantics=None,
):
    client = getattr(runtime, "history_client", None) or getattr(runtime, "client", None)
    if client is None:
        history.blocked("read_pinned_history_client_required")
    if replay_plan is not None:
        if expected_semantics is None or any(
            expected_semantics.get(key) != value
            for key, value in {
                "run_id": run_id,
                "writer_contract_version": writer_contract_version,
                "environment": environment,
                "planned_at": planned_at.isoformat(),
            }.items()
        ):
            history.blocked("replay_preview_binding_changed")
        plan, view = await history.replay_preview_view(runtime, replay_plan, expected_semantics, operator_id)
        result = _after_ports(runtime, view)
        return HistoryPreview(
            plan,
            replay_plan["history_sha256"],
            replay_plan,
            expected_semantics,
            [],
            result.read_ports,
            result.reader_factory,
            view,
        )
    if expected_semantics is not None:
        history.blocked("replay_preview_material_required")
    plan = await history.capture(runtime.sessions, client, progress=report_progress)
    backup = history.save_private_history_backup(plan, artifacts.root / "private") if artifacts is not None else None
    diagnostics = [{key: item[key] for key in ("table", "id", "reason") if key in item} for item in plan["blocked"]]
    if plan.get("business", {}).get("physical") and getattr(runtime, "history_physical", None) is None:
        diagnostics.append({"reason": "history_physical_reader_required", "not_evaluated": True})
    view = await build_history_view(plan, sessions=runtime.sessions, client=client, operator_id=operator_id or 0)
    try:
        semantic = view.manifest()
        semantic.update(
            run_id=run_id,
            writer_contract_version=writer_contract_version,
            environment=environment,
            planned_at=planned_at.isoformat(),
            history_sha256=history.checksum(plan),
            operator_binding="apply_time" if operator_id is None else "fixed",
            operator_id=operator_id,
        )
        factory = getattr(runtime, "sharing_reader_factory", None)

        @asynccontextmanager
        async def readers(catalog):
            if factory is None:
                history.blocked("native_sharing_reader_required")
            async with factory(catalog) as reader:
                reader.history_view = view
                yield reader

        replay = history.build_replay_plan(plan)
        if not replay.get("executable"):
            diagnostics.append({"reason": replay["reason"], "not_evaluated": True})
        return HistoryPreview(
            plan, history.checksum(plan), replay, semantic, diagnostics, _ports(view), readers, view, backup
        )
    except BaseException:
        view.close()
        raise


async def apply_history(
    runtime,
    *,
    history_plan=None,
    replay_plan=None,
    operator_id,
    transaction_guard=None,
    external_guard=None,
    **_identity,
):
    """Execute the original intent; shared replay is materialized by its Owner."""
    client = getattr(runtime, "history_client", None) or getattr(runtime, "client", None)
    if history_plan is None:
        if replay_plan is None:
            history.blocked("original_history_plan_required")
        history_plan = await history.restore_replay_plan(replay_plan, sessions=runtime.sessions)
    native = getattr(runtime, "history_runtime", None) or getattr(runtime, "permission_runtime", None)
    if native is None:
        history.blocked("native_history_runtime_required")
    from bisheng.permission.application.migration_history import maintenance_guard

    tenants = getattr(external_guard, "tenant_ids", ())
    if transaction_guard is not None and not tenants:
        history.blocked("global_history_attempt_scope_required")
    with maintenance_guard(
        transaction_guard=transaction_guard,
        external_guard=external_guard,
        global_tenants=tenants,
        identity={"history_sha256": history.history_plan_identity(history_plan)},
    ):
        return await history.apply(
            history_plan,
            sessions=runtime.sessions,
            client=client,
            runtime=native,
            operator_id=operator_id,
            physical=getattr(runtime, "history_physical", None),
            progress=report_progress,
        )


async def assert_history_after(runtime, replay_plan, expected_semantic_manifest, operator_id):
    return await history.assert_history_after_facts(runtime, replay_plan, expected_semantic_manifest, operator_id)


@dataclass
class HistoryAfterPorts:
    read_ports: object
    reader_factory: object
    fact_view: object

    async def aclose(self):
        self.fact_view.close()


def _after_ports(runtime, view):
    factory = getattr(runtime, "sharing_reader_factory", None)

    @asynccontextmanager
    async def readers(catalog):
        if factory is None:
            history.blocked("native_sharing_reader_required")
        async with factory(catalog) as reader:
            reader.history_view = view
            yield reader

    return HistoryAfterPorts(_ports(view), readers, view)


async def verified_history_after_ports(runtime, replay_plan, expected_semantics, after_receipt, operator_id):
    view = await history.normalized_after_view(runtime, replay_plan, expected_semantics, after_receipt, operator_id)
    return _after_ports(runtime, view)
