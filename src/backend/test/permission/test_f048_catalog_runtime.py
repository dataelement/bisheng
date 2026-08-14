"""Production Catalog SQL/OpenFGA adapter contracts for F048."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import (
    PermissionPublishNotReadyError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    get_authorization_model_f048,
    required_relations_checksum,
)
from bisheng.permission.application import control_state as control_state_module
from bisheng.permission.application import sql_runtime as sql_runtime_module
from bisheng.permission.application.catalog_api import (
    F048CatalogApi,
    OpenFGACatalogProjector,
    SqlCatalogImpact,
    SqlCatalogState,
)
from bisheng.permission.application.control_state import (
    SqlPermissionControlState,
)
from bisheng.permission.application.sql_runtime import (
    SqlCatalogDecisionState,
)
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogProjectionTuple,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionModel,
    PermissionModelAction,
    ResourcePermissionMode,
)
from bisheng.permission.domain.schemas import (
    CatalogChangeRequest,
    CatalogChangeType,
    CatalogDraftRequest,
    CatalogPublishRequest,
    VerifiedPermissionTarget,
)
from bisheng.permission.domain.services.catalog_policy import (
    ACTION_RESOURCE_SCOPES,
    REGISTERED_ACTION_CODES,
    CatalogAction,
    derive_action_release,
)
from bisheng.permission.domain.services.catalog_service import CatalogService
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.model_policy import (
    CustomModelSelection,
    derive_permission_models,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

TABLE_NAMES = (
    "authorization_model_release",
    "permission_catalog_release",
    "permission_action",
    "permission_action_resource_scope",
    "permission_model",
    "permission_model_action",
    "permission_catalog_projection_tuple",
    "permission_projection_operation",
    "permission_projection_tuple",
    "permission_migration_run",
    "permission_migration_item",
    "permission_visible_source_projection",
    "permission_grant",
    "permission_grant_assignee",
    "resource_permission_mode",
)


class FakeCatalogMarker:
    def __init__(self) -> None:
        self.release_keys: list[str] = []

    async def arm_catalog(self, release_key: str) -> None:
        self.release_keys.append(release_key)


class InMemoryCatalogFGA:
    def __init__(self) -> None:
        self.store_id = "store"
        self.model_id = "model"
        self.tuples: set[tuple[str, str, str]] = set()
        self.write_calls: list[tuple[list[dict], list[dict]]] = []

    async def write_tuples(
        self,
        writes: list[dict] | None = None,
        deletes: list[dict] | None = None,
    ) -> None:
        writes = list(writes or ())
        deletes = list(deletes or ())
        self.write_calls.append((writes, deletes))
        for row in deletes:
            self.tuples.discard((row["user"], row["relation"], row["object"]))
        for row in writes:
            self.tuples.add((row["user"], row["relation"], row["object"]))

    async def read_tuples(
        self,
        user: str | None = None,
        relation: str | None = None,
        object: str | None = None,
        consistency: str | None = None,
    ) -> list[dict]:
        del consistency
        # An object ending in ":" is a type filter, matching every id of that
        # type — the same shape the real Read API accepts (and it requires a
        # user alongside it, which this fake asserts rather than silently allows).
        if object is not None and object.endswith(":") and not user:
            raise AssertionError("type-only object filter needs a user")
        return [
            {"user": item_user, "relation": item_relation, "object": item_object}
            for item_user, item_relation, item_object in sorted(self.tuples)
            if (user is None or item_user == user)
            and (relation is None or item_relation == relation)
            and (object is None or item_object == object or (object.endswith(":") and item_object.startswith(object)))
        ]

    @staticmethod
    def validate_business_mutation_size(operation_count: int) -> None:
        assert operation_count <= 90


@pytest.fixture
async def session_factory() -> AsyncIterator[SessionFactory]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = sa.MetaData()
    for name in TABLE_NAMES:
        cloned = SQLModel.metadata.tables[name].to_metadata(metadata)
        cloned.c.id.type = sa.Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    yield factory
    await engine.dispose()


def _actions(*, edit_level: int = 2) -> tuple[CatalogAction, ...]:
    levels = {
        "download": 1,
        "use": 1,
        "rename": 2,
        "edit": edit_level,
        "create_folder": 2,
        "upload_file": 2,
        "move": 2,
        "manage_permission": 3,
        "share": 3,
        "publish": 3,
        "unpublish": 3,
        "delete": 4,
    }
    return tuple(
        CatalogAction(
            code=code,
            name=code,
            level=levels[code],
            active=True,
            resource_types=ACTION_RESOURCE_SCOPES[code],
            sort_order=index,
        )
        for index, code in enumerate(REGISTERED_ACTION_CODES)
    )


async def _seed_current(
    session_factory: SessionFactory,
    fga: InMemoryCatalogFGA,
) -> PermissionCatalogRelease:
    action_release = derive_action_release(_actions())
    models = derive_permission_models(
        action_release,
        custom_models=(
            CustomModelSelection(
                model_key="collaborator",
                name="协作者",
                action_codes=("edit",),
            ),
        ),
    )
    model_payload = get_authorization_model_f048()
    async with session_factory() as session:
        async with session.begin():
            auth = AuthorizationModelRelease(
                environment="test",
                store_id=fga.store_id,
                model_version="f048-v1",
                model_id=fga.model_id,
                model_checksum=authorization_model_checksum(model_payload),
                required_relations_checksum=required_relations_checksum(model_payload),
                openfga_version="1.15.1",
                status="ACTIVE",
            )
            session.add(auth)
            await session.flush()
            release = PermissionCatalogRelease(
                release_key="catalog-v1",
                version=1,
                status="CURRENT",
                required_authorization_model_release_id=int(auth.id),
                draft_owner_id=7,
                idempotency_key="initial-catalog",
                checksum="a" * 64,
                published_at=sa.func.now(),
            )
            session.add(release)
            await session.flush()
            action_ids: dict[str, int] = {}
            for action in action_release.actions:
                row = PermissionAction(
                    catalog_release_id=int(release.id),
                    code=action.code,
                    name=action.name,
                    level=action.level,
                    active=action.active,
                    sort_order=action.sort_order,
                )
                session.add(row)
                await session.flush()
                action_ids[action.code] = int(row.id)
                session.add_all(
                    [
                        PermissionActionResourceScope(
                            action_id=int(row.id),
                            resource_type=resource_type,
                        )
                        for resource_type in action.resource_types
                    ]
                )
            for model in models.models:
                row = PermissionModel(
                    catalog_release_id=int(release.id),
                    model_key=model.model_key,
                    normalized_name=model.name.casefold(),
                    name=model.name,
                    kind=model.kind,
                    config_scope=model.config_scope,
                    derived_level=model.derived_level,
                    active=model.active,
                    allow_same_level=model.allow_same_level,
                )
                session.add(row)
                await session.flush()
                session.add_all(
                    [
                        PermissionModelAction(
                            model_id=int(row.id),
                            action_id=action_ids[action],
                        )
                        for action in model.selected_action_codes
                    ]
                )
    fga.tuples.add(("user:*", "active", "permission_catalog_release:catalog-v1"))
    return release


def _api(
    session_factory: SessionFactory,
    fga: InMemoryCatalogFGA,
    marker: FakeCatalogMarker,
) -> F048CatalogApi:
    state = SqlCatalogState(session_factory=session_factory)
    impact = SqlCatalogImpact(session_factory=session_factory)
    projector = OpenFGACatalogProjector(
        client=fga,
        marker=marker,
        session_factory=session_factory,
    )
    return F048CatalogApi(
        state=state,
        service=CatalogService(
            state=state,
            impact=impact,
            projector=projector,
        ),
    )


async def test_catalog_draft_can_bind_one_same_store_authorization_release(
    session_factory: SessionFactory,
) -> None:
    fga = InMemoryCatalogFGA()
    current = await _seed_current(session_factory, fga)
    async with session_factory() as session:
        async with session.begin():
            target = AuthorizationModelRelease(
                environment="test",
                store_id=fga.store_id,
                model_version="f048-v2",
                model_id="model-v2",
                predecessor_model_id=fga.model_id,
                model_checksum="a" * 64,
                required_relations_checksum="b" * 64,
                openfga_version="1.15.1",
                status="STAGED",
            )
            session.add(target)
            await session.flush()
            target_id = int(target.id)

    state = SqlCatalogState(session_factory=session_factory)
    reservation = await state.reserve_draft(
        base_release_id=int(current.id),
        operator_id=7,
        idempotency_key="authorization-model-upgrade",
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10),
    )
    await state.bind_draft_authorization_release(
        draft_id=reservation.release_id,
        authorization_release_id=target_id,
    )
    await state.bind_draft_authorization_release(
        draft_id=reservation.release_id,
        authorization_release_id=target_id,
    )

    async with session_factory() as session:
        draft = await session.get(PermissionCatalogRelease, reservation.release_id)
    assert draft is not None
    assert draft.required_authorization_model_release_id == target_id


async def test_decision_runtime_rejects_catalog_model_pin_drift(
    session_factory: SessionFactory,
    monkeypatch,
) -> None:
    fga = InMemoryCatalogFGA()
    await _seed_current(session_factory, fga)
    monkeypatch.setattr(
        sql_runtime_module,
        "get_async_db_session",
        session_factory,
    )

    await SqlCatalogDecisionState(
        expected_store_id="store",
        expected_model_id="model",
    ).ensure_runtime_ready()

    with pytest.raises(
        PermissionPublishNotReadyError,
        match="Store/model pin",
    ):
        await SqlCatalogDecisionState(
            expected_store_id="store",
            expected_model_id="stale-model",
        ).ensure_runtime_ready()


async def test_action_level_draft_rebuilds_every_standard_and_custom_model(
    session_factory: SessionFactory,
) -> None:
    fga = InMemoryCatalogFGA()
    marker = FakeCatalogMarker()
    current = await _seed_current(session_factory, fga)
    api = _api(session_factory, fga, marker)

    draft = await api.create_draft(
        request=CatalogDraftRequest(
            idempotency_key="raise-edit",
            base_release_id=int(current.id),
            changes=(
                CatalogChangeRequest(
                    type=CatalogChangeType.ASSIGN_ACTION_LEVEL,
                    action_code="edit",
                    level=3,
                ),
            ),
        ),
        operator_id=7,
    )

    assert draft["base_release_id"] == current.id
    async with session_factory() as session:
        draft_release = await session.get(
            PermissionCatalogRelease,
            draft["draft_id"],
        )
        model_rows = list(
            (
                await session.execute(
                    select(PermissionModel)
                    .where(PermissionModel.catalog_release_id == draft["draft_id"])
                    .order_by(PermissionModel.model_key)
                )
            ).scalars()
        )
        model_ids = [int(row.id) for row in model_rows]
        selected = list(
            (
                await session.execute(
                    select(
                        PermissionModel.model_key,
                        PermissionAction.code,
                    )
                    .join(
                        PermissionModelAction,
                        PermissionModelAction.model_id == PermissionModel.id,
                    )
                    .join(
                        PermissionAction,
                        PermissionAction.id == PermissionModelAction.action_id,
                    )
                    .where(col(PermissionModel.id).in_(model_ids))
                )
            ).all()
        )

    assert draft_release is not None
    assert draft_release.status == "DRAFT"
    by_model: dict[str, set[str]] = {}
    for model_key, action_code in selected:
        by_model.setdefault(str(model_key), set()).add(str(action_code))
    assert "edit" not in by_model["editor"]
    assert "edit" in by_model["manager"]
    assert "edit" in by_model["owner"]
    assert "edit" in by_model["collaborator"]
    collaborator = next(row for row in model_rows if row.model_key == "collaborator")
    assert collaborator.derived_level == 3


async def test_catalog_publish_allows_visibility_only_grant_after_action_level_change(
    session_factory: SessionFactory,
) -> None:
    fga = InMemoryCatalogFGA()
    marker = FakeCatalogMarker()
    current = await _seed_current(session_factory, fga)
    source = GrantSourceService().canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="42",
        source_type="DIRECT",
    )
    with bypass_tenant_filter():
        async with session_factory() as session:
            async with session.begin():
                grant = PermissionGrant(
                    tenant_id=1,
                    resource_type="folder",
                    resource_id="86206",
                    model_key="viewer",
                    state="ACTIVE",
                    projection_state="CURRENT",
                )
                session.add(grant)
                await session.flush()
                session.add(
                    PermissionGrantAssignee(
                        tenant_id=1,
                        grant_id=int(grant.id),
                        subject_type=source.subject_type,
                        subject_id=source.subject_id,
                        userset_relation=source.userset_relation,
                        include_children=source.include_children,
                        source_type=source.source_type,
                        source_ref=source.source_ref,
                        source_locator=source.source_locator,
                        source_fingerprint=source.source_fingerprint,
                        projected_subject=source.projected_subject,
                        protected=source.protected,
                        state="ACTIVE",
                    )
                )

    api = _api(session_factory, fga, marker)
    draft = await api.create_draft(
        request=CatalogDraftRequest(
            idempotency_key="raise-download",
            base_release_id=int(current.id),
            changes=(
                CatalogChangeRequest(
                    type=CatalogChangeType.ASSIGN_ACTION_LEVEL,
                    action_code="download",
                    level=2,
                ),
            ),
        ),
        operator_id=7,
    )

    impact = draft["impact"]
    assert impact["resource_count"] == 1
    assert impact["grant_count"] == 1
    assert impact["assignee_count"] == 1
    assert impact["expansion_count"] == 0
    assert impact["revocation_count"] == 1
    assert impact["blockers"] == []
    result = await api.publish_draft(
        draft_id=draft["draft_id"],
        request=CatalogPublishRequest(
            expected_current_release_id=int(current.id),
            idempotency_key="publish-raise-download",
            confirmed=True,
        ),
        operator_id=7,
    )

    assert result["status"] == "CURRENT"


async def test_catalog_publish_stages_complete_release_and_switches_once(
    session_factory: SessionFactory,
) -> None:
    fga = InMemoryCatalogFGA()
    marker = FakeCatalogMarker()
    current = await _seed_current(session_factory, fga)
    api = _api(session_factory, fga, marker)
    draft = await api.create_draft(
        request=CatalogDraftRequest(
            idempotency_key="disable-share",
            base_release_id=int(current.id),
            changes=(
                CatalogChangeRequest(
                    type=CatalogChangeType.SET_ACTION_ACTIVE,
                    action_code="share",
                    active=False,
                ),
            ),
        ),
        operator_id=7,
    )

    result = await api.publish_draft(
        draft_id=draft["draft_id"],
        request=CatalogPublishRequest(
            expected_current_release_id=int(current.id),
            idempotency_key="publish-disable-share",
            confirmed=True,
        ),
        operator_id=7,
    )

    assert result["status"] == "CURRENT"
    assert marker.release_keys == [result["release_key"]]
    pointer_calls = [call for call in fga.write_calls if call[0] and call[0][0]["relation"] == "active"]
    assert pointer_calls == [
        (
            [
                {
                    "user": "user:*",
                    "relation": "active",
                    "object": (f"permission_catalog_release:{result['release_key']}"),
                }
            ],
            [
                {
                    "user": "user:*",
                    "relation": "active",
                    "object": "permission_catalog_release:catalog-v1",
                }
            ],
        )
    ]
    async with session_factory() as session:
        releases = list(
            (
                await session.execute(select(PermissionCatalogRelease).order_by(PermissionCatalogRelease.version))
            ).scalars()
        )
        staged = list(
            (
                await session.execute(
                    select(PermissionCatalogProjectionTuple).where(
                        PermissionCatalogProjectionTuple.catalog_release_id == draft["draft_id"]
                    )
                )
            ).scalars()
        )
    assert [row.status for row in releases] == ["RETIRED", "CURRENT"]
    assert staged
    assert all(row.status == "WRITTEN" for row in staged)
    assert {row.relation for row in staged if row.action == "WRITE"} >= {
        "catalog",
        "release",
        "enabled_marker",
        "edit_marker",
    }


async def test_catalog_create_is_idempotent_and_current_shape_is_complete(
    session_factory: SessionFactory,
) -> None:
    fga = InMemoryCatalogFGA()
    marker = FakeCatalogMarker()
    current = await _seed_current(session_factory, fga)
    api = _api(session_factory, fga, marker)
    request = CatalogDraftRequest(
        idempotency_key="same-draft",
        base_release_id=int(current.id),
        changes=(
            CatalogChangeRequest(
                type=CatalogChangeType.SET_ALLOW_SAME_LEVEL,
                model_key="manager",
                allow_same_level=True,
            ),
        ),
    )

    first = await api.create_draft(request=request, operator_id=7)
    second = await api.create_draft(request=request, operator_id=7)
    payload = await api.get_current()

    assert second == first
    assert len(payload["actions"]) == len(REGISTERED_ACTION_CODES)
    assert {row["key"] for row in payload["models"]} == {
        "viewer",
        "editor",
        "manager",
        "owner",
        "collaborator",
    }
    with bypass_tenant_filter():
        async with session_factory() as session:
            count = (
                await session.execute(
                    select(sa.func.count(PermissionCatalogRelease.id)).where(PermissionCatalogRelease.status == "DRAFT")
                )
            ).scalar_one()
    assert count == 1


async def test_permission_roster_sql_cursor_reads_only_one_bounded_page(
    session_factory: SessionFactory,
    monkeypatch,
) -> None:
    source_service = GrantSourceService()
    sources = [
        source_service.canonicalize_source(
            source_id=source_id,
            subject_type="user",
            subject_id=str(source_id),
            source_type="DIRECT",
        )
        for source_id in (10, 20, 30)
    ]
    with bypass_tenant_filter():
        async with session_factory() as session:
            async with session.begin():
                grant = PermissionGrant(
                    tenant_id=5,
                    resource_type="workflow",
                    resource_id="wf-1",
                    model_key="viewer",
                    state="ACTIVE",
                    projection_state="CURRENT",
                )
                session.add(grant)
                await session.flush()
                session.add_all(
                    [
                        PermissionGrantAssignee(
                            id=source.source_id,
                            tenant_id=5,
                            grant_id=int(grant.id),
                            subject_type=source.subject_type,
                            subject_id=source.subject_id,
                            userset_relation=source.userset_relation,
                            include_children=source.include_children,
                            source_type=source.source_type,
                            source_ref=source.source_ref,
                            source_locator=source.source_locator,
                            source_fingerprint=source.source_fingerprint,
                            projected_subject=source.projected_subject,
                            protected=source.protected,
                            state="ACTIVE",
                        )
                        for source in sources
                    ]
                )
    monkeypatch.setattr(
        control_state_module,
        "get_async_db_session",
        session_factory,
    )
    state = SqlPermissionControlState()
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=5,
        resource_type="workflow",
        resource_id="wf-1",
        resource_version=1,
        context_version="workflow:wf-1:v1",
    )
    models = (
        GrantModelSnapshot(
            model_key="viewer",
            active=True,
            action_codes=("visible",),
            derived_level=1,
        ),
    )

    with bypass_tenant_filter():
        first, first_has_more = await state.load_source_page(
            target=target,
            mode="CUSTOM",
            models=models,
            after_id=0,
            limit=2,
        )
        second, second_has_more = await state.load_source_page(
            target=target,
            mode="CUSTOM",
            models=models,
            after_id=20,
            limit=2,
        )

    assert [row.source_id for row in first] == [10, 20]
    assert first_has_more is True
    assert [row.source_id for row in second] == [30]
    assert second_has_more is False


async def test_inherited_roster_uses_nearest_custom_ancestor(
    session_factory: SessionFactory,
    monkeypatch,
) -> None:
    source_service = GrantSourceService()
    root_source = source_service.canonicalize_source(
        source_id=10,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    middle_creator = source_service.canonicalize_source(
        source_id=20,
        subject_type="user",
        subject_id="200",
        source_type="CREATOR",
        source_ref="folder:97333",
        protected=True,
    )
    leaf_creator = source_service.canonicalize_source(
        source_id=30,
        subject_type="user",
        subject_id="300",
        source_type="CREATOR",
        source_ref="folder:12345",
        protected=True,
    )
    with bypass_tenant_filter():
        async with session_factory() as session:
            async with session.begin():
                session.add_all(
                    [
                        ResourcePermissionMode(
                            tenant_id=5,
                            resource_type="knowledge_space",
                            resource_id="3733",
                            mode="CUSTOM",
                            projection_state="CURRENT",
                        ),
                        ResourcePermissionMode(
                            tenant_id=5,
                            resource_type="folder",
                            resource_id="97333",
                            mode="INHERIT",
                            parent_type="knowledge_space",
                            parent_id="3733",
                            projection_state="CURRENT",
                        ),
                        ResourcePermissionMode(
                            tenant_id=5,
                            resource_type="folder",
                            resource_id="12345",
                            mode="INHERIT",
                            parent_type="folder",
                            parent_id="97333",
                            projection_state="CURRENT",
                        ),
                    ]
                )
                for resource_type, resource_id, source in (
                    ("knowledge_space", "3733", root_source),
                    ("folder", "97333", middle_creator),
                    ("folder", "12345", leaf_creator),
                ):
                    grant = PermissionGrant(
                        tenant_id=5,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        model_key="viewer",
                        state="ACTIVE",
                        projection_state="CURRENT",
                    )
                    session.add(grant)
                    await session.flush()
                    session.add(
                        PermissionGrantAssignee(
                            id=source.source_id,
                            tenant_id=5,
                            grant_id=int(grant.id),
                            subject_type=source.subject_type,
                            subject_id=source.subject_id,
                            userset_relation=source.userset_relation,
                            include_children=source.include_children,
                            source_type=source.source_type,
                            source_ref=source.source_ref,
                            source_locator=source.source_locator,
                            source_fingerprint=source.source_fingerprint,
                            projected_subject=source.projected_subject,
                            protected=source.protected,
                            state="ACTIVE",
                        )
                    )
    monkeypatch.setattr(
        control_state_module,
        "get_async_db_session",
        session_factory,
    )
    state = SqlPermissionControlState()
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=5,
        resource_type="folder",
        resource_id="12345",
        resource_version=1,
        context_version="folder:12345:v1",
        parent_type="folder",
        parent_id="97333",
    )
    models = (
        GrantModelSnapshot(
            model_key="viewer",
            active=True,
            action_codes=("visible",),
            derived_level=1,
        ),
    )

    with bypass_tenant_filter():
        inherited = await state.inherited_grant_set(
            target=target,
            models=models,
        )
        page, has_more = await state.load_source_page(
            target=target,
            mode="INHERIT",
            models=models,
            after_id=0,
            limit=10,
        )

    assert inherited is not None
    assert (inherited.resource_type, inherited.resource_id) == (
        "knowledge_space",
        "3733",
    )
    assert [source.subject_id for grant in inherited.grants for source in grant.sources] == ["100"]
    assert [(row.source_id, row.scope, row.inherited_from) for row in page] == [
        (10, "INHERITED", "knowledge_space:3733"),
        (30, "LOCAL", None),
    ]
    assert has_more is False


async def test_draft_folds_every_change_in_the_batch(
    session_factory: SessionFactory,
) -> None:
    """A batch must publish all of its edits, not just the last one.

    The board used to open a fresh draft off the CURRENT release per edit, so a
    session of three tweaks produced three one-change drafts and publishing any
    of them silently dropped the other two.
    """

    fga = InMemoryCatalogFGA()
    marker = FakeCatalogMarker()
    current = await _seed_current(session_factory, fga)
    api = _api(session_factory, fga, marker)

    draft = await api.create_draft(
        request=CatalogDraftRequest(
            idempotency_key="batch-of-three",
            base_release_id=int(current.id),
            changes=(
                CatalogChangeRequest(
                    type=CatalogChangeType.ASSIGN_ACTION_LEVEL,
                    action_code="edit",
                    level=3,
                ),
                CatalogChangeRequest(
                    type=CatalogChangeType.ASSIGN_ACTION_LEVEL,
                    action_code="rename",
                    level=4,
                ),
                CatalogChangeRequest(
                    type=CatalogChangeType.SET_ACTION_ACTIVE,
                    action_code="unpublish",
                    active=False,
                ),
            ),
        ),
        operator_id=7,
    )

    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(PermissionAction).where(PermissionAction.catalog_release_id == draft["draft_id"])
                )
            ).scalars()
        )
    by_code = {row.code: row for row in rows}
    assert by_code["edit"].level == 3
    assert by_code["rename"].level == 4
    assert by_code["unpublish"].active is False
    # Untouched actions keep the base release's values.
    assert by_code["delete"].level == 4


async def test_a_later_change_in_the_batch_wins_over_an_earlier_one(
    session_factory: SessionFactory,
) -> None:
    fga = InMemoryCatalogFGA()
    marker = FakeCatalogMarker()
    current = await _seed_current(session_factory, fga)
    api = _api(session_factory, fga, marker)

    draft = await api.create_draft(
        request=CatalogDraftRequest(
            idempotency_key="batch-overwrite",
            base_release_id=int(current.id),
            changes=(
                CatalogChangeRequest(
                    type=CatalogChangeType.ASSIGN_ACTION_LEVEL,
                    action_code="edit",
                    level=3,
                ),
                CatalogChangeRequest(
                    type=CatalogChangeType.ASSIGN_ACTION_LEVEL,
                    action_code="edit",
                    level=4,
                ),
            ),
        ),
        operator_id=7,
    )

    async with session_factory() as session:
        row = (
            await session.execute(
                select(PermissionAction).where(
                    PermissionAction.catalog_release_id == draft["draft_id"],
                    PermissionAction.code == "edit",
                )
            )
        ).scalar_one()
    assert row.level == 4


async def test_deactivate_and_delete_in_one_batch(
    session_factory: SessionFactory,
) -> None:
    """Removing a model must not need two publications.

    Deletability was judged against the base release, so a batch that deactivates
    a model and then deletes it was refused for being active — forcing
    deactivate, publish, delete, publish for one removal.
    """

    fga = InMemoryCatalogFGA()
    marker = FakeCatalogMarker()
    current = await _seed_current(session_factory, fga)
    api = _api(session_factory, fga, marker)

    draft = await api.create_draft(
        request=CatalogDraftRequest(
            idempotency_key="deactivate-then-delete",
            base_release_id=int(current.id),
            changes=(
                CatalogChangeRequest(
                    type=CatalogChangeType.SET_MODEL_ACTIVE,
                    model_key="collaborator",
                    active=False,
                ),
                CatalogChangeRequest(
                    type=CatalogChangeType.DELETE_MODEL,
                    model_key="collaborator",
                ),
            ),
        ),
        operator_id=7,
    )

    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(PermissionModel).where(PermissionModel.catalog_release_id == draft["draft_id"])
                )
            ).scalars()
        )
    assert "collaborator" not in {row.model_key for row in rows}


async def test_active_model_can_be_deleted_when_reference_audit_is_zero(
    session_factory: SessionFactory,
) -> None:
    """Active controls future assignment, not whether a zero-ref model can delete."""

    fga = InMemoryCatalogFGA()
    marker = FakeCatalogMarker()
    current = await _seed_current(session_factory, fga)
    api = _api(session_factory, fga, marker)

    draft = await api.create_draft(
        request=CatalogDraftRequest(
            idempotency_key="delete-while-active",
            base_release_id=int(current.id),
            changes=(
                CatalogChangeRequest(
                    type=CatalogChangeType.DELETE_MODEL,
                    model_key="collaborator",
                ),
            ),
        ),
        operator_id=7,
    )
    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(PermissionModel).where(PermissionModel.catalog_release_id == draft["draft_id"])
                )
            ).scalars()
        )
    assert "collaborator" not in {row.model_key for row in rows}
