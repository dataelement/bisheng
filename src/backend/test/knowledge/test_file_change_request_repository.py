from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeFootprint,
    KnowledgeSpaceFileChangeLockScope,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import (
    KnowledgeSpaceUploadStage,
    KnowledgeSpaceUploadStageState,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
    FootprintEntry,
    KnowledgeSpaceFileChangeFootprintRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    APPROVER_RECONCILABLE_STATUSES,
    RESOURCE_LOCK_BLOCKING_STATUSES,
    KnowledgeSpaceFileChangeRequestRepository,
)


@pytest_asyncio.fixture
async def repository_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Knowledge.__table__,
        KnowledgeSpaceFileChangeRequest.__table__,
        KnowledgeSpaceFileChangeFootprint.__table__,
        KnowledgeSpaceUploadStage.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def reset_tenant_context():
    token = current_tenant_id.set(None)
    yield
    current_tenant_id.reset(token)


async def _insert_space(session: AsyncSession, *, tenant_id: int, space_id: int) -> None:
    session.add(
        Knowledge(
            id=space_id,
            tenant_id=tenant_id,
            user_id=1,
            name=f"space-{space_id}",
            type=KnowledgeTypeEnum.SPACE.value,
            auth_type=AuthTypeEnum.PUBLIC,
        )
    )


async def _insert_request(
    session: AsyncSession,
    *,
    tenant_id: int,
    space_id: int,
    instance_id: int,
    status: str,
    resource_type: str = KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
    resource_id: int = 501,
    path_root: str | None = None,
    lock_scope: str = KnowledgeSpaceFileChangeLockScope.EXACT,
) -> int:
    execution_state = (
        KnowledgeSpaceFileChangeExecutionState.APPLIED
        if status == "executed"
        else KnowledgeSpaceFileChangeExecutionState.NOT_STARTED
    )
    request = KnowledgeSpaceFileChangeRequest(
        tenant_id=tenant_id,
        space_id=space_id,
        action=KnowledgeSpaceFileChangeAction.DELETE,
        resource_type=resource_type,
        resource_id=resource_id,
        applicant_user_id=9,
        business_key=f"knowledge-space-change:{instance_id}",
        request_fingerprint=f"fingerprint-{instance_id}",
        approval_instance_id=instance_id,
        execution_state=execution_state,
    )
    session.add(request)
    await session.flush()
    assert request.id is not None
    session.add(
        KnowledgeSpaceFileChangeFootprint(
            tenant_id=tenant_id,
            request_id=request.id,
            space_id=space_id,
            resource_type=resource_type,
            resource_id=resource_id,
            path_root=path_root,
            lock_scope=lock_scope,
        )
    )
    await session.flush()
    return request.id


async def test_request_repository_always_scopes_reads_and_updates_by_tenant(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            own_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1001,
                status="pending",
            )
            foreign_id = await _insert_request(
                session,
                tenant_id=18,
                space_id=101,
                instance_id=1002,
                status="pending",
            )

        repository = KnowledgeSpaceFileChangeRequestRepository(session)
        assert (await repository.get_by_id(tenant_id=17, request_id=own_id)) is not None
        assert (await repository.get_by_id(tenant_id=17, request_id=foreign_id)) is None
        assert (
            await repository.attach_approval_instance(
                tenant_id=17,
                request_id=foreign_id,
                approval_instance_id=2002,
            )
            is False
        )

        foreign = (
            await session.exec(
                select(KnowledgeSpaceFileChangeRequest).where(
                    KnowledgeSpaceFileChangeRequest.tenant_id == 18,
                    KnowledgeSpaceFileChangeRequest.id == foreign_id,
                )
            )
        ).one()
        assert foreign.approval_instance_id == 1002


async def test_request_view_keeps_non_upload_request_without_optional_stage(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            stage = KnowledgeSpaceUploadStage(
                tenant_id=17,
                space_id=101,
                uploader_user_id=9,
                upload_id="upload-101",
                object_name="staged/upload-101",
                file_name="upload.pdf",
                file_size=128,
                content_hash="upload-hash",
                state=KnowledgeSpaceUploadStageState.ATTACHED,
                expire_at=datetime(2030, 1, 1),
            )
            session.add(stage)
            await session.flush()
            assert stage.id is not None

            upload = KnowledgeSpaceFileChangeRequest(
                tenant_id=17,
                space_id=101,
                action=KnowledgeSpaceFileChangeAction.UPLOAD,
                resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
                applicant_user_id=9,
                business_key="upload-request",
                request_fingerprint="upload-fingerprint",
                upload_stage_id=stage.id,
                file_name="upload.pdf",
            )
            rename = KnowledgeSpaceFileChangeRequest(
                tenant_id=17,
                space_id=101,
                action=KnowledgeSpaceFileChangeAction.RENAME,
                resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                resource_id=501,
                applicant_user_id=9,
                business_key="rename-request",
                request_fingerprint="rename-fingerprint",
                action_snapshot={"resource_name": "before.pdf"},
            )
            session.add(upload)
            session.add(rename)
            await session.flush()
            assert upload.id is not None
            assert rename.id is not None

        repository = KnowledgeSpaceFileChangeRequestRepository(session)
        upload_view = await repository.get_request_view(
            tenant_id=17,
            space_id=101,
            request_id=upload.id,
        )
        rename_view = await repository.get_request_view(
            tenant_id=17,
            space_id=101,
            request_id=rename.id,
        )

    assert upload_view is not None
    assert upload_view.upload_id == "upload-101"
    assert upload_view.stage_state == KnowledgeSpaceUploadStageState.ATTACHED
    assert rename_view is not None
    assert rename_view.upload_id is None
    assert rename_view.stage_state is None
    assert rename_view.resource_name == "before.pdf"


async def test_active_resource_matches_use_only_authoritative_root_footprint(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            request_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1003,
                status="pending",
                resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                resource_id=501,
                path_root="/501/",
                lock_scope=KnowledgeSpaceFileChangeLockScope.SUBTREE,
            )
            session.add(
                KnowledgeSpaceFileChangeFootprint(
                    tenant_id=17,
                    request_id=request_id,
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                    resource_id=900,
                    path_root="/900/",
                    lock_scope=KnowledgeSpaceFileChangeLockScope.DESTINATION,
                )
            )

        repository = KnowledgeSpaceFileChangeFootprintRepository(session)
        matches = await repository.list_active_resource_matches(
            tenant_id=17,
            space_id=101,
            resources=[
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                    resource_id=502,
                    path_root="/501/502/",
                ),
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                    resource_id=900,
                    path_root="/900/",
                ),
            ],
        )

    assert [(row.request.id, row.path_root, row.lock_scope) for row in matches] == [
        (request_id, "/501/", KnowledgeSpaceFileChangeLockScope.SUBTREE)
    ]


async def test_lock_spaces_uses_unique_ascending_ids_and_explicit_tenant(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            await _insert_space(session, tenant_id=17, space_id=301)
            await _insert_space(session, tenant_id=17, space_id=102)
            await _insert_space(session, tenant_id=18, space_id=205)

        repository = KnowledgeSpaceFileChangeRequestRepository(session)
        locked = await repository.lock_spaces(tenant_id=17, space_ids=[301, 102, 301, 205])

        assert [space.id for space in locked] == [102, 301]


async def test_resource_conflict_joins_only_same_tenant_active_instances(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            active_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1101,
                status="approved",
            )
            await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1102,
                status="executed",
            )
            await _insert_request(
                session,
                tenant_id=18,
                space_id=101,
                instance_id=1103,
                status="pending",
            )
            orphan = KnowledgeSpaceFileChangeRequest(
                tenant_id=17,
                space_id=101,
                action=KnowledgeSpaceFileChangeAction.DELETE,
                resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                resource_id=501,
                applicant_user_id=9,
                business_key="orphan-request",
                request_fingerprint="orphan-fingerprint",
            )
            session.add(orphan)
            await session.flush()
            assert orphan.id is not None
            session.add(
                KnowledgeSpaceFileChangeFootprint(
                    tenant_id=17,
                    request_id=orphan.id,
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                    resource_id=501,
                    lock_scope=KnowledgeSpaceFileChangeLockScope.EXACT,
                )
            )

        repository = KnowledgeSpaceFileChangeFootprintRepository(session)
        conflicts = await repository.find_blocking_request_ids(
            tenant_id=17,
            footprints=[
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                    resource_id=501,
                )
            ],
        )

    assert conflicts == [active_id]


async def test_root_subtree_conflicts_with_every_descendant(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            request_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1151,
                status="pending",
                resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                resource_id=1,
                path_root="/",
                lock_scope=KnowledgeSpaceFileChangeLockScope.SUBTREE,
            )

        repository = KnowledgeSpaceFileChangeFootprintRepository(session)
        conflicts = await repository.find_blocking_request_ids(
            tenant_id=17,
            footprints=[
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                    resource_id=99,
                    path_root="/10/20/",
                    lock_scope=KnowledgeSpaceFileChangeLockScope.SUBTREE,
                )
            ],
        )

        assert conflicts == [request_id]


async def test_version_sibling_expansion_conflicts_through_shared_version_footprint(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            request_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1201,
                status="pending",
                resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE_VERSION,
                resource_id=7002,
            )

        repository = KnowledgeSpaceFileChangeFootprintRepository(session)
        conflicts = await repository.find_blocking_request_ids(
            tenant_id=17,
            footprints=[
                # The caller expands a version operation to every sibling in the document.
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE_VERSION,
                    resource_id=7001,
                ),
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE_VERSION,
                    resource_id=7002,
                ),
            ],
        )

        assert conflicts == [request_id]


@pytest.mark.parametrize(
    ("existing_path", "existing_scope", "candidate_path", "candidate_scope"),
    [
        (
            "/10/",
            KnowledgeSpaceFileChangeLockScope.SUBTREE,
            "/10/20/",
            KnowledgeSpaceFileChangeLockScope.SUBTREE,
        ),
        (
            "/10/20/",
            KnowledgeSpaceFileChangeLockScope.SUBTREE,
            "/10/",
            KnowledgeSpaceFileChangeLockScope.SUBTREE,
        ),
        (
            "/30/40/",
            KnowledgeSpaceFileChangeLockScope.SUBTREE,
            "/30/40/50/",
            KnowledgeSpaceFileChangeLockScope.DESTINATION,
        ),
        (
            "/30/40/50/",
            KnowledgeSpaceFileChangeLockScope.DESTINATION,
            "/30/40/",
            KnowledgeSpaceFileChangeLockScope.SUBTREE,
        ),
    ],
)
async def test_path_conflict_is_bidirectional_for_parent_child_and_destination_ancestors(
    repository_engine,
    existing_path: str,
    existing_scope: str,
    candidate_path: str,
    candidate_scope: str,
):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            request_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1301,
                status="pending",
                resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                resource_id=10,
                path_root=existing_path,
                lock_scope=existing_scope,
            )

        repository = KnowledgeSpaceFileChangeFootprintRepository(session)
        conflicts = await repository.find_blocking_request_ids(
            tenant_id=17,
            footprints=[
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                    resource_id=99,
                    path_root=candidate_path,
                    lock_scope=candidate_scope,
                )
            ],
        )

        assert conflicts == [request_id]


async def test_exact_sibling_resources_with_same_parent_marker_do_not_conflict(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1351,
                status="pending",
                resource_id=501,
                path_root="/10/",
                lock_scope=KnowledgeSpaceFileChangeLockScope.EXACT,
            )

        repository = KnowledgeSpaceFileChangeFootprintRepository(session)
        conflicts = await repository.find_blocking_request_ids(
            tenant_id=17,
            footprints=[
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                    resource_id=502,
                    path_root="/10/",
                    lock_scope=KnowledgeSpaceFileChangeLockScope.EXACT,
                )
            ],
        )

        assert conflicts == []


async def test_independent_subtrees_with_shared_root_ancestor_do_not_conflict(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1361,
                status="pending",
                resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                resource_id=20,
                path_root="/10/20/",
                lock_scope=KnowledgeSpaceFileChangeLockScope.SUBTREE,
            )

        repository = KnowledgeSpaceFileChangeFootprintRepository(session)
        conflicts = await repository.find_blocking_request_ids(
            tenant_id=17,
            footprints=[
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                    resource_id=30,
                    path_root="/10/30/",
                    lock_scope=KnowledgeSpaceFileChangeLockScope.SUBTREE,
                )
            ],
        )

        assert conflicts == []


async def test_independent_destination_markers_do_not_conflict_on_shared_parent(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1371,
                status="pending",
                resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                resource_id=10,
                path_root="/10/",
                lock_scope=KnowledgeSpaceFileChangeLockScope.DESTINATION,
            )

        repository = KnowledgeSpaceFileChangeFootprintRepository(session)
        conflicts = await repository.find_blocking_request_ids(
            tenant_id=17,
            footprints=[
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                    resource_id=10,
                    path_root="/10/",
                    lock_scope=KnowledgeSpaceFileChangeLockScope.DESTINATION,
                )
            ],
        )

        assert conflicts == []


async def test_destination_conflicts_with_exact_change_to_same_directory(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            request_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1381,
                status="pending",
                resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                resource_id=10,
                path_root="/10/",
                lock_scope=KnowledgeSpaceFileChangeLockScope.DESTINATION,
            )

        repository = KnowledgeSpaceFileChangeFootprintRepository(session)
        conflicts = await repository.find_blocking_request_ids(
            tenant_id=17,
            footprints=[
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                    resource_id=10,
                    path_root="/10/",
                    lock_scope=KnowledgeSpaceFileChangeLockScope.EXACT,
                )
            ],
        )

        assert conflicts == [request_id]


async def test_path_like_treats_percent_and_underscore_as_literal_characters(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            literal_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1401,
                status="pending",
                resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                resource_id=41,
                path_root="/literal%_folder\\name/child/",
                lock_scope=KnowledgeSpaceFileChangeLockScope.SUBTREE,
            )
            await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1402,
                status="pending",
                resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                resource_id=42,
                path_root="/literalXXfolderZname/child/",
                lock_scope=KnowledgeSpaceFileChangeLockScope.SUBTREE,
            )

        repository = KnowledgeSpaceFileChangeFootprintRepository(session)
        conflicts = await repository.find_blocking_request_ids(
            tenant_id=17,
            footprints=[
                FootprintEntry(
                    space_id=101,
                    resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                    resource_id=99,
                    path_root="/literal%_folder\\name/",
                    lock_scope=KnowledgeSpaceFileChangeLockScope.SUBTREE,
                )
            ],
        )

        assert conflicts == [literal_id]


async def test_add_many_normalizes_paths_deduplicates_and_never_queries_action_json(repository_engine):
    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            request_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1501,
                status="pending",
            )
            repository = KnowledgeSpaceFileChangeFootprintRepository(session)
            rows = await repository.add_many(
                tenant_id=17,
                request_id=request_id,
                footprints=[
                    FootprintEntry(
                        space_id=101,
                        resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                        resource_id=88,
                        path_root="10//20",
                        lock_scope=KnowledgeSpaceFileChangeLockScope.SUBTREE,
                    ),
                    FootprintEntry(
                        space_id=101,
                        resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                        resource_id=88,
                        path_root="/10/20/",
                        lock_scope=KnowledgeSpaceFileChangeLockScope.SUBTREE,
                    ),
                ],
            )

        assert len(rows) == 1
        assert rows[0].path_root == "/10/20/"
        statement = repository.build_blocking_conflict_statement(
            tenant_id=17,
            footprints=[FootprintEntry(space_id=101, resource_type="folder", path_root="/10/")],
        )
        compiled = str(statement.compile()).lower()
        assert "action_snapshot" not in compiled
        assert "json_" not in compiled


async def test_resource_lock_and_approver_reconciliation_status_sets_are_separate(repository_engine):
    assert RESOURCE_LOCK_BLOCKING_STATUSES == frozenset(
        {
            KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
            KnowledgeSpaceFileChangeExecutionState.QUEUED,
            KnowledgeSpaceFileChangeExecutionState.APPLYING,
            KnowledgeSpaceFileChangeExecutionState.FAILED,
            KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
        }
    )
    assert APPROVER_RECONCILABLE_STATUSES == frozenset({KnowledgeSpaceFileChangeExecutionState.NOT_STARTED})
    assert KnowledgeSpaceFileChangeExecutionState.APPLIED not in APPROVER_RECONCILABLE_STATUSES

    set_current_tenant_id(17)
    async with AsyncSession(bind=repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            pending_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1601,
                status="pending",
            )
            empty_exception_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1602,
                status="exception",
            )
            other_exception_id = await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1603,
                status="exception",
            )
            await _insert_request(
                session,
                tenant_id=17,
                space_id=101,
                instance_id=1604,
                status="approved",
            )

        repository = KnowledgeSpaceFileChangeRequestRepository(session)
        ids = await repository.list_reconcilable_instance_ids(
            tenant_id=17,
            space_ids=[101],
            after_instance_id=0,
            limit=100,
        )

        # API returns instance IDs, not request IDs.
        assert ids == [1601, 1602, 1603, 1604]
        assert pending_id != empty_exception_id != other_exception_id
