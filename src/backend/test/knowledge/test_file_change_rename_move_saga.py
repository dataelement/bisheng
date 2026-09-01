from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import SpaceNotFoundError, SpacePermissionDeniedError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
    KnowledgeSpaceFileChangeExecutionStepState,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeFootprint,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_execution_step_repository import (
    KnowledgeSpaceFileChangeExecutionStepRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
    ExecutionStepContext,
    VerifiedExecutionStepResult,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    KnowledgeSpaceMutationExecutor,
    MoveExecutionStepCode,
    MutationExecutionCompleted,
    MutationExecutionDispatch,
    MutationStepContext,
    RenameExecutionStepCode,
    VerifiedMutationStepResult,
)


@pytest_asyncio.fixture
async def saga_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Knowledge.__table__,
        KnowledgeFile.__table__,
        KnowledgeDocument.__table__,
        KnowledgeDocumentVersion.__table__,
        KnowledgeSpaceFileChangeRequest.__table__,
        KnowledgeSpaceFileChangeExecutionStep.__table__,
        KnowledgeSpaceFileChangeFootprint.__table__,
        TagLink.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=tables))
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


async def _seed_spaces(session: AsyncSession) -> None:
    session.add_all(
        [
            Knowledge(
                id=10,
                tenant_id=42,
                user_id=1,
                name="source",
                type=KnowledgeTypeEnum.SPACE.value,
                state=KnowledgeState.PUBLISHED.value,
            ),
            Knowledge(
                id=20,
                tenant_id=42,
                user_id=2,
                name="target",
                type=KnowledgeTypeEnum.SPACE.value,
                state=KnowledgeState.PUBLISHED.value,
            ),
        ]
    )


async def _add_file(session: AsyncSession, **values) -> KnowledgeFile:
    defaults = {
        "tenant_id": 42,
        "knowledge_id": 10,
        "user_id": 7,
        "user_name": "editor",
        "updater_id": 7,
        "updater_name": "editor",
        "file_type": FileType.FILE.value,
        "level": 0,
        "file_level_path": "",
        "status": KnowledgeFileStatus.SUCCESS.value,
    }
    defaults.update(values)
    row = KnowledgeFile(**defaults)
    session.add(row)
    await session.flush()
    return row


async def _seed_rename(engine, *, resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE):
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            await _seed_spaces(session)
            row = await _add_file(
                session,
                id=101,
                file_name="old.pdf" if resource_type == "knowledge_file" else "old-folder",
                file_type=FileType.FILE.value if resource_type == "knowledge_file" else FileType.DIR.value,
            )
            if resource_type == KnowledgeSpaceFileChangeResourceType.FOLDER:
                await _add_file(
                    session,
                    id=102,
                    file_name="child.pdf",
                    file_level_path="/101",
                    level=1,
                )
            request = KnowledgeSpaceFileChangeRequest(
                tenant_id=42,
                space_id=10,
                action=KnowledgeSpaceFileChangeAction.RENAME,
                resource_type=resource_type,
                resource_id=row.id,
                applicant_user_id=7,
                business_key="knowledge-space-change:rename-saga",
                request_fingerprint="rename-saga-fingerprint",
                approval_instance_id=501,
                file_name=row.file_name,
                action_snapshot={"old_name": row.file_name, "new_name": "new.pdf" if row.file_type else "new-folder"},
            )
            session.add(request)
            await session.flush()
            return int(request.id)


async def _seed_cross_space_folder_move(engine) -> int:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            await _seed_spaces(session)
            await _add_file(
                session,
                id=201,
                knowledge_id=20,
                file_name="destination",
                file_type=FileType.DIR.value,
            )
            await _add_file(session, id=101, file_name="folder", file_type=FileType.DIR.value)
            child = await _add_file(session, id=102, file_name="child.pdf", file_level_path="/101", level=1)
            historical = await _add_file(
                session,
                id=103,
                file_name="child-v1.pdf",
                file_level_path="/101",
                level=1,
            )
            document = KnowledgeDocument(knowledge_id=10, file_level_path="/101", level=1)
            session.add(document)
            await session.flush()
            v1 = KnowledgeDocumentVersion(
                document_id=int(document.id), knowledge_file_id=int(historical.id), version_no=1, is_primary=False
            )
            v2 = KnowledgeDocumentVersion(
                document_id=int(document.id), knowledge_file_id=int(child.id), version_no=2, is_primary=True
            )
            session.add_all([v1, v2])
            session.add_all(
                [
                    TagLink(
                        tenant_id=42,
                        tag_id=9,
                        resource_id="102",
                        resource_type=ResourceTypeEnum.SPACE_FILE.value,
                        user_id=7,
                    ),
                    TagLink(
                        tenant_id=42,
                        tag_id=10,
                        resource_id="103",
                        resource_type=ResourceTypeEnum.SPACE_FILE.value,
                        user_id=7,
                    ),
                ]
            )
            await session.flush()
            document.primary_version_id = int(v2.id)
            session.add(document)
            request = KnowledgeSpaceFileChangeRequest(
                tenant_id=42,
                space_id=10,
                action=KnowledgeSpaceFileChangeAction.MOVE,
                resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
                resource_id=101,
                applicant_user_id=7,
                business_key="knowledge-space-change:move-saga",
                request_fingerprint="move-saga-fingerprint",
                approval_instance_id=502,
                file_name="folder",
                source_parent_id=None,
                target_space_id=20,
                target_parent_id=201,
                action_snapshot={"source_path": "", "source_level": 0},
            )
            session.add(request)
            await session.flush()
            return int(request.id)


async def _row(engine, model, row_id):
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        return await session.get(model, row_id)


async def _steps(engine, request_id):
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        return list(
            (
                await session.exec(
                    select(KnowledgeSpaceFileChangeExecutionStep)
                    .where(KnowledgeSpaceFileChangeExecutionStep.request_id == request_id)
                    .order_by(KnowledgeSpaceFileChangeExecutionStep.id)
                )
            ).all()
        )


class _VerifiedEffects:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.applied: list[MutationStepContext] = []
        self.compensated: list[MutationStepContext] = []
        self.fail_on: str | None = None

    async def apply(self, context: MutationStepContext) -> VerifiedMutationStepResult:
        resource = await _row(self.engine, KnowledgeFile, context.resource_id)
        assert resource.file_name == context.manifest["root"]["old_name"]
        assert resource.knowledge_id == context.manifest["root"]["old_space_id"]
        assert resource.file_level_path == context.manifest["root"]["old_path"]
        self.applied.append(context)
        if context.step_code == self.fail_on:
            raise RuntimeError("injected external failure")
        return VerifiedMutationStepResult(result_digest=f"verified:{context.step_code}")

    async def compensate(self, context: MutationStepContext) -> VerifiedMutationStepResult:
        resource = await _row(self.engine, KnowledgeFile, context.resource_id)
        assert resource.file_name == context.manifest["root"]["old_name"]
        assert resource.knowledge_id == context.manifest["root"]["old_space_id"]
        self.compensated.append(context)
        return VerifiedMutationStepResult(result_digest=f"compensated:{context.step_code}")


class _AuthoritativeOwner:
    def __init__(self) -> None:
        self.executed: list[MutationStepContext] = []
        self.compensated: list[MutationStepContext] = []
        self.cutover_prepared: list[MutationStepContext] = []
        self.cutover_finalized: list[MutationStepContext] = []
        self.cutover_cleaned: list[MutationStepContext] = []
        self.cutover_rolled_back: list[MutationStepContext] = []
        self.fail_finalize_once = False
        self.fail_cleanup_once = False
        self.crash_prepare_once: BaseException | None = None

    async def execute_and_verify(self, context: MutationStepContext) -> VerifiedMutationStepResult:
        self.executed.append(context)
        return VerifiedMutationStepResult(result_digest=f"owner:{context.step_code}")

    async def compensate_and_verify(self, context: MutationStepContext) -> VerifiedMutationStepResult:
        self.compensated.append(context)
        return VerifiedMutationStepResult(result_digest=f"owner-compensated:{context.step_code}")

    async def prepare_cutover_and_verify(self, context: MutationStepContext) -> VerifiedMutationStepResult:
        self.cutover_prepared.append(context)
        if self.crash_prepare_once is not None:
            crash = self.crash_prepare_once
            self.crash_prepare_once = None
            raise crash
        return VerifiedMutationStepResult(result_digest="owner-cutover-prepared")

    async def rollback_cutover_and_verify(self, context: MutationStepContext) -> VerifiedMutationStepResult:
        self.cutover_rolled_back.append(context)
        return VerifiedMutationStepResult(result_digest="owner-cutover-rolled-back")

    async def finalize_cutover_and_verify(self, context: MutationStepContext) -> VerifiedMutationStepResult:
        self.cutover_finalized.append(context)
        if self.fail_finalize_once:
            self.fail_finalize_once = False
            raise RuntimeError("injected owner finalization crash")
        return VerifiedMutationStepResult(result_digest="owner-cutover-finalized")

    async def cleanup_cutover_and_verify(self, context: MutationStepContext) -> VerifiedMutationStepResult:
        self.cutover_cleaned.append(context)
        if self.fail_cleanup_once:
            self.fail_cleanup_once = False
            raise RuntimeError("injected owner cleanup crash")
        return VerifiedMutationStepResult(result_digest="owner-cutover-cleaned")


async def _allow_execution(**_kwargs) -> None:
    return None


async def _complete_execution(**_kwargs) -> bool:
    return True


def _executor(engine, effects, *, after_step_effect=None):
    owner = _AuthoritativeOwner()
    return KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(engine),
        execution_token_factory=lambda: "rename-move-token",
        deadline_factory=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        execution_validator=_allow_execution,
        mutation_execution_validator=_allow_execution,
        mutation_step_applier=effects.apply if effects is not None else None,
        mutation_step_compensator=effects.compensate if effects is not None else None,
        after_step_effect=after_step_effect,
        mutation_step_owner=owner,
    )


async def test_rename_prepares_and_verifies_indexes_before_atomic_name_cutover(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    effects = _VerifiedEffects(saga_engine)

    result = await _executor(saga_engine, effects).execute(
        request_id=request_id,
    )

    assert isinstance(result, MutationExecutionCompleted)
    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "new.pdf"
    request = await _row(saga_engine, KnowledgeSpaceFileChangeRequest, request_id)
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED
    assert [context.step_code for context in effects.applied] == [
        RenameExecutionStepCode.INDEX_SHADOW,
        RenameExecutionStepCode.VERIFY,
    ]
    steps = await _steps(saga_engine, request_id)
    assert {step.state for step in steps} == {KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED}
    assert {step.idempotency_key for step in steps} == {
        f"f046:{request_id}:{code}" for code in RenameExecutionStepCode.ALL
    }


async def test_public_verified_mutation_cutover_finishes_coordinator_driven_rename(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    executor = _executor(saga_engine, None)

    deferred = await executor.execute(
        request_id=request_id,
    )
    assert isinstance(deferred, MutationExecutionDispatch)
    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        async with session.begin():
            steps = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceFileChangeExecutionStep).where(
                            KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                        )
                    )
                ).all()
            )
            for step in steps:
                if step.step_code in RenameExecutionStepCode.EXTERNAL:
                    step.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                    step.result_digest = f"verified:{step.step_code}"
                    session.add(step)

    assert await executor.cutover_verified_mutation(
        request_id=request_id,
        execution_token=deferred.execution_token,
    )

    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "new.pdf"
    request = await _row(saga_engine, KnowledgeSpaceFileChangeRequest, request_id)
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED
    by_code = {step.step_code: step for step in await _steps(saga_engine, request_id)}
    assert by_code[RenameExecutionStepCode.DB_CUTOVER].state == (KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED)


async def test_cutover_replays_cleanup_after_atomic_db_phase_and_approval_commit(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    owner = _AuthoritativeOwner()
    owner.fail_cleanup_once = True
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "cutover-token",
        deadline_factory=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        mutation_execution_validator=_allow_execution,
        mutation_step_owner=owner,
    )
    deferred = await executor.execute(
        request_id=request_id,
    )
    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        async with session.begin():
            steps = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceFileChangeExecutionStep).where(
                            KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                        )
                    )
                ).all()
            )
            for step in steps:
                if step.step_code in RenameExecutionStepCode.EXTERNAL:
                    step.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                    step.result_digest = f"verified:{step.step_code}"
                    session.add(step)

    with pytest.raises(RuntimeError, match="cleanup crash"):
        await executor.cutover_verified_mutation(
            request_id=request_id,
            execution_token=deferred.execution_token,
        )
    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "new.pdf"
    request = await _row(saga_engine, KnowledgeSpaceFileChangeRequest, request_id)
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED
    assert request.execution_checkpoint["mutation_transition_active"] is True
    assert request.execution_checkpoint["mutation_transition_phase"] == "new_view"

    # Simulate Beat recovery in a fresh worker process: the recovery API
    # reloads the manifest from the durable request using only id + token.
    assert await executor.continue_post_cutover_cleanup(
        request_id=request_id,
        execution_token=deferred.execution_token,
    )
    request = await _row(saga_engine, KnowledgeSpaceFileChangeRequest, request_id)
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED
    assert request.execution_checkpoint["mutation_transition_active"] is False
    assert len(owner.cutover_finalized) == 1
    assert len(owner.cutover_cleaned) == 2
    assert owner.cutover_rolled_back == []
    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        footprints = list(
            (
                await session.exec(
                    select(KnowledgeSpaceFileChangeFootprint).where(
                        KnowledgeSpaceFileChangeFootprint.request_id == request_id
                    )
                )
            ).all()
        )
    assert footprints == []


async def test_cutover_uses_only_knowledge_resource_and_step_locks(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    events: list[str] = []
    armed = False

    async def complete(**_kwargs):
        nonlocal armed
        armed = True
        events.append("instance/outbox")
        return True

    async def validate(**_kwargs):
        events.append("resource")

    original_get = KnowledgeSpaceFileChangeRequestRepository.get_by_id
    original_steps = KnowledgeSpaceFileChangeExecutionStepRepository.list_by_request

    async def observed_get(repository, *args, **kwargs):
        if armed:
            events.append("request")
        return await original_get(repository, *args, **kwargs)

    async def observed_steps(repository, *args, **kwargs):
        if armed:
            events.append("steps")
        return await original_steps(repository, *args, **kwargs)

    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "lock-order-token",
        mutation_execution_validator=validate,
        mutation_step_owner=_AuthoritativeOwner(),
    )
    deferred = await executor.execute(
        request_id=request_id,
    )
    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        async with session.begin():
            for step in await KnowledgeSpaceFileChangeExecutionStepRepository(session).list_by_request(
                tenant_id=42,
                request_id=request_id,
                for_update=True,
            ):
                if step.step_code in RenameExecutionStepCode.EXTERNAL:
                    step.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                    step.result_digest = f"verified:{step.step_code}"
                    session.add(step)

    events.clear()
    with (
        patch.object(KnowledgeSpaceFileChangeRequestRepository, "get_by_id", new=observed_get),
        patch.object(KnowledgeSpaceFileChangeExecutionStepRepository, "list_by_request", new=observed_steps),
    ):
        assert await executor.cutover_verified_mutation(
            request_id=request_id,
            execution_token=deferred.execution_token,
        )

    assert events[0] == "resource"
    assert "instance/outbox" not in events


async def test_cutover_commit_ack_loss_reloads_new_view_and_never_rolls_back(saga_engine):
    class _AckLostAfterCommit:
        def __init__(self, transaction) -> None:
            self.transaction = transaction

        async def __aenter__(self):
            return await self.transaction.__aenter__()

        async def __aexit__(self, exc_type, exc, traceback):
            result = await self.transaction.__aexit__(exc_type, exc, traceback)
            if exc_type is None:
                raise RuntimeError("injected commit acknowledgement loss")
            return result

    ack_state = {"armed": False}

    class _AckLossSession(AsyncSession):
        def begin(self):
            transaction = super().begin()
            if ack_state["armed"]:
                ack_state["armed"] = False
                return _AckLostAfterCommit(transaction)
            return transaction

    @asynccontextmanager
    async def ack_loss_factory():
        async with _AckLossSession(bind=saga_engine, expire_on_commit=False) as session:
            yield session

    class _ArmingOwner(_AuthoritativeOwner):
        async def finalize_cutover_and_verify(self, context):
            result = await super().finalize_cutover_and_verify(context)
            ack_state["armed"] = True
            return result

    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    owner = _ArmingOwner()
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=ack_loss_factory,
        execution_token_factory=lambda: "ack-loss-token",
        mutation_execution_validator=_allow_execution,
        mutation_step_owner=owner,
    )
    deferred = await executor.execute(
        request_id=request_id,
    )
    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        async with session.begin():
            for step in await KnowledgeSpaceFileChangeExecutionStepRepository(session).list_by_request(
                tenant_id=42,
                request_id=request_id,
                for_update=True,
            ):
                if step.step_code in RenameExecutionStepCode.EXTERNAL:
                    step.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                    step.result_digest = f"verified:{step.step_code}"
                    session.add(step)

    assert await executor.cutover_verified_mutation(
        request_id=request_id,
        execution_token=deferred.execution_token,
    )

    request = await _row(saga_engine, KnowledgeSpaceFileChangeRequest, request_id)
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED
    assert request.execution_checkpoint["mutation_transition_active"] is False
    assert owner.cutover_rolled_back == []
    assert len(owner.cutover_cleaned) == 1


async def test_parent_boundary_process_crash_keeps_old_view_and_hides_target(saga_engine):
    class SimulatedProcessCrash(BaseException):
        pass

    set_current_tenant_id(42)
    request_id = await _seed_cross_space_folder_move(saga_engine)
    owner = _AuthoritativeOwner()
    owner.crash_prepare_once = SimulatedProcessCrash()
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "move-token",
        deadline_factory=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        mutation_execution_validator=_allow_execution,
        mutation_step_owner=owner,
    )
    deferred = await executor.execute(
        request_id=request_id,
    )
    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        async with session.begin():
            steps = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceFileChangeExecutionStep).where(
                            KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                        )
                    )
                ).all()
            )
            for step in steps:
                if step.step_code in MoveExecutionStepCode.EXTERNAL:
                    step.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                    session.add(step)

    with pytest.raises(SimulatedProcessCrash):
        await executor.cutover_verified_mutation(
            request_id=request_id,
            execution_token=deferred.execution_token,
        )

    folder = await _row(saga_engine, KnowledgeFile, 101)
    assert (folder.knowledge_id, folder.file_level_path) == (10, "")
    from bisheng.knowledge.domain.services.knowledge_space_mutation_read_projection_service import (
        MutationReadProjectionService,
    )

    projection = MutationReadProjectionService(session_factory=_session_factory(saga_engine))
    assert await projection.list_invisible_ids(tenant_id=42, space_ids=[10]) == set()
    assert 101 in await projection.list_invisible_ids(tenant_id=42, space_ids=[20])


async def test_catchable_db_cutover_failure_restores_old_visibility_fence(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_cross_space_folder_move(saga_engine)
    owner = _AuthoritativeOwner()

    validation_calls = 0

    async def reject_cutover(**_kwargs):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls > 1:
            raise RuntimeError("injected DB validation rollback")

    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "move-token",
        deadline_factory=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        mutation_execution_validator=reject_cutover,
        mutation_step_owner=owner,
    )
    deferred = await executor.execute(
        request_id=request_id,
    )
    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        async with session.begin():
            steps = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceFileChangeExecutionStep).where(
                            KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                        )
                    )
                ).all()
            )
            for step in steps:
                if step.step_code in MoveExecutionStepCode.EXTERNAL:
                    step.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                    session.add(step)

    with pytest.raises(RuntimeError, match="DB validation rollback"):
        await executor.cutover_verified_mutation(
            request_id=request_id,
            execution_token=deferred.execution_token,
        )
    folder = await _row(saga_engine, KnowledgeFile, 101)
    assert (folder.knowledge_id, folder.file_level_path) == (10, "")
    request = await _row(saga_engine, KnowledgeSpaceFileChangeRequest, request_id)
    assert request.execution_checkpoint["mutation_transition_active"] is False
    assert len(owner.cutover_rolled_back) == 1


async def test_folder_rename_is_one_root_cutover_and_does_not_rewrite_descendant_paths(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine, resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER)
    effects = _VerifiedEffects(saga_engine)

    result = await _executor(saga_engine, effects).execute(
        request_id=request_id,
    )

    assert isinstance(result, MutationExecutionCompleted)
    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "new-folder"
    child = await _row(saga_engine, KnowledgeFile, 102)
    assert child.file_name == "child.pdf"
    assert child.file_level_path == "/101"


async def test_external_failure_compensates_prepared_steps_and_keeps_old_name(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    effects = _VerifiedEffects(saga_engine)
    effects.fail_on = RenameExecutionStepCode.VERIFY

    with pytest.raises(RuntimeError, match="injected external failure"):
        await _executor(saga_engine, effects).execute(
            request_id=request_id,
        )

    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "old.pdf"
    request = await _row(saga_engine, KnowledgeSpaceFileChangeRequest, request_id)
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED
    assert [context.step_code for context in effects.compensated] == [RenameExecutionStepCode.INDEX_SHADOW]


async def test_partial_move_step_failure_compensates_the_failed_step_and_prior_preparations(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_cross_space_folder_move(saga_engine)
    effects = _VerifiedEffects(saga_engine)
    effects.fail_on = MoveExecutionStepCode.INDEX

    with pytest.raises(RuntimeError, match="injected external failure"):
        await _executor(saga_engine, effects).execute(
            request_id=request_id,
        )

    assert [context.step_code for context in effects.compensated] == [
        MoveExecutionStepCode.INDEX,
        MoveExecutionStepCode.STORAGE,
        MoveExecutionStepCode.TAGS,
        MoveExecutionStepCode.PARENT_TUPLE,
    ]
    folder = await _row(saga_engine, KnowledgeFile, 101)
    assert (folder.knowledge_id, folder.file_level_path) == (10, "")


async def test_failed_rename_resumes_with_new_token_and_stable_step_idempotency_keys(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    first_effects = _VerifiedEffects(saga_engine)
    first_effects.fail_on = RenameExecutionStepCode.VERIFY
    executor = _executor(saga_engine, first_effects)
    with pytest.raises(RuntimeError, match="injected external failure"):
        await executor.execute(
            request_id=request_id,
        )
    original_keys = {step.step_code: step.idempotency_key for step in await _steps(saga_engine, request_id)}

    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        async with session.begin():
            resumed = await executor.prepare_mutation_resume_in_uow(
                session=session,
                request_id=request_id,
                new_token="second-generation",
            )
    assert isinstance(resumed, MutationExecutionDispatch)
    assert resumed.execution_token == "second-generation"

    second_effects = _VerifiedEffects(saga_engine)
    resumed_executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "must-not-be-used",
        deadline_factory=lambda: datetime(2026, 8, 12, tzinfo=UTC),
        mutation_execution_validator=_allow_execution,
        mutation_step_applier=second_effects.apply,
        mutation_step_compensator=second_effects.compensate,
        mutation_step_owner=_AuthoritativeOwner(),
    )
    result = await resumed_executor.execute(
        request_id=request_id,
    )

    assert isinstance(result, MutationExecutionCompleted)
    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "new.pdf"
    resumed_steps = await _steps(saga_engine, request_id)
    assert {step.step_code: step.idempotency_key for step in resumed_steps} == original_keys
    assert {step.attempt_token for step in resumed_steps} == {"second-generation"}


async def test_crash_after_effect_before_ack_replays_same_idempotency_key_without_early_cutover(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    effects = _VerifiedEffects(saga_engine)

    class SimulatedProcessCrash(BaseException):
        pass

    crash_once = True

    def crash_after_first_effect(context):
        nonlocal crash_once
        if crash_once and context.step_code == RenameExecutionStepCode.INDEX_SHADOW:
            crash_once = False
            raise SimulatedProcessCrash()

    executor = _executor(saga_engine, effects, after_step_effect=crash_after_first_effect)
    with pytest.raises(SimulatedProcessCrash):
        await executor.execute(
            request_id=request_id,
        )

    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "old.pdf"
    result = await executor.execute(
        request_id=request_id,
    )
    assert isinstance(result, MutationExecutionCompleted)
    shadow_keys = [
        context.idempotency_key
        for context in effects.applied
        if context.step_code == RenameExecutionStepCode.INDEX_SHADOW
    ]
    assert shadow_keys == [f"f046:{request_id}:rename.index_shadow"] * 2


async def test_executor_never_treats_enqueue_ack_as_verified_side_effect_completion(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)

    async def enqueue_only(_context):
        return "celery-task-id"

    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "token",
        execution_validator=_allow_execution,
        mutation_execution_validator=_allow_execution,
        mutation_step_applier=enqueue_only,
    )
    with pytest.raises(TypeError, match="verified mutation step result"):
        await executor.execute(
            request_id=request_id,
        )
    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "old.pdf"


async def test_worker_owner_step_reloads_current_durable_context_and_returns_verified_result(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    owner = _AuthoritativeOwner()
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "owner-token",
        deadline_factory=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        mutation_execution_validator=_allow_execution,
        mutation_step_owner=owner,
    )
    deferred = await executor.execute(
        request_id=request_id,
    )

    result = await executor.execute_and_verify_step(
        ExecutionStepContext(
            tenant_id=42,
            request_id=request_id,
            execution_token=deferred.execution_token,
            action="rename",
            step_code=RenameExecutionStepCode.INDEX_SHADOW,
            idempotency_key=f"f046:{request_id}:rename.index_shadow",
            task_id="untrusted-broker-receipt",
        )
    )

    assert result == VerifiedExecutionStepResult("owner:rename.index_shadow")
    assert len(owner.executed) == 1
    durable = owner.executed[0]
    assert durable.execution_token == "owner-token"
    assert durable.manifest["new_name"] == "new.pdf"
    assert durable.idempotency_key == f"f046:{request_id}:rename.index_shadow"


async def test_worker_owner_step_rejects_forged_broker_identity_before_side_effect(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    owner = _AuthoritativeOwner()
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "owner-token",
        deadline_factory=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        mutation_execution_validator=_allow_execution,
        mutation_step_owner=owner,
    )
    await executor.execute(
        request_id=request_id,
    )

    with pytest.raises(RuntimeError, match="durable step identity"):
        await executor.execute_and_verify_step(
            ExecutionStepContext(
                tenant_id=42,
                request_id=request_id,
                execution_token="owner-token",
                action="move",
                step_code=RenameExecutionStepCode.INDEX_SHADOW,
                idempotency_key="forged-key",
                task_id=None,
            )
        )

    assert owner.executed == []


async def test_public_compensation_reloads_manifest_and_reverses_durable_steps(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    owner = _AuthoritativeOwner()
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "owner-token",
        deadline_factory=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        mutation_execution_validator=_allow_execution,
        mutation_step_owner=owner,
    )
    await executor.execute(
        request_id=request_id,
    )
    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        async with session.begin():
            request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
            request.execution_state = KnowledgeSpaceFileChangeExecutionState.COMPENSATING
            session.add(request)
            rows = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceFileChangeExecutionStep).where(
                            KnowledgeSpaceFileChangeExecutionStep.request_id == request_id
                        )
                    )
                ).all()
            )
            shadow = next(row for row in rows if row.step_code == RenameExecutionStepCode.INDEX_SHADOW)
            shadow.state = KnowledgeSpaceFileChangeExecutionStepState.COMPENSATING
            session.add(shadow)

    assert await executor.continue_compensation(request_id=request_id, execution_token="owner-token")
    request = await _row(saga_engine, KnowledgeSpaceFileChangeRequest, request_id)
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED
    by_code = {step.step_code: step for step in await _steps(saga_engine, request_id)}
    assert by_code[RenameExecutionStepCode.INDEX_SHADOW].state == (
        KnowledgeSpaceFileChangeExecutionStepState.COMPENSATED
    )
    assert [context.step_code for context in owner.compensated] == [RenameExecutionStepCode.INDEX_SHADOW]


async def test_cross_space_folder_move_cuts_over_subtree_version_chain_and_document_last(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_cross_space_folder_move(saga_engine)
    effects = _VerifiedEffects(saga_engine)

    result = await _executor(saga_engine, effects).execute(
        request_id=request_id,
    )

    assert isinstance(result, MutationExecutionCompleted)
    folder = await _row(saga_engine, KnowledgeFile, 101)
    child = await _row(saga_engine, KnowledgeFile, 102)
    historical = await _row(saga_engine, KnowledgeFile, 103)
    document = await _row(saga_engine, KnowledgeDocument, 1)
    assert (folder.knowledge_id, folder.file_level_path, folder.level) == (20, "/201", 1)
    assert (child.knowledge_id, child.file_level_path, child.level) == (20, "/201/101", 2)
    assert (historical.knowledge_id, historical.file_level_path, historical.level) == (20, "/201/101", 2)
    assert (document.knowledge_id, document.file_level_path, document.level) == (20, "/201/101", 2)
    assert [context.step_code for context in effects.applied] == [
        MoveExecutionStepCode.PARENT_TUPLE,
        MoveExecutionStepCode.TAGS,
        MoveExecutionStepCode.STORAGE,
        MoveExecutionStepCode.INDEX,
        MoveExecutionStepCode.VERIFY,
    ]
    assert effects.applied[0].manifest["tag_snapshot"] == {"102": [9], "103": [10]}


async def test_move_target_removed_after_approval_fails_before_steps_and_keeps_source(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_cross_space_folder_move(saga_engine)
    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        async with session.begin():
            target = await session.get(KnowledgeFile, 201)
            await session.delete(target)
    effects = _VerifiedEffects(saga_engine)

    with pytest.raises(LookupError, match="target folder"):
        await _executor(saga_engine, effects).execute(
            request_id=request_id,
        )

    folder = await _row(saga_engine, KnowledgeFile, 101)
    assert (folder.knowledge_id, folder.file_level_path) == (10, "")
    assert await _steps(saga_engine, request_id) == []
    assert effects.applied == []


async def test_move_version_chain_fails_closed_when_a_sibling_crosses_tenant_boundary(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_cross_space_folder_move(saga_engine)
    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        async with session.begin():
            foreign_file = await _add_file(
                session,
                id=104,
                tenant_id=99,
                knowledge_id=10,
                file_name="foreign-v3.pdf",
                file_level_path="/101",
                level=1,
            )
            session.add(
                KnowledgeDocumentVersion(
                    document_id=1,
                    knowledge_file_id=int(foreign_file.id),
                    version_no=3,
                    is_primary=False,
                )
            )
    effects = _VerifiedEffects(saga_engine)

    with pytest.raises(ValueError, match="version chain crosses the tenant"):
        await _executor(saga_engine, effects).execute(
            request_id=request_id,
        )

    assert await _steps(saga_engine, request_id) == []
    folder = await _row(saga_engine, KnowledgeFile, 101)
    assert (folder.knowledge_id, folder.file_level_path) == (10, "")


async def test_move_rechecks_target_name_after_external_preparation_and_compensates(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_cross_space_folder_move(saga_engine)
    effects = _VerifiedEffects(saga_engine)
    conflict_created = False

    async def create_conflict_after_verify(context):
        nonlocal conflict_created
        if conflict_created or context.step_code != MoveExecutionStepCode.VERIFY:
            return
        conflict_created = True
        async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
            async with session.begin():
                await _add_file(
                    session,
                    id=299,
                    knowledge_id=20,
                    file_name="folder",
                    file_type=FileType.DIR.value,
                    file_level_path="/201",
                    level=1,
                )

    with pytest.raises(ValueError, match="now contains a folder with the same name"):
        await _executor(
            saga_engine,
            effects,
            after_step_effect=create_conflict_after_verify,
        ).execute(
            request_id=request_id,
        )

    folder = await _row(saga_engine, KnowledgeFile, 101)
    assert (folder.knowledge_id, folder.file_level_path) == (10, "")
    assert [context.step_code for context in effects.compensated] == [
        MoveExecutionStepCode.INDEX,
        MoveExecutionStepCode.STORAGE,
        MoveExecutionStepCode.TAGS,
        MoveExecutionStepCode.PARENT_TUPLE,
    ]


async def test_runtime_revalidation_rejects_revoked_rename_permission_before_steps(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    effects = _VerifiedEffects(saga_engine)
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "token",
        mutation_step_applier=effects.apply,
        mutation_step_compensator=effects.compensate,
        mutation_step_owner=_AuthoritativeOwner(),
    )

    with (
        patch(
            "bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository.KnowledgeSpaceMutationRepository.get_current_user_role_ids",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.has_effective_action_strict",
            new_callable=AsyncMock,
            return_value=False,
        ) as permission_check,
    ):
        with pytest.raises(SpacePermissionDeniedError):
            await executor.execute(
                request_id=request_id,
            )

    permission_check.assert_awaited_once()
    assert permission_check.await_args.args == ("knowledge_file", 101, "rename")
    assert permission_check.await_args.kwargs["space_id"] == 10
    assert permission_check.await_args.kwargs["locked_space"] is not None
    assert await _steps(saga_engine, request_id) == []
    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "old.pdf"


async def test_runtime_revalidation_rejects_unpublished_move_target_before_steps(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_cross_space_folder_move(saga_engine)
    async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
        async with session.begin():
            target_space = await session.get(Knowledge, 20)
            target_space.state = KnowledgeState.UNPUBLISHED.value
            session.add(target_space)
    effects = _VerifiedEffects(saga_engine)
    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "token",
        mutation_step_applier=effects.apply,
        mutation_step_compensator=effects.compensate,
        mutation_step_owner=_AuthoritativeOwner(),
    )

    with (
        patch(
            "bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository.KnowledgeSpaceMutationRepository.get_current_user_role_ids",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.has_effective_action_strict",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        with pytest.raises(SpaceNotFoundError):
            await executor.execute(
                request_id=request_id,
            )

    assert await _steps(saga_engine, request_id) == []
    folder = await _row(saga_engine, KnowledgeFile, 101)
    assert (folder.knowledge_id, folder.file_level_path) == (10, "")


async def test_cutover_revalidates_revoked_permission_and_compensates_old_name(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)
    effects = _VerifiedEffects(saga_engine)
    permission_revoked = False

    async def current_permission(*_args, **_kwargs):
        return not permission_revoked

    def revoke_after_verify(context):
        nonlocal permission_revoked
        if context.step_code == RenameExecutionStepCode.VERIFY:
            permission_revoked = True

    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "token",
        mutation_step_applier=effects.apply,
        mutation_step_compensator=effects.compensate,
        after_step_effect=revoke_after_verify,
        mutation_step_owner=_AuthoritativeOwner(),
    )
    with (
        patch(
            "bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository.KnowledgeSpaceMutationRepository.get_current_user_role_ids",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.has_effective_action_strict",
            new_callable=AsyncMock,
            side_effect=current_permission,
        ) as permission_check,
    ):
        with pytest.raises(SpacePermissionDeniedError):
            await executor.execute(
                request_id=request_id,
            )

    assert permission_check.await_count == 2
    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "old.pdf"
    assert [context.step_code for context in effects.compensated] == [RenameExecutionStepCode.INDEX_SHADOW]
    request = await _row(saga_engine, KnowledgeSpaceFileChangeRequest, request_id)
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED


async def test_cutover_revalidates_target_space_state_and_compensates_old_position(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_cross_space_folder_move(saga_engine)
    effects = _VerifiedEffects(saga_engine)
    target_disabled = False

    async def disable_target_after_verify(context):
        nonlocal target_disabled
        if target_disabled or context.step_code != MoveExecutionStepCode.VERIFY:
            return
        target_disabled = True
        async with AsyncSession(bind=saga_engine, expire_on_commit=False) as session:
            async with session.begin():
                target_space = await session.get(Knowledge, 20)
                target_space.state = KnowledgeState.UNPUBLISHED.value
                session.add(target_space)

    executor = KnowledgeSpaceMutationExecutor(
        session_factory=_session_factory(saga_engine),
        execution_token_factory=lambda: "token",
        mutation_step_applier=effects.apply,
        mutation_step_compensator=effects.compensate,
        after_step_effect=disable_target_after_verify,
        mutation_step_owner=_AuthoritativeOwner(),
    )
    with (
        patch(
            "bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository.KnowledgeSpaceMutationRepository.get_current_user_role_ids",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.has_effective_action_strict",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        with pytest.raises(SpaceNotFoundError):
            await executor.execute(
                request_id=request_id,
            )

    folder = await _row(saga_engine, KnowledgeFile, 101)
    child = await _row(saga_engine, KnowledgeFile, 102)
    assert (folder.knowledge_id, folder.file_level_path) == (10, "")
    assert (child.knowledge_id, child.file_level_path) == (10, "/101")
    assert [context.step_code for context in effects.compensated] == [
        MoveExecutionStepCode.INDEX,
        MoveExecutionStepCode.STORAGE,
        MoveExecutionStepCode.TAGS,
        MoveExecutionStepCode.PARENT_TUPLE,
    ]


async def test_without_inline_runner_rename_is_deferred_and_never_cuts_over(saga_engine):
    set_current_tenant_id(42)
    request_id = await _seed_rename(saga_engine)

    result = await _executor(saga_engine, None).execute(
        request_id=request_id,
    )

    assert isinstance(result, MutationExecutionDispatch)
    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "old.pdf"
    assert {step.state for step in await _steps(saga_engine, request_id)} == {
        KnowledgeSpaceFileChangeExecutionStepState.PENDING
    }


async def test_rename_executor_never_falls_back_to_another_tenant(saga_engine):
    request_id = await _seed_rename(saga_engine)
    set_current_tenant_id(99)
    effects = _VerifiedEffects(saga_engine)

    with pytest.raises(LookupError, match="request not found"):
        await _executor(saga_engine, effects).execute(
            request_id=request_id,
        )

    set_current_tenant_id(42)
    assert (await _row(saga_engine, KnowledgeFile, 101)).file_name == "old.pdf"
    assert await _steps(saga_engine, request_id) == []
