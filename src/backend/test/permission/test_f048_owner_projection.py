"""F048 protected creator, multi-owner, and notification contracts."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.permission.application.control_state import (
    RuntimeCatalogSnapshot,
    RuntimeModelSnapshot,
)
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.owner_service import (
    F048OwnerProjectionService,
    OwnerProjectionContext,
)
from bisheng.permission.domain.services.resource_permission_notification_service import (
    F048PermissionNotificationAdapter,
    PermissionGrantNotificationItem,
)


class _Projection:
    def __init__(self, error: Exception | None = None) -> None:
        self.plans = []
        self.prepared = []
        self.abandoned = []
        self.error = error

    async def prepare(self, plan):
        self.prepared.append(plan)
        return SimpleNamespace(id=77, status="PREPARED")

    async def abandon_prepared(self, plan, error):
        self.abandoned.append((plan, error))

    async def execute(self, plan):
        self.plans.append(plan)
        if self.error:
            raise self.error
        return {"status": "FINALIZED", "target_version": 1}


class _State:
    def __init__(self) -> None:
        self.prepared = []
        self.finalized = []
        self.compensations = []

    async def prepare(
        self,
        context,
        grant,
        source,
        *,
        operation_id: int,
    ):
        self.prepared.append((context, grant, source, operation_id))

    async def finalize(self, context, grant, outcome):
        self.finalized.append((context, grant, outcome))

    async def mark_compensation_required(self, context, error):
        self.compensations.append((context, error))


class _Subjects:
    def __init__(self) -> None:
        self.calls = []

    async def resolve_user_ids(
        self,
        subject_type,
        subject_id,
        include_children,
    ):
        self.calls.append((subject_type, subject_id, include_children))
        if subject_type == "department":
            return frozenset({20, 21})
        return frozenset({int(subject_id)})


def _target(resource_id: str = "wf-1") -> VerifiedPermissionTarget:
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=5,
        resource_type="workflow",
        resource_id=resource_id,
        resource_version=0,
        context_version=f"workflow-{resource_id}-v0",
    )


def _owner_grant(resource_id: str = "wf-1") -> GrantSnapshot:
    return GrantSnapshot(
        grant_id=f"{resource_id}-owner",
        tenant_id=5,
        resource_type="workflow",
        resource_id=resource_id,
        model=GrantModelSnapshot(
            model_key="owner",
            active=True,
            action_codes=(
                "manage_permission",
                "edit",
                "delete",
                "use",
            ),
            derived_level=4,
            allow_same_level=True,
        ),
        active=False,
        sources=(),
    )


def _context(
    *,
    resource_id: str = "wf-1",
    grant: GrantSnapshot | None = None,
    system_owned: bool = False,
    system_predicate: bool = False,
) -> OwnerProjectionContext:
    return OwnerProjectionContext(
        target=_target(resource_id),
        owner_grant=grant,
        source_id=91,
        owner_user_id=None if system_owned else 7,
        system_owned=system_owned,
        system_predicate=system_predicate,
        store_id="store-live",
        model_id="model-f048",
        operator_id=7,
        idempotency_key=f"create:{resource_id}",
    )


@pytest.mark.asyncio
async def test_creation_adds_one_protected_creator_without_replacing_owners() -> None:
    sources = GrantSourceService()
    ordinary = sources.canonicalize_source(
        source_id=90,
        subject_type="user",
        subject_id="8",
        source_type="DIRECT",
    )
    seeded = sources.add_source(_owner_grant(), ordinary).grant
    projection = _Projection()
    state = _State()
    service = F048OwnerProjectionService(
        source_service=sources,
        projection=projection,
        state=state,
    )

    result = await service.project_created(
        _context(grant=seeded),
    )

    assert len(result.grant.sources) == 2
    assert sum(source.protected for source in result.grant.sources) == 1
    assert {source.projected_subject for source in result.grant.sources} == {"user:7", "user:8"}
    assert len(state.prepared) == len(state.finalized) == 1
    assert any(delta.relation == "protected_assignee" for delta in projection.plans[0].deltas)


@pytest.mark.asyncio
async def test_copy_regenerates_creator_for_the_new_resource() -> None:
    service = F048OwnerProjectionService(
        source_service=GrantSourceService(),
        projection=_Projection(),
        state=_State(),
    )

    first = await service.project_created(
        _context(grant=_owner_grant()),
    )
    copied = await service.project_created(
        _context(
            resource_id="wf-copy",
            grant=_owner_grant("wf-copy"),
        ),
    )

    assert first.grant.sources[0].source_ref == "workflow:wf-1"
    assert copied.grant.sources[0].source_ref == "workflow:wf-copy"
    assert first.grant.grant_id != copied.grant.grant_id


@pytest.mark.asyncio
async def test_custom_copy_projects_ordinary_sources_and_new_creator_atomically() -> None:
    sources = GrantSourceService()
    ordinary = sources.canonicalize_source(
        source_id=90,
        subject_type="user",
        subject_id="8",
        source_type="DIRECT",
    )
    editor = sources.add_source(
        GrantSnapshot(
            grant_id="wf-copy-editor",
            tenant_id=5,
            resource_type="workflow",
            resource_id="wf-copy",
            model=GrantModelSnapshot(
                model_key="editor",
                active=True,
                action_codes=("edit",),
                derived_level=2,
            ),
            active=False,
            sources=(),
        ),
        ordinary,
    )
    owner = _owner_grant("wf-copy")
    projection = _Projection()
    service = F048OwnerProjectionService(
        source_service=sources,
        projection=projection,
        state=_State(),
    )

    result = await service.project_created(
        replace(
            _context(
                resource_id="wf-copy",
                grant=owner,
            ),
            permission_mode="CUSTOM",
            operation_type="RESOURCE_COPY",
            copy_grants=(editor.grant, owner),
            copy_deltas=editor.deltas,
        )
    )

    plan = projection.plans[0]
    assert plan.operation_type == "RESOURCE_COPY"
    assert any(row.relation == "custom_mode" for row in plan.deltas)
    assert {(row.user, row.relation) for row in plan.deltas} >= {
        ("user:8", "ordinary_assignee"),
        ("user:7", "protected_assignee"),
    }
    assert result.grant is not None
    assert result.grant.sources[0].protected is True


@pytest.mark.asyncio
async def test_runtime_custom_copy_excludes_old_protected_creator() -> None:
    source_service = GrantSourceService()
    editor_model = GrantModelSnapshot(
        model_key="editor",
        active=True,
        action_codes=("edit",),
        derived_level=2,
    )
    owner_model = GrantModelSnapshot(
        model_key="owner",
        active=True,
        action_codes=("manage_permission", "delete"),
        derived_level=4,
    )
    ordinary = source_service.canonicalize_source(
        source_id=20,
        subject_type="user",
        subject_id="8",
        source_type="DIRECT",
    )
    old_creator = source_service.canonicalize_source(
        source_id=21,
        subject_type="user",
        subject_id="9",
        source_type="CREATOR",
        source_ref="workflow:wf-source",
        protected=True,
    )
    source_grants = (
        source_service.add_source(
            GrantSnapshot(
                grant_id="source-editor",
                tenant_id=5,
                resource_type="workflow",
                resource_id="wf-source",
                model=editor_model,
                active=False,
                sources=(),
            ),
            ordinary,
        ).grant,
        source_service.add_source(
            GrantSnapshot(
                grant_id="source-owner",
                tenant_id=5,
                resource_type="workflow",
                resource_id="wf-source",
                model=owner_model,
                active=False,
                sources=(),
            ),
            old_creator,
        ).grant,
    )
    source_target = VerifiedPermissionTarget.from_business_service(
        tenant_id=5,
        resource_type="workflow",
        resource_id="wf-source",
        resource_version=3,
        context_version="source-v3",
    )
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=5,
        resource_type="workflow",
        resource_id="wf-copy",
        resource_version=0,
        context_version="copy-v0",
    )
    catalog = RuntimeCatalogSnapshot(
        release_id=12,
        release_key="catalog-v12",
        version=12,
        checksum="c" * 64,
        store_id="store",
        model_id="model",
        model_checksum="m" * 64,
        models=(
            RuntimeModelSnapshot(
                snapshot=editor_model,
                name="Editor",
                kind="STANDARD",
                version=12,
            ),
            RuntimeModelSnapshot(
                snapshot=owner_model,
                name="Owner",
                kind="STANDARD",
                version=12,
            ),
        ),
    )

    class State:
        async def mode_for_target(self, target):
            del target
            return SimpleNamespace(
                version=3,
                parent_type=None,
                parent_id=None,
                projection_state="CURRENT",
                mode="CUSTOM",
            )

        async def current_catalog(self):
            return catalog

        async def load_grants(self, **kwargs):
            del kwargs
            return source_grants

    class Owner:
        def __init__(self):
            self.context = None

        async def project_created(self, context):
            self.context = context
            return context

    owner = Owner()
    runtime = F048PermissionRuntime(
        client=SimpleNamespace(store_id="store", model_id="model"),
        state=State(),
        marker=object(),
        decision=object(),
        projection=object(),
        sources=source_service,
        owner=owner,
        grants=object(),
        modes=object(),
        explain=object(),
    )

    await runtime.project_copy(
        actor=SimpleNamespace(user_id=7),
        source=source_target,
        target=target,
        owner_user_id=7,
        mode="CUSTOM",
    )

    copied_sources = [source for grant in owner.context.copy_grants for source in grant.sources]
    assert [source.subject_id for source in copied_sources] == ["8"]
    assert all(not source.protected for source in copied_sources)
    assert owner.context.owner_user_id == 7
    assert owner.context.operation_type == "RESOURCE_COPY"


@pytest.mark.asyncio
async def test_projection_failure_records_durable_compensation() -> None:
    state = _State()
    service = F048OwnerProjectionService(
        source_service=GrantSourceService(),
        projection=_Projection(RuntimeError("fga unavailable")),
        state=state,
    )

    with pytest.raises(RuntimeError, match="fga unavailable"):
        await service.project_created(
            _context(grant=_owner_grant()),
        )

    assert len(state.prepared) == 1
    assert state.finalized == []
    assert len(state.compensations) == 1


@pytest.mark.asyncio
async def test_system_owned_requires_code_allowlist_and_business_predicate() -> None:
    projection = _Projection()
    service = F048OwnerProjectionService(
        source_service=GrantSourceService(),
        projection=projection,
        state=_State(),
    )
    valid = replace(
        _context(
            grant=None,
            system_owned=True,
            system_predicate=True,
        ),
        system_action_codes=("visible", "use"),
        target=VerifiedPermissionTarget.from_business_service(
            tenant_id=5,
            resource_type="tool",
            resource_id="preset-1",
            resource_version=0,
            context_version="tool-preset-1-v0",
        ),
    )

    result = await service.project_created(valid)
    assert result.grant is None
    assert any(delta.relation == "system_visible_marker" for delta in projection.plans[0].deltas)
    assert any(delta.relation == "system_use_marker" for delta in projection.plans[0].deltas)

    for invalid in (
        replace(valid, system_predicate=False),
        replace(
            valid,
            target=VerifiedPermissionTarget.from_business_service(
                tenant_id=5,
                resource_type="knowledge_file",
                resource_id="builtin",
                resource_version=0,
                context_version="file-builtin-v0",
            ),
        ),
    ):
        with pytest.raises(PermissionInvalidResourceError):
            await service.project_created(invalid)


@pytest.mark.asyncio
async def test_notifications_derive_recipients_from_source_and_model_actions() -> None:
    subjects = _Subjects()
    adapter = F048PermissionNotificationAdapter(subjects=subjects)
    changes = (
        PermissionGrantNotificationItem(
            operation="ADD",
            subject_type="department",
            subject_id="17",
            include_children=True,
            source_type="DEPARTMENT",
            model_key="manager",
            action_codes=("edit", "manage_permission"),
        ),
        PermissionGrantNotificationItem(
            operation="REMOVE",
            subject_type="user",
            subject_id="9",
            include_children=False,
            source_type="DIRECT",
            model_key="viewer",
            action_codes=("use",),
        ),
    )

    context = await adapter.build_context(
        resource_type="workflow",
        resource_id="wf-1",
        changes=changes,
    )

    assert context.grant_user_ids == {20, 21}
    assert context.read_revoke_user_ids == {9}
    assert subjects.calls == [
        ("department", "17", True),
        ("user", "9", False),
    ]
    assert not hasattr(changes[0], "relation")
