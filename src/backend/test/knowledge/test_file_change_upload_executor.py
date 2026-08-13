from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import (
    SpaceFileSizeLimitError,
    SpaceFolderNotFoundError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
    KnowledgeSpaceFileChangeExecutionStepState,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_policy import KnowledgeSpaceFileChangePolicy
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import (
    KnowledgeSpaceUploadStage,
    KnowledgeSpaceUploadStageState,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    KnowledgeSpaceMutationExecutor,
    MutationExecutionDispatch,
    UploadExecutionStepCode,
    UploadStepDispatchContext,
)


@pytest_asyncio.fixture
async def upload_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        KnowledgeSpaceUploadStage.__table__,
        Knowledge.__table__,
        KnowledgeSpaceFileChangeRequest.__table__,
        KnowledgeFile.__table__,
        KnowledgeDocument.__table__,
        KnowledgeDocumentVersion.__table__,
        KnowledgeSpaceFileChangeExecutionStep.__table__,
        KnowledgeSpaceFileChangePolicy.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=tables))
        await connection.exec_driver_sql(
            "CREATE TABLE userrole (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
            "role_id INTEGER NOT NULL, tenant_id INTEGER NOT NULL)"
        )
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def tenant_context():
    token = current_tenant_id.set(None)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def _session_factory(engine):
    @asynccontextmanager
    async def factory():
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            yield session

    return factory


async def _seed_upload_bundle(
    engine,
    *,
    tenant_id: int = 42,
    relative_path: str = "quarterly.pdf",
    space_state: int = KnowledgeState.PUBLISHED.value,
    source_parent_id: int | None = None,
    create_source_parent: bool = False,
) -> tuple[int, int]:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            session.add(
                Knowledge(
                    id=8,
                    tenant_id=tenant_id,
                    user_id=1,
                    name="Finance",
                    type=KnowledgeTypeEnum.SPACE.value,
                    state=space_state,
                )
            )
            if source_parent_id is not None and create_source_parent:
                session.add(
                    KnowledgeFile(
                        id=source_parent_id,
                        tenant_id=tenant_id,
                        knowledge_id=8,
                        user_id=7,
                        user_name="applicant",
                        updater_id=7,
                        updater_name="applicant",
                        file_name="approved-target",
                        file_type=0,
                        level=0,
                        file_level_path="",
                        status=KnowledgeFileStatus.SUCCESS.value,
                    )
                )
            stage = KnowledgeSpaceUploadStage(
                tenant_id=tenant_id,
                upload_id="opaque-upload-1",
                space_id=8,
                uploader_user_id=7,
                object_name="knowledge-space-upload-stage/42/opaque-upload-1",
                file_name="quarterly.pdf",
                file_size=1024,
                content_hash="sha256-content",
                state=KnowledgeSpaceUploadStageState.ATTACHED,
                expire_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
            )
            session.add(stage)
            await session.flush()
            request = KnowledgeSpaceFileChangeRequest(
                tenant_id=tenant_id,
                space_id=8,
                action=KnowledgeSpaceFileChangeAction.UPLOAD,
                resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
                applicant_user_id=7,
                business_key="knowledge-space-change:upload-executor",
                request_fingerprint="upload-executor-fingerprint",
                approval_instance_id=101,
                upload_stage_id=stage.id,
                source_parent_id=source_parent_id,
                file_name=stage.file_name,
                file_size=stage.file_size,
                content_hash=stage.content_hash,
                action_snapshot={"relative_path": relative_path},
            )
            session.add(request)
            await session.flush()
            return int(request.id), int(stage.id)


async def _rows(engine, model):
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        return list((await session.exec(select(model))).all())


class _SideEffects:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.events: list[tuple[str, str]] = []

    async def authorize_file(self, context) -> str:
        await self._assert_committed_bundle(context)
        self.events.append((UploadExecutionStepCode.FGA, context.idempotency_key))
        return "fga-authoritative-ack"

    async def dispatch_parse(self, context) -> str:
        await self._assert_committed_bundle(context)
        self.events.append((UploadExecutionStepCode.PARSE, context.idempotency_key))
        return "parse-task-701"

    async def _assert_committed_bundle(self, context) -> None:
        async with AsyncSession(bind=self.engine, expire_on_commit=False) as session:
            request = await session.get(KnowledgeSpaceFileChangeRequest, context.request_id)
            file = await session.get(KnowledgeFile, context.file_id)
            steps = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceFileChangeExecutionStep).where(
                            KnowledgeSpaceFileChangeExecutionStep.request_id == context.request_id
                        )
                    )
                ).all()
            )
        assert request is not None and request.executed_resource_id == context.file_id
        assert file is not None
        assert len(steps) == 4


async def _allow_execution(**_kwargs) -> None:
    return None


def _executor(
    engine,
    side_effects,
    *,
    tokens=None,
    repository_factory=None,
    execution_validator=_allow_execution,
):
    token_iter = iter(tokens or ["attempt-token-1"])
    return KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(engine),
        authorize_file=side_effects.authorize_file,
        dispatch_parse=side_effects.dispatch_parse,
        execution_token_factory=lambda: next(token_iter),
        deadline_factory=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        mutation_repository_factory=repository_factory,
        execution_validator=execution_validator,
    )


async def test_formal_file_document_version_request_link_and_steps_commit_before_side_effects(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(upload_engine)
    side_effects = _SideEffects(upload_engine)

    result = await _executor(upload_engine, side_effects).execute(
        request_id=request_id,
    )

    assert isinstance(result, MutationExecutionDispatch)
    assert result.execution_token == "attempt-token-1"
    files = await _rows(upload_engine, KnowledgeFile)
    documents = await _rows(upload_engine, KnowledgeDocument)
    versions = await _rows(upload_engine, KnowledgeDocumentVersion)
    requests = await _rows(upload_engine, KnowledgeSpaceFileChangeRequest)
    stages = await _rows(upload_engine, KnowledgeSpaceUploadStage)
    steps = await _rows(upload_engine, KnowledgeSpaceFileChangeExecutionStep)
    assert len(files) == len(documents) == len(versions) == 1
    assert requests[0].executed_resource_id == files[0].id
    assert requests[0].execution_token == result.execution_token
    assert requests[0].execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING
    assert stages[0].state == KnowledgeSpaceUploadStageState.CONSUMED
    assert documents[0].primary_version_id == versions[0].id
    assert versions[0].knowledge_file_id == files[0].id
    assert {step.step_code for step in steps} == {
        UploadExecutionStepCode.FGA,
        UploadExecutionStepCode.PARSE,
        UploadExecutionStepCode.INDEX,
        UploadExecutionStepCode.VECTOR,
    }
    assert side_effects.events == [
        (UploadExecutionStepCode.FGA, f"f046:{request_id}:upload.fga"),
        (UploadExecutionStepCode.PARSE, f"f046:{request_id}:upload.parse"),
    ]


async def test_failure_after_formal_rows_flush_rolls_back_every_database_row(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(upload_engine)
    side_effects = _SideEffects(upload_engine)

    class FailingRepository:
        def __init__(self, session) -> None:
            from bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository import (
                KnowledgeSpaceMutationRepository,
            )

            self.delegate = KnowledgeSpaceMutationRepository(session)

        def __getattr__(self, name):  # pragma: no cover - defensive
            return getattr(self.delegate, name)

        async def add_formal_upload_bundle(self, **kwargs):
            await self.delegate.add_formal_upload_bundle(**kwargs)
            raise RuntimeError("fault after formal rows flush")

    executor = _executor(
        upload_engine,
        side_effects,
        repository_factory=FailingRepository,
    )
    with pytest.raises(RuntimeError, match="fault after formal rows flush"):
        await executor.execute(
            request_id=request_id,
        )

    assert await _rows(upload_engine, KnowledgeFile) == []
    assert await _rows(upload_engine, KnowledgeDocument) == []
    assert await _rows(upload_engine, KnowledgeDocumentVersion) == []
    assert await _rows(upload_engine, KnowledgeSpaceFileChangeExecutionStep) == []
    request = (await _rows(upload_engine, KnowledgeSpaceFileChangeRequest))[0]
    stage = (await _rows(upload_engine, KnowledgeSpaceUploadStage))[0]
    assert request.executed_resource_id is None
    assert request.execution_token is None
    assert stage.state == KnowledgeSpaceUploadStageState.ATTACHED
    assert side_effects.events == []


async def test_duplicate_execution_reuses_file_token_and_stable_steps_without_redispatch(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(upload_engine)
    side_effects = _SideEffects(upload_engine)
    executor = _executor(upload_engine, side_effects, tokens=["attempt-token-1", "must-not-be-used"])

    first = await executor.execute(
        request_id=request_id,
    )
    second = await executor.execute(
        request_id=request_id,
    )

    assert second == first
    assert len(await _rows(upload_engine, KnowledgeFile)) == 1
    assert len(await _rows(upload_engine, KnowledgeDocument)) == 1
    assert len(await _rows(upload_engine, KnowledgeDocumentVersion)) == 1
    assert len(await _rows(upload_engine, KnowledgeSpaceFileChangeExecutionStep)) == 4
    assert len(side_effects.events) == 2


async def test_executor_never_falls_back_to_a_request_from_another_tenant(upload_engine):
    request_id, _stage_id = await _seed_upload_bundle(upload_engine, tenant_id=42)
    set_current_tenant_id(99)
    side_effects = _SideEffects(upload_engine)

    with pytest.raises(LookupError, match="request not found"):
        await _executor(upload_engine, side_effects).execute(
            request_id=request_id,
        )

    request = (await _rows(upload_engine, KnowledgeSpaceFileChangeRequest))[0]
    assert request.executed_resource_id is None
    assert request.execution_token is None
    assert side_effects.events == []


async def test_approved_upload_rejects_stage_metadata_drift_before_formal_rows(upload_engine):
    set_current_tenant_id(42)
    request_id, stage_id = await _seed_upload_bundle(upload_engine)
    async with AsyncSession(bind=upload_engine, expire_on_commit=False) as session:
        async with session.begin():
            stage = await session.get(KnowledgeSpaceUploadStage, stage_id)
            stage.content_hash = "different-content"
            session.add(stage)
    side_effects = _SideEffects(upload_engine)

    with pytest.raises(ValueError, match="metadata changed"):
        await _executor(upload_engine, side_effects).execute(
            request_id=request_id,
        )

    assert await _rows(upload_engine, KnowledgeFile) == []
    assert await _rows(upload_engine, KnowledgeSpaceFileChangeExecutionStep) == []
    assert side_effects.events == []


async def test_runtime_validator_rejects_permission_revoked_after_approval(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(upload_engine)
    side_effects = _SideEffects(upload_engine)
    executor = _executor(upload_engine, side_effects, execution_validator=None)

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.has_effective_permission_id_strict",
        new_callable=AsyncMock,
        return_value=False,
    ) as permission_id_check:
        with pytest.raises(SpacePermissionDeniedError):
            await executor.execute(
                request_id=request_id,
            )

    permission_id_check.assert_awaited_once()
    assert permission_id_check.await_args.args == ("knowledge_space", 8, "upload_file")
    assert permission_id_check.await_args.kwargs["locked_space"] is not None
    assert await _rows(upload_engine, KnowledgeFile) == []
    assert await _rows(upload_engine, KnowledgeSpaceFileChangeExecutionStep) == []
    assert side_effects.events == []


async def test_runtime_validator_rejects_space_unpublished_after_approval(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(
        upload_engine,
        space_state=KnowledgeState.UNPUBLISHED.value,
    )
    side_effects = _SideEffects(upload_engine)
    executor = _executor(upload_engine, side_effects, execution_validator=None)

    with pytest.raises(SpaceNotFoundError):
        await executor.execute(
            request_id=request_id,
        )

    assert await _rows(upload_engine, KnowledgeFile) == []
    assert await _rows(upload_engine, KnowledgeSpaceFileChangeExecutionStep) == []
    assert side_effects.events == []


async def test_runtime_validator_checks_locked_source_folder_permission(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(
        upload_engine,
        source_parent_id=33,
        create_source_parent=True,
    )
    side_effects = _SideEffects(upload_engine)
    executor = _executor(upload_engine, side_effects, execution_validator=None)

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.has_effective_permission_id_strict",
        new_callable=AsyncMock,
        return_value=False,
    ) as permission_check:
        with pytest.raises(SpacePermissionDeniedError):
            await executor.execute(
                request_id=request_id,
            )

    assert permission_check.await_args.args == ("folder", 33, "upload_file")
    assert permission_check.await_args.kwargs["space_id"] == 8
    assert await _rows(upload_engine, KnowledgeSpaceFileChangeExecutionStep) == []


async def test_runtime_validator_rejects_source_folder_deleted_after_approval(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(
        upload_engine,
        source_parent_id=33,
        create_source_parent=False,
    )
    side_effects = _SideEffects(upload_engine)
    executor = _executor(upload_engine, side_effects, execution_validator=None)

    with pytest.raises(SpaceFolderNotFoundError):
        await executor.execute(
            request_id=request_id,
        )

    assert await _rows(upload_engine, KnowledgeFile) == []
    assert await _rows(upload_engine, KnowledgeSpaceFileChangeExecutionStep) == []


async def test_runtime_validator_rejects_role_quota_tightened_below_reserved_stage(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(upload_engine)
    side_effects = _SideEffects(upload_engine)
    executor = _executor(upload_engine, side_effects, execution_validator=None)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.has_effective_permission_id_strict",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "bisheng.role.domain.services.quota_service.QuotaService.get_knowledge_space_upload_limit_bytes",
            new_callable=AsyncMock,
            return_value=1023,
        ),
    ):
        with pytest.raises(SpaceFileSizeLimitError):
            await executor.execute(
                request_id=request_id,
            )

    assert await _rows(upload_engine, KnowledgeFile) == []
    assert await _rows(upload_engine, KnowledgeSpaceFileChangeExecutionStep) == []
    assert side_effects.events == []


async def test_knowledge_owner_rejects_can_edit_model_without_upload_file_permission_id(monkeypatch):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    service = KnowledgeSpaceService(
        request=None,
        login_user=UserPayload(user_id=7, user_name="editor", tenant_id=42, user_role=[]),
    )
    effective_loader = AsyncMock(return_value={"view_space", "edit_space", "rename_file"})
    monkeypatch.setattr(service, "_get_effective_permission_ids", effective_loader)

    allowed = await service.has_effective_permission_id(
        "knowledge_space",
        8,
        "upload_file",
        space_id=8,
    )

    assert allowed is False
    effective_loader.assert_awaited_once_with(
        "knowledge_space",
        8,
        space_id=8,
        include_public_viewer=False,
    )


async def test_knowledge_owner_allows_custom_non_edit_relation_with_upload_file_permission_id(monkeypatch):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    service = KnowledgeSpaceService(
        request=None,
        login_user=UserPayload(user_id=7, user_name="custom-viewer", tenant_id=42, user_role=[]),
    )
    effective_loader = AsyncMock(return_value={"view_space", "upload_file"})
    monkeypatch.setattr(service, "_get_effective_permission_ids", effective_loader)

    assert await service.has_effective_permission_id(
        "knowledge_space",
        8,
        "upload_file",
        space_id=8,
    )


async def test_parse_scheduler_handoff_completes_business_step_while_pipeline_steps_remain_pending(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(upload_engine)
    side_effects = _SideEffects(upload_engine)

    result = await _executor(upload_engine, side_effects).execute(
        request_id=request_id,
    )

    assert isinstance(result, MutationExecutionDispatch)
    step_by_code = {step.step_code: step for step in await _rows(upload_engine, KnowledgeSpaceFileChangeExecutionStep)}
    assert step_by_code[UploadExecutionStepCode.FGA].state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
    assert step_by_code[UploadExecutionStepCode.PARSE].state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
    assert step_by_code[UploadExecutionStepCode.INDEX].state == KnowledgeSpaceFileChangeExecutionStepState.PENDING
    assert step_by_code[UploadExecutionStepCode.VECTOR].state == KnowledgeSpaceFileChangeExecutionStepState.PENDING
    request = (await _rows(upload_engine, KnowledgeSpaceFileChangeRequest))[0]
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING


async def test_parse_dispatch_hands_off_to_regular_upload_without_business_callback(monkeypatch):
    context = UploadStepDispatchContext(
        tenant_id=42,
        request_id=41,
        execution_token="attempt-token-1",
        step_code=UploadExecutionStepCode.PARSE,
        idempotency_key="f046:41:upload.parse",
        file_id=701,
        file_name="quarterly.pdf",
        applicant_user_id=7,
        space_id=8,
        checkpoint={},
    )

    enqueue = Mock()
    scheduler_module = SimpleNamespace(enqueue_or_dispatch=enqueue)
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.knowledge.scheduler",
        scheduler_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.knowledge",
        SimpleNamespace(scheduler=scheduler_module),
    )
    monkeypatch.setitem(
        sys.modules,
        "bisheng.knowledge.domain.services.knowledge_space_service",
        SimpleNamespace(
            KnowledgeSpaceService=SimpleNamespace(
                get_preview_cache_key=lambda *_args: "preview-cache",
            )
        ),
    )
    result = await KnowledgeSpaceMutationExecutor._dispatch_parse(context)

    assert result == "scheduler:f046:41:upload.parse"
    enqueue.assert_called_once_with(
        user_id=7,
        file_id=701,
        file_name="quarterly.pdf",
        preview_cache_key="preview-cache",
        callback_url=None,
        idempotency_key="f046:41:upload.parse",
    )
    assert "file_change_request_id" not in enqueue.call_args.kwargs
    assert "file_change_execution_token" not in enqueue.call_args.kwargs


async def test_folder_upload_checkpoint_has_guard_manifest_for_new_directories_and_file(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(
        upload_engine,
        relative_path="reports/2026/quarterly.pdf",
    )
    side_effects = _SideEffects(upload_engine)

    await _executor(upload_engine, side_effects).execute(
        request_id=request_id,
    )

    request = (await _rows(upload_engine, KnowledgeSpaceFileChangeRequest))[0]
    resources = request.execution_checkpoint["formal_resource_ids"]
    assert [resource["resource_type"] for resource in resources] == [
        "folder",
        "folder",
        "knowledge_file",
    ]
    assert len({int(resource["resource_id"]) for resource in resources}) == 3
    assert int(resources[-1]["resource_id"]) == int(request.executed_resource_id)
    assert "parent_type" not in resources[0]
    assert "owner_user_id" not in resources[0]


async def test_prepare_resume_uses_new_token_without_new_file_or_business_request(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(upload_engine)
    side_effects = _SideEffects(upload_engine)
    executor = _executor(upload_engine, side_effects)
    first = await executor.execute(
        request_id=request_id,
    )

    async with AsyncSession(bind=upload_engine, expire_on_commit=False) as session:
        async with session.begin():
            request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
            request.execution_state = KnowledgeSpaceFileChangeExecutionState.FAILED
            session.add(request)
            steps = list((await session.exec(select(KnowledgeSpaceFileChangeExecutionStep))).all())
            for step in steps:
                if step.step_code != UploadExecutionStepCode.FGA:
                    step.state = KnowledgeSpaceFileChangeExecutionStepState.FAILED
                    session.add(step)

    async with AsyncSession(bind=upload_engine, expire_on_commit=False) as session:
        async with session.begin():
            resumed = await executor.prepare_upload_resume_in_uow(
                session=session,
                request_id=request_id,
                new_token="attempt-token-2",
            )

    assert isinstance(resumed, MutationExecutionDispatch)
    assert first.execution_token != resumed.execution_token == "attempt-token-2"
    assert len(await _rows(upload_engine, KnowledgeFile)) == 1
    assert len(await _rows(upload_engine, KnowledgeSpaceFileChangeRequest)) == 1
    request = (await _rows(upload_engine, KnowledgeSpaceFileChangeRequest))[0]
    assert request.approval_instance_id == 101
    assert request.execution_token == "attempt-token-2"
    step_by_code = {step.step_code: step for step in await _rows(upload_engine, KnowledgeSpaceFileChangeExecutionStep)}
    assert step_by_code[UploadExecutionStepCode.FGA].state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
    for code in (UploadExecutionStepCode.PARSE, UploadExecutionStepCode.INDEX, UploadExecutionStepCode.VECTOR):
        assert step_by_code[code].attempt_token == "attempt-token-2"
        assert step_by_code[code].state == KnowledgeSpaceFileChangeExecutionStepState.PENDING


async def test_post_commit_dispatch_failure_marks_request_failed_for_token_bound_resume(upload_engine):
    set_current_tenant_id(42)
    request_id, _stage_id = await _seed_upload_bundle(upload_engine)
    side_effects = _SideEffects(upload_engine)

    async def fail_parse(_context):
        raise RuntimeError("broker unavailable")

    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(upload_engine),
        authorize_file=side_effects.authorize_file,
        dispatch_parse=fail_parse,
        execution_token_factory=lambda: "attempt-token-1",
        deadline_factory=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        execution_validator=_allow_execution,
    )
    with pytest.raises(RuntimeError, match="broker unavailable"):
        await executor.execute(
            request_id=request_id,
        )

    request = (await _rows(upload_engine, KnowledgeSpaceFileChangeRequest))[0]
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED
    assert request.execution_token == "attempt-token-1"
    assert request.execution_checkpoint["failure_reason"] == "broker unavailable"
    assert request.executed_resource_id is not None
    assert len(await _rows(upload_engine, KnowledgeFile)) == 1
