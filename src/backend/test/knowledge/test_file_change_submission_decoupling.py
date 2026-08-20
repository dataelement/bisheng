from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
)
from bisheng.approval.domain.ports.scenario_policy import (
    DECISION_DELIVERY_COMPLETION_MODE,
    ApprovalSubmissionCommand,
    ApprovalSubmissionResult,
)
from bisheng.common.errcode.knowledge_space import (
    SpaceFileChangeConflictError,
    SpacePermissionDeniedError,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_file_change_policy import (
    KnowledgeSpaceFileChangePolicy,
    KnowledgeSpaceFileChangeSetting,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE,
    KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
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
)
from bisheng.knowledge.domain.repositories.knowledge_space_upload_stage_repository import (
    KnowledgeSpaceUploadStageRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_service import (
    FileChangeRequestCommand,
    KnowledgeSpaceFileChangeService,
)

TENANT_ID = 17
SPACE_ID = 101
APPLICANT_ID = 9
INITIAL_APPROVERS = (201, 202)


@pytest_asyncio.fixture
async def submission_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Knowledge.__table__,
        KnowledgeSpaceFileChangePolicy.__table__,
        KnowledgeSpaceFileChangeSetting.__table__,
        KnowledgeSpaceUploadStage.__table__,
        KnowledgeSpaceFileChangeRequest.__table__,
        KnowledgeSpaceFileChangeFootprint.__table__,
        ApprovalInstance.__table__,
        ApprovalOutbox.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=tables))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def tenant_context():
    token = set_current_tenant_id(TENANT_ID)
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


async def _seed_space(engine, *, space_id: int = SPACE_ID) -> None:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session, session.begin():
        session.add(
            Knowledge(
                id=space_id,
                tenant_id=TENANT_ID,
                user_id=1,
                name=f"space-{space_id}",
                type=KnowledgeTypeEnum.SPACE.value,
                auth_type=AuthTypeEnum.PUBLIC,
            )
        )


async def _seed_stage(engine, *, upload_id: str = "upload-opaque-1") -> None:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session, session.begin():
        session.add(
            KnowledgeSpaceUploadStage(
                tenant_id=TENANT_ID,
                space_id=SPACE_ID,
                uploader_user_id=APPLICANT_ID,
                upload_id=upload_id,
                object_name=f"stage/{TENANT_ID}/{upload_id}",
                file_name="quarterly.pdf",
                file_size=42,
                content_hash="hash",
                state=KnowledgeSpaceUploadStageState.UPLOADED,
                expire_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
            )
        )


class RecordingSubmissionPort:
    def __init__(self, engine, *, fail: bool = False) -> None:
        self.engine = engine
        self.fail = fail
        self.commands: list[ApprovalSubmissionCommand] = []
        self.observed: list[dict[str, Any]] = []
        self.effects_seen: list[str] = []

    async def submit_in_uow(
        self,
        *,
        session: AsyncSession,
        command: ApprovalSubmissionCommand,
    ) -> ApprovalSubmissionResult:
        assert session.in_transaction()
        request_id = int(command.business_request_id)
        request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
        assert request is not None
        footprints = (
            await session.exec(
                select(KnowledgeSpaceFileChangeFootprint).where(
                    KnowledgeSpaceFileChangeFootprint.request_id == request_id
                )
            )
        ).all()
        stage = None
        if request.upload_stage_id is not None:
            stage = await session.get(KnowledgeSpaceUploadStage, int(request.upload_stage_id))
        self.commands.append(command)
        self.observed.append(
            {
                "request_id": request_id,
                "footprint_count": len(footprints),
                "stage_state": stage.state if stage is not None else None,
            }
        )
        instance = ApprovalInstance(
            tenant_id=command.tenant_id,
            scenario_code=command.scenario_code,
            scenario_name="file change",
            handler_key=command.scenario_code,
            business_key=command.business_key,
            business_resource_type=command.business_request_type,
            business_resource_id=command.business_request_id,
            business_name=command.title,
            applicant_user_id=command.applicant.user_id,
            applicant_user_name=command.applicant.user_name,
            applicant_department_id=command.applicant.department_id,
            status=ApprovalInstanceStatus.PENDING,
        )
        session.add(instance)
        await session.flush()
        if self.fail:
            raise RuntimeError("submission failed")

        async def effect() -> None:
            async with AsyncSession(bind=self.engine) as verify_session:
                assert await verify_session.get(ApprovalInstance, int(instance.id)) is not None
            self.effects_seen.append("submission.effect")

        return ApprovalSubmissionResult(
            instance_id=int(instance.id),
            task_ids=(701,),
            post_commit_effects=(effect,),
        )

    @asynccontextmanager
    async def scenario_guard(self, *, tenant_id: int, scenario_code: str):
        assert tenant_id == TENANT_ID
        assert scenario_code == KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE
        yield


class RequiredPolicy:
    async def is_approval_required(self, *, space_id: int, session=None) -> bool:
        assert space_id > 0
        return True


def _command(action: str) -> FileChangeRequestCommand:
    common = {
        "action": action,
        "space_id": SPACE_ID,
        "applicant_user_id": APPLICANT_ID,
        "applicant_user_name": "editor",
        "resource_name": "quarterly.pdf",
        "source_parent_id": 10,
        "action_snapshot": {"old_name": "quarterly.pdf", "new_name": "annual.pdf"},
    }
    if action == KnowledgeSpaceFileChangeAction.UPLOAD:
        return FileChangeRequestCommand(
            **common,
            resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
            upload_id="upload-opaque-1",
        )
    if action == KnowledgeSpaceFileChangeAction.MOVE:
        return FileChangeRequestCommand(
            **common,
            resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
            resource_id=501,
            target_space_id=SPACE_ID,
            target_parent_id=20,
        )
    return FileChangeRequestCommand(
        **common,
        resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
        resource_id=501,
    )


def _service(
    engine,
    *,
    submission_port: RecordingSubmissionPort,
    authorized: bool = True,
) -> KnowledgeSpaceFileChangeService:
    async def authorize(_command):
        if not authorized:
            raise SpacePermissionDeniedError()

    async def is_owner_or_manager(_command):
        return False

    async def resolve_footprint(command):
        return [
            FootprintEntry(
                space_id=command.space_id,
                resource_type=command.resource_type,
                resource_id=command.resource_id,
                path_root="/10/501/",
                lock_scope=KnowledgeSpaceFileChangeLockScope.EXACT,
            )
        ]

    async def resolve_approvers(**kwargs):
        assert kwargs == {
            "tenant_id": TENANT_ID,
            "space_id": SPACE_ID,
            "applicant_user_id": APPLICANT_ID,
        }
        return list(INITIAL_APPROVERS)

    async def direct(command):
        return {"id": command.resource_id or command.upload_id}

    async def retain_stage(upload_id: str):
        async with AsyncSession(bind=engine, expire_on_commit=False) as session, session.begin():
            stage = await KnowledgeSpaceUploadStageRepository(session).get_by_upload_id(
                tenant_id=TENANT_ID,
                upload_id=upload_id,
                for_update=True,
            )
            assert stage is not None
            stage.state = KnowledgeSpaceUploadStageState.ATTACHED
            await KnowledgeSpaceUploadStageRepository(session).save(stage)

    return KnowledgeSpaceFileChangeService(
        session_factory=_session_factory(engine),
        submission_port=submission_port,
        approver_resolver=resolve_approvers,
        policy_service=RequiredPolicy(),
        mutation_authorizer=authorize,
        owner_manager_checker=is_owner_or_manager,
        footprint_resolver=resolve_footprint,
        direct_executor=direct,
        stage_retainer=retain_stage,
    )


async def _all(engine, model):
    async with AsyncSession(bind=engine) as session:
        return (await session.exec(select(model))).all()


@pytest.mark.parametrize(
    "action",
    [
        KnowledgeSpaceFileChangeAction.UPLOAD,
        KnowledgeSpaceFileChangeAction.RENAME,
        KnowledgeSpaceFileChangeAction.MOVE,
        KnowledgeSpaceFileChangeAction.DELETE,
    ],
)
async def test_all_actions_submit_knowledge_owned_command_with_initial_approvers(
    submission_engine,
    action: str,
) -> None:
    await _seed_space(submission_engine)
    if action == KnowledgeSpaceFileChangeAction.UPLOAD:
        await _seed_stage(submission_engine)
    port = RecordingSubmissionPort(submission_engine)

    result = await _service(submission_engine, submission_port=port).request_change(_command(action))

    assert result.decision == "pending"
    assert len(port.commands) == 1
    command = port.commands[0]
    assert command.scenario_code == KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE
    assert command.business_request_type == KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE
    assert command.completion_mode == DECISION_DELIVERY_COMPLETION_MODE
    assert command.initial_approver_user_ids == INITIAL_APPROVERS
    assert command.link_snapshot["space_id"] == SPACE_ID
    assert command.link_snapshot["change_request_id"] == int(command.business_request_id)
    assert command.business_key
    assert command.request_fingerprint
    persisted = (await _all(submission_engine, KnowledgeSpaceFileChangeRequest))[0]
    assert persisted.approval_instance_id == result.approval_instance_id
    assert persisted.business_key == command.business_key
    assert persisted.request_fingerprint == command.request_fingerprint
    assert persisted.execution_state == KnowledgeSpaceFileChangeExecutionState.NOT_STARTED
    assert persisted.execution_token is None
    assert await _all(submission_engine, ApprovalOutbox) == []


async def test_request_stage_footprint_and_approval_bundle_share_one_commit(
    submission_engine,
) -> None:
    await _seed_space(submission_engine)
    await _seed_stage(submission_engine)
    port = RecordingSubmissionPort(submission_engine)

    await _service(submission_engine, submission_port=port).request_change(
        _command(KnowledgeSpaceFileChangeAction.UPLOAD)
    )

    assert port.observed == [
        {
            "request_id": port.observed[0]["request_id"],
            "footprint_count": 1,
            "stage_state": KnowledgeSpaceUploadStageState.ATTACHING,
        }
    ]
    assert len(await _all(submission_engine, KnowledgeSpaceFileChangeRequest)) == 1
    assert len(await _all(submission_engine, KnowledgeSpaceFileChangeFootprint)) == 1
    assert len(await _all(submission_engine, ApprovalInstance)) == 1
    assert port.effects_seen == ["submission.effect"]


async def test_submission_failure_rolls_back_request_stage_footprint_and_approval_bundle(
    submission_engine,
) -> None:
    await _seed_space(submission_engine)
    await _seed_stage(submission_engine)
    port = RecordingSubmissionPort(submission_engine, fail=True)

    with pytest.raises(RuntimeError, match="submission failed"):
        await _service(submission_engine, submission_port=port).request_change(
            _command(KnowledgeSpaceFileChangeAction.UPLOAD)
        )

    assert await _all(submission_engine, KnowledgeSpaceFileChangeRequest) == []
    assert await _all(submission_engine, KnowledgeSpaceFileChangeFootprint) == []
    assert await _all(submission_engine, ApprovalInstance) == []
    stage = (await _all(submission_engine, KnowledgeSpaceUploadStage))[0]
    assert stage.state == KnowledgeSpaceUploadStageState.UPLOADED
    assert port.effects_seen == []


async def test_permission_failure_precedes_submission_and_creates_no_rows(submission_engine) -> None:
    await _seed_space(submission_engine)
    port = RecordingSubmissionPort(submission_engine)

    with pytest.raises(SpacePermissionDeniedError):
        await _service(
            submission_engine,
            submission_port=port,
            authorized=False,
        ).request_change(_command(KnowledgeSpaceFileChangeAction.DELETE))

    assert port.commands == []
    assert await _all(submission_engine, KnowledgeSpaceFileChangeRequest) == []
    assert await _all(submission_engine, ApprovalInstance) == []


async def test_existing_footprint_conflict_still_blocks_second_submission(submission_engine) -> None:
    await _seed_space(submission_engine)
    port = RecordingSubmissionPort(submission_engine)
    service = _service(submission_engine, submission_port=port)
    command = _command(KnowledgeSpaceFileChangeAction.DELETE)

    await service.request_change(command)
    with pytest.raises(SpaceFileChangeConflictError):
        await service.request_change(command)

    assert len(port.commands) == 1


def test_submission_path_depends_on_public_approval_port_not_gate_or_deferred() -> None:
    import inspect

    from bisheng.knowledge.domain.services import knowledge_space_file_change_service as service_module
    from bisheng.knowledge.domain.services import knowledge_space_file_change_uow as uow_module

    source = inspect.getsource(service_module) + inspect.getsource(uow_module)
    assert "bisheng.approval.domain.ports" in source
    assert "approval.domain.services.approval_gate" not in source
    assert "approval.domain.services.approval_uow" not in source
    assert "ApprovalGate" not in source
    assert "Deferred" not in source
    assert "ApprovalOutbox" not in source


def test_business_binding_is_canonical_and_request_fingerprint_is_tamper_evident() -> None:
    original = _command(KnowledgeSpaceFileChangeAction.RENAME)
    reordered = replace(
        original,
        action_snapshot={"new_name": "annual.pdf", "old_name": "quarterly.pdf"},
    )
    tampered = replace(
        original,
        action_snapshot={"old_name": "quarterly.pdf", "new_name": "confidential.pdf"},
    )

    business_key = KnowledgeSpaceFileChangeService._business_key(
        tenant_id=TENANT_ID,
        command=original,
    )
    reordered_key = KnowledgeSpaceFileChangeService._business_key(
        tenant_id=TENANT_ID,
        command=reordered,
    )
    original_fingerprint = KnowledgeSpaceFileChangeService._request_fingerprint(
        tenant_id=TENANT_ID,
        business_key=business_key,
        command=original,
        action_snapshot=KnowledgeSpaceFileChangeService._canonical_snapshot(original.action_snapshot),
        stage=None,
    )
    reordered_fingerprint = KnowledgeSpaceFileChangeService._request_fingerprint(
        tenant_id=TENANT_ID,
        business_key=reordered_key,
        command=reordered,
        action_snapshot=KnowledgeSpaceFileChangeService._canonical_snapshot(reordered.action_snapshot),
        stage=None,
    )
    tampered_fingerprint = KnowledgeSpaceFileChangeService._request_fingerprint(
        tenant_id=TENANT_ID,
        business_key=business_key,
        command=tampered,
        action_snapshot=KnowledgeSpaceFileChangeService._canonical_snapshot(tampered.action_snapshot),
        stage=None,
    )

    assert business_key == reordered_key
    assert original_fingerprint == reordered_fingerprint
    assert len(original_fingerprint) == 64
    assert tampered_fingerprint != original_fingerprint
