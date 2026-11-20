"""Frozen, read-only retention policy; never grants migration write authority."""

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.knowledge.application.unification_inventory_codec import decode_inventory_page
from bisheng.knowledge.domain.repositories.unification_identity_retention_repository import (
    FIELDS,
    UnificationIdentityRetentionRepository,
    blocked,
)
from bisheng.permission.application.sql_runtime import stable_grant_key
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)


def metadata(value):
    return {key: value[key] for key in FIELDS if key in value}


async def validate(session, *, expected=None, repository=None):
    """None captures a new Run; {} preserves an old Run's strict contract."""
    repository = repository or PermissionMigrationSnapshotRepository()
    try:
        await repository.avalidate_global_integrity(session)
    except PermissionMigrationBlockedError as error:
        if error.kwargs.get("reason") != "f118_snapshot_global_original_orphan" or expected == {}:
            raise
        snapshot = await UnificationIdentityRetentionRepository(
            fact_view=getattr(repository, "fact_view", None)
        ).acapture(session)
        if expected is not None and snapshot.metadata() != expected:
            blocked("frozen_facts_changed")
        await repository.avalidate_global_integrity(session, retained_tenant_ids=snapshot.tenant_ids)
        return snapshot
    if expected:
        blocked("frozen_facts_removed")
    return None


async def load_metadata(store, frozen):
    content = await store.aload_canonical(frozen.plan_ref, run_id=frozen.run_id, kind="plan")
    page = decode_inventory_page(
        content, run_id=frozen.run_id, section="manifest", scope="global", tenant_id=None, page_index=0, kind="plan"
    )
    rows = [row.data for row in page.records if row.record_type == "run"]
    if len(rows) != 1:
        blocked("metadata_required")
    return metadata(rows[0])


def verify_tuple_plan(plan, objects):
    if not objects:
        return

    def selected(rows):
        return {key for key in rows if key[2] in objects or key[0].partition("#")[0] in objects}

    before = selected(plan.before)
    if before != selected(plan.staged) or before != selected(plan.after):
        blocked("retained_graph_changed")


def protected_objects(snapshot):
    if snapshot is None:
        return frozenset()
    return snapshot.objects | frozenset(
        "permission_grant:" + stable_grant_key(tenant_id=tenant, resource_type=kind, resource_id=ident, model_key=model)
        for tenant, kind, ident, model in snapshot.grant_identities
    )
