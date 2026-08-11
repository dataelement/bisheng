from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import (
    SpaceFileChangeInvalidStateError,
    SpaceFileSizeLimitError,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_space_file_change_policy import (
    KnowledgeSpaceFileChangePolicy,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import (
    KnowledgeSpaceUploadStage,
    KnowledgeSpaceUploadStageState,
)
from bisheng.knowledge.domain.repositories.knowledge_space_upload_stage_repository import (
    KnowledgeSpaceUploadStageRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_space_file_change_schema import (
    KnowledgeSpaceUploadStageResp,
)
from bisheng.knowledge.domain.services.knowledge_space_upload_stage_service import (
    KnowledgeSpaceUploadCapacity,
    KnowledgeSpaceUploadStageService,
)


class _Storage:
    bucket = "permanent-uploads"
    tmp_bucket = "temporary-uploads"

    def __init__(self) -> None:
        self.copy_calls: list[tuple[str, str, str, str]] = []
        self.remove_calls: list[tuple[str, str]] = []
        self.existing_objects: set[tuple[str, str]] = set()
        self.preview_calls: list[tuple[str, str, int, dict[str, str] | None]] = []

    async def copy_object(
        self,
        source_bucket: str,
        source_object: str,
        dest_bucket: str,
        dest_object: str,
    ) -> None:
        self.copy_calls.append((source_bucket, source_object, dest_bucket, dest_object))
        if (source_bucket, source_object) not in self.existing_objects:
            raise FileNotFoundError(source_object)
        self.existing_objects.add((dest_bucket, dest_object))

    async def remove_object(self, bucket_name: str, object_name: str) -> None:
        self.remove_calls.append((bucket_name, object_name))
        self.existing_objects.discard((bucket_name, object_name))

    async def object_exists(self, bucket_name: str, object_name: str) -> bool:
        return (bucket_name, object_name) in self.existing_objects

    async def get_share_link(
        self,
        object_name: str,
        bucket: str,
        expire_days: int,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        self.preview_calls.append((bucket, object_name, expire_days, response_headers))
        return "https://preview.invalid/opaque-token"


@pytest_asyncio.fixture
async def stage_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        KnowledgeSpaceFileChangePolicy.__table__,
        KnowledgeSpaceUploadStage.__table__,
        KnowledgeSpaceFileChangeRequest.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: SQLModel.metadata.create_all(sync_connection, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def reset_tenant_context():
    token = current_tenant_id.set(None)
    yield
    current_tenant_id.reset(token)


def _service(
    engine,
    storage: _Storage,
    *,
    capacity: KnowledgeSpaceUploadCapacity | None = None,
    generated_ids: list[str] | None = None,
) -> KnowledgeSpaceUploadStageService:
    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            yield session

    async def load_capacity(_tenant_id: int, _uploader_user_id: int) -> KnowledgeSpaceUploadCapacity:
        return capacity or KnowledgeSpaceUploadCapacity()

    ids = iter(generated_ids or [])

    def upload_id_factory() -> str:
        return next(ids, str(uuid4()))

    class _TestStageService(KnowledgeSpaceUploadStageService):
        async def create_stage(
            self,
            *,
            space_id: int,
            uploader_user_id: int,
            file_name: str,
            content: bytes,
            upload_id: str | None = None,
        ):
            temporary_object_name = f"tmp-{hashlib.sha256(content).hexdigest()[:16]}-{file_name}"
            storage.existing_objects.add((storage.tmp_bucket, temporary_object_name))
            return await super().create_stage(
                space_id=space_id,
                uploader_user_id=uploader_user_id,
                file_name=file_name,
                file_size=len(content),
                content_hash=hashlib.sha256(content).hexdigest(),
                temporary_object_name=temporary_object_name,
                upload_id=upload_id,
            )

    return _TestStageService(
        session_factory=session_factory,
        storage=storage,
        capacity_loader=load_capacity,
        upload_id_factory=upload_id_factory,
        now=lambda: datetime(2026, 8, 10, tzinfo=UTC),
    )


async def _rows(engine, tenant_id: int) -> list[KnowledgeSpaceUploadStage]:
    async with AsyncSession(bind=engine) as session:
        statement = select(KnowledgeSpaceUploadStage).where(KnowledgeSpaceUploadStage.tenant_id == tenant_id)
        return list((await session.exec(statement)).all())


async def test_create_stage_generates_opaque_uuid_and_persists_server_metadata_without_object_name_output(
    stage_engine,
):
    set_current_tenant_id(17)
    storage = _Storage()
    service = _service(stage_engine, storage)

    stage = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="quarterly.pdf",
        content=b"authoritative-content",
    )

    UUID(stage.upload_id)
    assert stage.file_name == "quarterly.pdf"
    assert stage.file_size == len(b"authoritative-content")
    assert stage.content_hash == hashlib.sha256(b"authoritative-content").hexdigest()
    assert stage.object_name.startswith("tmp-")
    assert storage.copy_calls == []

    public = KnowledgeSpaceUploadStageResp.model_validate(stage).model_dump()
    assert public["upload_id"] == stage.upload_id
    assert "object_name" not in public


async def test_same_upload_id_and_hash_is_idempotent_but_changed_content_creates_a_new_stage(stage_engine):
    set_current_tenant_id(17)
    storage = _Storage()
    first_id = "adf44898-771e-4f5e-a6b5-c959f795e01e"
    changed_id = "0ac0c8b8-8960-402f-9447-59c646d846ed"
    service = _service(stage_engine, storage, generated_ids=[changed_id])

    first = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="report.txt",
        content=b"same",
        upload_id=first_id,
    )
    retried = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="report.txt",
        content=b"same",
        upload_id=first_id,
    )
    changed = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="report.txt",
        content=b"changed",
        upload_id=first_id,
    )

    assert retried.id == first.id
    assert changed.upload_id == changed_id
    assert changed.content_hash != first.content_hash
    assert storage.copy_calls == []
    assert len(await _rows(stage_engine, 17)) == 2


async def test_capacity_counts_formal_and_reserved_bytes_under_tenant_lock_and_consume_releases_reservation(
    stage_engine,
):
    set_current_tenant_id(17)
    storage = _Storage()
    capacity = KnowledgeSpaceUploadCapacity(
        user_used_bytes=10,
        user_limit_bytes=100,
        tenant_used_bytes=20,
        tenant_limit_bytes=200,
    )
    service = _service(stage_engine, storage, capacity=capacity)

    first = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="first.bin",
        content=b"a" * 60,
    )
    with pytest.raises(SpaceFileSizeLimitError):
        await service.create_stage(
            space_id=101,
            uploader_user_id=7,
            file_name="too-large.bin",
            content=b"b" * 31,
        )

    await service.attach(first.upload_id)
    consumed = await service.consume(first.upload_id)
    assert consumed.state == KnowledgeSpaceUploadStageState.CONSUMED

    second = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="after-consume.bin",
        content=b"c" * 31,
    )
    assert second.state == KnowledgeSpaceUploadStageState.UPLOADED

    async with AsyncSession(bind=stage_engine) as session:
        policy = (
            await session.exec(
                select(KnowledgeSpaceFileChangePolicy).where(KnowledgeSpaceFileChangePolicy.tenant_id == 17)
            )
        ).one()
        assert policy.id is not None


async def test_cleanup_releases_capacity_removes_object_and_is_retry_idempotent(stage_engine):
    set_current_tenant_id(17)
    storage = _Storage()
    service = _service(
        stage_engine,
        storage,
        capacity=KnowledgeSpaceUploadCapacity(user_limit_bytes=50),
    )
    stage = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="cleanup.bin",
        content=b"x" * 40,
    )
    await service.attach(stage.upload_id)

    cleaned = await service.cleanup(stage.upload_id)
    retried = await service.cleanup(stage.upload_id)
    replacement = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="replacement.bin",
        content=b"y" * 40,
    )

    assert cleaned.state == KnowledgeSpaceUploadStageState.CLEANED
    assert retried.state == KnowledgeSpaceUploadStageState.CLEANED
    assert storage.remove_calls == [
        (storage.tmp_bucket, stage.object_name),
        (storage.bucket, f"knowledge-space-upload-stage/17/{stage.upload_id}.bin"),
    ]
    assert replacement.id != stage.id


async def test_expired_orphan_reconcile_waits_for_minio_lifecycle_and_rechecks_binding(stage_engine):
    set_current_tenant_id(17)
    storage = _Storage()
    service = _service(stage_engine, storage)
    expired = datetime(2026, 8, 9, tzinfo=UTC)
    async with AsyncSession(bind=stage_engine, expire_on_commit=False) as session:
        orphan = KnowledgeSpaceUploadStage(
            upload_id=str(uuid4()),
            tenant_id=17,
            space_id=101,
            uploader_user_id=7,
            object_name="internal/orphan",
            file_name="orphan.bin",
            file_size=10,
            content_hash="orphan-hash",
            state=KnowledgeSpaceUploadStageState.UPLOADED,
            expire_at=expired,
        )
        attached = KnowledgeSpaceUploadStage(
            upload_id=str(uuid4()),
            tenant_id=17,
            space_id=101,
            uploader_user_id=7,
            object_name="internal/attached",
            file_name="attached.bin",
            file_size=10,
            content_hash="attached-hash",
            state=KnowledgeSpaceUploadStageState.ATTACHED,
            expire_at=expired,
        )
        bound = KnowledgeSpaceUploadStage(
            upload_id=str(uuid4()),
            tenant_id=17,
            space_id=101,
            uploader_user_id=7,
            object_name="internal/bound",
            file_name="bound.bin",
            file_size=10,
            content_hash="bound-hash",
            state=KnowledgeSpaceUploadStageState.UPLOADED,
            expire_at=expired,
        )
        session.add_all([orphan, attached, bound])
        await session.flush()
        session.add(
            KnowledgeSpaceFileChangeRequest(
                tenant_id=17,
                space_id=101,
                action=KnowledgeSpaceFileChangeAction.UPLOAD,
                resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
                applicant_user_id=7,
                upload_stage_id=bound.id,
            )
        )
        await session.commit()

    storage.existing_objects.add((storage.tmp_bucket, orphan.object_name))
    assert not await service.reconcile_expired_orphan(orphan.upload_id)
    assert storage.remove_calls == []

    # MinIO lifecycle owns physical deletion. The application only releases
    # metadata/capacity after authoritative absence is observed.
    storage.existing_objects.remove((storage.tmp_bucket, orphan.object_name))
    assert await service.reconcile_expired_orphan(orphan.upload_id)
    assert await service.reconcile_expired_orphan(orphan.upload_id)
    assert not await service.reconcile_expired_orphan(attached.upload_id)
    assert not await service.reconcile_expired_orphan(bound.upload_id)
    assert storage.remove_calls == []


async def test_retain_bound_stage_copies_temporary_object_before_attached_state(stage_engine):
    set_current_tenant_id(17)
    storage = _Storage()
    service = _service(stage_engine, storage)
    stage = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="pending.pdf",
        content=b"pending",
    )

    async with AsyncSession(bind=stage_engine) as session:
        row = await KnowledgeSpaceUploadStageRepository(session).get_by_upload_id(
            tenant_id=17,
            upload_id=stage.upload_id,
            for_update=True,
        )
        row.state = KnowledgeSpaceUploadStageState.ATTACHING
        session.add(row)
        await session.commit()

    retained = await service.retain_bound_stage(stage.upload_id)
    retried = await service.retain_bound_stage(stage.upload_id)

    assert retained.state == KnowledgeSpaceUploadStageState.ATTACHED
    assert retried.state == KnowledgeSpaceUploadStageState.ATTACHED
    assert storage.copy_calls == [
        (
            storage.tmp_bucket,
            stage.object_name,
            storage.bucket,
            f"knowledge-space-upload-stage/17/{stage.upload_id}.pdf",
        )
    ]
    assert retained.object_name == f"knowledge-space-upload-stage/17/{stage.upload_id}.pdf"


async def test_tenant_capacity_includes_reserved_bytes_from_all_uploaders(stage_engine):
    set_current_tenant_id(17)
    storage = _Storage()
    service = _service(
        stage_engine,
        storage,
        capacity=KnowledgeSpaceUploadCapacity(
            tenant_used_bytes=20,
            tenant_limit_bytes=100,
        ),
    )
    first = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="first-user.bin",
        content=b"x" * 60,
    )

    with pytest.raises(SpaceFileSizeLimitError):
        await service.create_stage(
            space_id=101,
            uploader_user_id=8,
            file_name="second-user.bin",
            content=b"y" * 21,
        )

    await service.cleanup(first.upload_id)
    second = await service.create_stage(
        space_id=101,
        uploader_user_id=8,
        file_name="second-user.bin",
        content=b"y" * 21,
    )
    assert second.uploader_user_id == 8


async def test_state_transitions_and_cross_tenant_access_fail_closed(stage_engine):
    set_current_tenant_id(17)
    storage = _Storage()
    service = _service(stage_engine, storage)
    stage = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="state.txt",
        content=b"state",
    )

    with pytest.raises(SpaceFileChangeInvalidStateError):
        await service.consume(stage.upload_id)

    await service.attach(stage.upload_id)
    await service.consume(stage.upload_id)
    cleaned = await service.cleanup(stage.upload_id)
    assert cleaned.state == KnowledgeSpaceUploadStageState.CLEANED

    set_current_tenant_id(18)
    with pytest.raises(LookupError, match="upload stage not found"):
        await service.attach(stage.upload_id)


async def test_preview_is_short_lived_and_only_available_to_uploader_or_authorized_manager(stage_engine):
    set_current_tenant_id(17)
    storage = _Storage()
    service = _service(stage_engine, storage)
    stage = await service.create_stage(
        space_id=101,
        uploader_user_id=7,
        file_name="preview.pdf",
        content=b"preview",
    )

    assert await service.create_preview_url(stage.upload_id, requester_user_id=7) == (
        "https://preview.invalid/opaque-token"
    )
    assert (
        await service.create_preview_url(
            stage.upload_id,
            requester_user_id=8,
            can_manage_space=True,
        )
        == "https://preview.invalid/opaque-token"
    )
    with pytest.raises(PermissionError, match="not authorized"):
        await service.create_preview_url(stage.upload_id, requester_user_id=8)

    assert storage.preview_calls == [
        (
            storage.tmp_bucket,
            stage.object_name,
            1,
            {
                "response-content-disposition": "inline; filename*=UTF-8''preview.pdf",
                "response-content-type": "application/pdf",
            },
        ),
        (
            storage.tmp_bucket,
            stage.object_name,
            1,
            {
                "response-content-disposition": "inline; filename*=UTF-8''preview.pdf",
                "response-content-type": "application/pdf",
            },
        ),
    ]


def test_preview_headers_preserve_non_ascii_xlsx_name_and_content_type():
    headers = KnowledgeSpaceUploadStageService._preview_response_headers("731时点-现存合并范围内法人企业.xlsx")

    assert headers["response-content-disposition"].startswith("inline; filename*=UTF-8''731")
    assert "%E6%97%B6%E7%82%B9" in headers["response-content-disposition"]
    assert headers["response-content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def test_repository_queries_and_capacity_sums_always_have_explicit_tenant_predicates(stage_engine):
    async with AsyncSession(bind=stage_engine) as session:
        repository = KnowledgeSpaceUploadStageRepository(session)
        by_upload = str(
            repository.build_upload_id_statement(
                tenant_id=17,
                upload_id="opaque",
                for_update=True,
            )
        )
        reserved = str(repository.build_reserved_bytes_statement(tenant_id=17, uploader_user_id=7))

    assert "knowledge_space_upload_stage.tenant_id" in by_upload
    assert "FOR UPDATE" in by_upload
    assert "knowledge_space_upload_stage.tenant_id" in reserved
    assert "knowledge_space_upload_stage.uploader_user_id" in reserved
