from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import ApprovalInstance, ApprovalInstanceStatus
from bisheng.approval.domain.ports.scenario_policy import (
    ApprovalSubmissionCommand,
    ApprovalSubmissionResult,
)
from bisheng.common.errcode.knowledge_space import (
    SpaceFileChangeConflictError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_file_change_policy import (
    KnowledgeSpaceFileChangePolicy,
    KnowledgeSpaceFileChangeSetting,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeFootprint,
    KnowledgeSpaceFileChangeLockScope,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import (
    KnowledgeSpaceUploadStage,
    KnowledgeSpaceUploadStageState,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import FootprintEntry
from bisheng.knowledge.domain.repositories.knowledge_space_upload_stage_repository import (
    KnowledgeSpaceUploadStageRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_approver_resolver import (
    KnowledgeSpaceFileChangeApproverResolver,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_service import (
    FileChangeRequestCommand,
    KnowledgeSpaceFileChangeService,
)
from bisheng.permission.domain.services.permission_service import PermissionService


@pytest_asyncio.fixture
async def request_engine():
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


def _session_factory(engine):
    @asynccontextmanager
    async def factory():
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            yield session

    return factory


async def _seed_space(
    engine,
    *,
    tenant_id: int,
    space_id: int,
    auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
    knowledge_type: KnowledgeTypeEnum = KnowledgeTypeEnum.SPACE,
) -> None:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            session.add(
                Knowledge(
                    id=space_id,
                    tenant_id=tenant_id,
                    user_id=1,
                    name=f"space-{space_id}",
                    type=knowledge_type.value,
                    auth_type=auth_type,
                )
            )


async def _seed_stage(engine, *, tenant_id: int, space_id: int, uploader_user_id: int, upload_id: str) -> None:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            session.add(
                KnowledgeSpaceUploadStage(
                    tenant_id=tenant_id,
                    space_id=space_id,
                    uploader_user_id=uploader_user_id,
                    upload_id=upload_id,
                    object_name=f"stage/{tenant_id}/{upload_id}",
                    file_name="quarterly.pdf",
                    file_size=42,
                    content_hash="hash",
                    state=KnowledgeSpaceUploadStageState.UPLOADED,
                    expire_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
                )
            )


class _Policy:
    def __init__(self, required: bool, events: list[str]) -> None:
        self.required = required
        self.events = events

    async def is_approval_required(self, *, space_id: int, session=None) -> bool:
        self.events.append(f"policy:{space_id}")
        return self.required


class _SubmissionPort:
    def __init__(
        self,
        events: list[str],
        *,
        fail: bool = False,
        exception: bool = False,
    ) -> None:
        self.events = events
        self.fail = fail
        self.exception = exception
        self.calls = []

    async def submit_in_uow(self, *, session, command: ApprovalSubmissionCommand):
        self.events.append("submission")
        self.calls.append(command)
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
            status=(ApprovalInstanceStatus.EXCEPTION if self.exception else ApprovalInstanceStatus.PENDING),
        )
        session.add(instance)
        await session.flush()
        if self.fail:
            raise RuntimeError("submission failed")

        async def effect() -> None:
            self.events.append("submission.effect")

        return ApprovalSubmissionResult(
            instance_id=int(instance.id),
            task_ids=() if self.exception else (701,),
            post_commit_effects=(effect,),
        )


def _command(**overrides) -> FileChangeRequestCommand:
    values = {
        "action": KnowledgeSpaceFileChangeAction.DELETE,
        "space_id": 101,
        "applicant_user_id": 9,
        "applicant_user_name": "editor",
        "resource_type": KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
        "resource_id": 501,
        "resource_name": "quarterly.pdf",
        "action_snapshot": {"old_name": "quarterly.pdf"},
    }
    values.update(overrides)
    return FileChangeRequestCommand(**values)


def _service(
    engine,
    *,
    events: list[str],
    authorized: bool = True,
    privileged: bool = False,
    approval_required: bool = True,
    submission_port: _SubmissionPort | None = None,
    footprint_resolver=None,
    retain_failures: list[bool] | None = None,
):
    async def authorize(_command):
        events.append("permission")
        if not authorized:
            raise SpacePermissionDeniedError()

    async def is_owner_or_manager(_command):
        events.append("owner-manager")
        return privileged

    async def resolve(command):
        events.append("footprint")
        return [
            FootprintEntry(
                space_id=command.space_id,
                resource_type=command.resource_type,
                resource_id=command.resource_id,
                path_root="/10/20/",
                lock_scope=KnowledgeSpaceFileChangeLockScope.EXACT,
            )
        ]

    async def direct(command):
        events.append("direct")
        return {"id": command.resource_id or command.upload_id}

    async def resolve_approvers(**_identity):
        return [201]

    async def retain_stage(upload_id: str):
        events.append(f"retain:{upload_id}")
        if retain_failures and retain_failures.pop(0):
            raise RuntimeError("MinIO lifecycle update failed")
        async with _session_factory(engine)() as session:
            async with session.begin():
                stage = await KnowledgeSpaceUploadStageRepository(session).get_by_upload_id(
                    tenant_id=17,
                    upload_id=upload_id,
                    for_update=True,
                )
                assert stage is not None
                assert stage.state == KnowledgeSpaceUploadStageState.ATTACHING
                stage.state = KnowledgeSpaceUploadStageState.ATTACHED
                await KnowledgeSpaceUploadStageRepository(session).save(stage)

    return KnowledgeSpaceFileChangeService(
        session_factory=_session_factory(engine),
        submission_port=submission_port or _SubmissionPort(events),
        approver_resolver=resolve_approvers,
        policy_service=_Policy(approval_required, events),
        mutation_authorizer=authorize,
        owner_manager_checker=is_owner_or_manager,
        footprint_resolver=footprint_resolver or resolve,
        direct_executor=direct,
        stage_retainer=retain_stage,
    )


async def _count_rows(engine, model) -> int:
    async with AsyncSession(bind=engine) as session:
        return len((await session.exec(select(model))).all())


async def test_permission_failure_is_first_and_creates_no_business_or_approval_rows(request_engine):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    events: list[str] = []
    service = _service(request_engine, events=events, authorized=False)

    with pytest.raises(SpacePermissionDeniedError):
        await service.request_change(_command())

    assert events == ["permission"]
    assert await _count_rows(request_engine, KnowledgeSpaceFileChangeRequest) == 0
    assert await _count_rows(request_engine, ApprovalInstance) == 0


@pytest.mark.parametrize(("private", "privileged"), [(True, False), (False, True)])
async def test_private_space_or_current_owner_manager_executes_directly_without_submission(
    request_engine,
    private,
    privileged,
):
    set_current_tenant_id(17)
    await _seed_space(
        request_engine,
        tenant_id=17,
        space_id=101,
        auth_type=AuthTypeEnum.PRIVATE if private else AuthTypeEnum.PUBLIC,
    )
    events: list[str] = []
    service = _service(
        request_engine,
        events=events,
        privileged=privileged,
        approval_required=not private,
    )

    result = await service.request_change(_command())

    assert result.decision == "direct"
    assert result.resource == {"id": 501}
    assert "submission" not in events
    assert events == (["permission", "direct"] if private else ["permission", "owner-manager", "direct"])
    assert await _count_rows(request_engine, KnowledgeSpaceFileChangeRequest) == 0


async def test_public_non_manager_with_approval_disabled_executes_directly_without_creating_request(request_engine):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101, auth_type=AuthTypeEnum.PUBLIC)
    events: list[str] = []
    service = _service(
        request_engine,
        events=events,
        privileged=False,
        approval_required=False,
    )

    result = await service.request_change(_command())

    assert result.decision == "direct"
    assert result.resource == {"id": 501}
    assert events == ["permission", "owner-manager", "policy:101", "direct"]
    assert "submission" not in events
    assert await _count_rows(request_engine, KnowledgeSpaceFileChangeRequest) == 0
    assert await _count_rows(request_engine, ApprovalInstance) == 0


async def test_policy_change_only_affects_subsequent_requests_and_keeps_existing_instance_pending(
    request_engine,
):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    events: list[str] = []
    service = _service(request_engine, events=events, approval_required=True)

    first = await service.request_change(_command(resource_id=501))
    service.policy_service.required = False
    second = await service.request_change(_command(resource_id=502))

    assert first.decision == "pending"
    assert second.decision == "direct"
    async with AsyncSession(bind=request_engine) as session:
        instance = (await session.exec(select(ApprovalInstance))).one()
        assert instance.id == first.approval_instance_id
        assert instance.status == ApprovalInstanceStatus.PENDING
    assert await _count_rows(request_engine, KnowledgeSpaceFileChangeRequest) == 1


async def test_personal_space_owner_executes_directly_while_editor_uses_current_policy(
    request_engine,
):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    events: list[str] = []
    service = _service(request_engine, events=events, approval_required=True)

    async def is_current_owner_or_manager(command):
        return await KnowledgeSpaceFileChangeApproverResolver.is_current_approver(
            tenant_id=17,
            space_id=command.space_id,
            user_id=command.applicant_user_id,
        )

    service.owner_manager_checker = is_current_owner_or_manager
    with (
        patch.object(
            PermissionService,
            "resolve_resource_relation_user_ids_strict",
            new=AsyncMock(return_value=set()),
        ),
        patch.object(
            PermissionService,
            "resolve_permanent_creator_user_ids_strict",
            new=AsyncMock(return_value={1}),
        ),
    ):
        owner = await service.request_change(
            _command(resource_id=501, applicant_user_id=1, applicant_user_name="owner")
        )
        editor = await service.request_change(
            _command(resource_id=502, applicant_user_id=9, applicant_user_name="editor")
        )

    assert owner.decision == "direct"
    assert editor.decision == "pending"
    assert await _count_rows(request_engine, KnowledgeSpaceFileChangeRequest) == 1
    assert await _count_rows(request_engine, ApprovalInstance) == 1


async def test_pending_upload_only_attaches_stage_and_never_creates_formal_knowledge_rows(request_engine):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    await _seed_stage(request_engine, tenant_id=17, space_id=101, uploader_user_id=9, upload_id="upload-1")
    events: list[str] = []
    service = _service(request_engine, events=events)

    result = await service.request_change(
        _command(
            action=KnowledgeSpaceFileChangeAction.UPLOAD,
            resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
            resource_id=None,
            upload_id="upload-1",
        )
    )

    assert result.decision == "pending"
    async with AsyncSession(bind=request_engine) as session:
        stage = (await session.exec(select(KnowledgeSpaceUploadStage))).one()
        request = (await session.exec(select(KnowledgeSpaceFileChangeRequest))).one()
        assert stage.state == KnowledgeSpaceUploadStageState.ATTACHED
        assert request.upload_stage_id == stage.id
        assert request.resource_id is None
    assert events.index("footprint") < events.index("submission")
    assert events[-2:] == ["retain:upload-1", "submission.effect"]


async def test_request_footprint_and_submission_bundle_roll_back_together_on_failure(request_engine):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    events: list[str] = []
    service = _service(
        request_engine,
        events=events,
        submission_port=_SubmissionPort(events, fail=True),
    )

    with pytest.raises(RuntimeError, match="submission failed"):
        await service.request_change(_command())

    assert await _count_rows(request_engine, KnowledgeSpaceFileChangeRequest) == 0
    assert await _count_rows(request_engine, KnowledgeSpaceFileChangeFootprint) == 0
    assert await _count_rows(request_engine, ApprovalInstance) == 0
    assert "submission.effect" not in events


async def test_approver_empty_exception_persists_and_projects_as_pending_without_task_notification(request_engine):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    events: list[str] = []
    service = _service(
        request_engine,
        events=events,
        submission_port=_SubmissionPort(events, exception=True),
    )

    result = await service.request_change(_command())

    assert result.decision == "pending"
    assert result.change_request_id is not None
    assert events[-1] == "submission.effect"
    async with AsyncSession(bind=request_engine) as session:
        instance = (await session.exec(select(ApprovalInstance))).one()
        assert instance.status == ApprovalInstanceStatus.EXCEPTION


async def test_owner_footprint_is_consumed_after_ascending_source_target_locks(request_engine):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=301)
    await _seed_space(request_engine, tenant_id=17, space_id=102)
    events: list[str] = []

    async def resolve(command):
        events.append("footprint")
        assert command.space_id == 301 and command.target_space_id == 102
        return [
            FootprintEntry(301, "folder", 20, "/10/20/", KnowledgeSpaceFileChangeLockScope.SUBTREE),
            FootprintEntry(301, "knowledge_file_version", 7001),
            FootprintEntry(301, "knowledge_file_version", 7002),
            FootprintEntry(102, "folder", 90, "/40/90/", KnowledgeSpaceFileChangeLockScope.DESTINATION),
            FootprintEntry(102, "folder", 40, "/40/", KnowledgeSpaceFileChangeLockScope.EXACT),
        ]

    service = _service(request_engine, events=events, footprint_resolver=resolve)
    result = await service.request_change(
        _command(
            action=KnowledgeSpaceFileChangeAction.MOVE,
            space_id=301,
            resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER,
            resource_id=20,
            target_space_id=102,
            target_parent_id=90,
        )
    )

    assert result.decision == "pending"
    async with AsyncSession(bind=request_engine) as session:
        footprints = (await session.exec(select(KnowledgeSpaceFileChangeFootprint))).all()
        assert {(row.space_id, row.resource_type, row.resource_id, row.lock_scope) for row in footprints} == {
            (301, "folder", 20, "subtree"),
            (301, "knowledge_file_version", 7001, "exact"),
            (301, "knowledge_file_version", 7002, "exact"),
            (102, "folder", 90, "destination"),
            (102, "folder", 40, "exact"),
        }


@pytest.mark.parametrize("invalid_side", ["source", "target"])
async def test_non_space_source_or_target_cannot_enter_request_bundle(request_engine, invalid_side):
    set_current_tenant_id(17)
    await _seed_space(
        request_engine,
        tenant_id=17,
        space_id=301,
        knowledge_type=(KnowledgeTypeEnum.NORMAL if invalid_side == "source" else KnowledgeTypeEnum.SPACE),
    )
    await _seed_space(
        request_engine,
        tenant_id=17,
        space_id=102,
        knowledge_type=(KnowledgeTypeEnum.NORMAL if invalid_side == "target" else KnowledgeTypeEnum.SPACE),
    )
    service = _service(request_engine, events=[])

    with pytest.raises(SpaceNotFoundError):
        await service.request_change(
            _command(
                action=KnowledgeSpaceFileChangeAction.MOVE,
                space_id=301,
                target_space_id=102,
                target_parent_id=90,
            )
        )

    assert await _count_rows(request_engine, KnowledgeSpaceFileChangeRequest) == 0
    assert await _count_rows(request_engine, ApprovalInstance) == 0


async def test_folder_subtree_creates_one_root_request_not_child_requests(request_engine):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    events: list[str] = []

    async def resolve(_command):
        return [
            FootprintEntry(101, "folder", 10, "/10/", KnowledgeSpaceFileChangeLockScope.SUBTREE),
            FootprintEntry(101, "knowledge_file", 11, "/10/11/"),
            FootprintEntry(101, "folder", 12, "/10/12/"),
        ]

    service = _service(request_engine, events=events, footprint_resolver=resolve)
    await service.request_change(_command(resource_type=KnowledgeSpaceFileChangeResourceType.FOLDER, resource_id=10))

    assert await _count_rows(request_engine, KnowledgeSpaceFileChangeRequest) == 1
    assert await _count_rows(request_engine, ApprovalInstance) == 1
    assert await _count_rows(request_engine, KnowledgeSpaceFileChangeFootprint) == 3


async def test_conflict_blocks_second_request_and_is_tenant_isolated(request_engine):
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    await _seed_space(request_engine, tenant_id=18, space_id=102)
    command = _command()

    set_current_tenant_id(17)
    first = await _service(request_engine, events=[]).request_change(command)
    with pytest.raises(SpaceFileChangeConflictError):
        await _service(request_engine, events=[]).request_change(command)

    set_current_tenant_id(18)
    foreign = await _service(request_engine, events=[]).request_change(_command(space_id=102))
    assert first.change_request_id != foreign.change_request_id


async def test_same_upload_retry_returns_original_ids_without_second_submission(request_engine):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    await _seed_stage(request_engine, tenant_id=17, space_id=101, uploader_user_id=9, upload_id="upload-2")
    events: list[str] = []
    submission_port = _SubmissionPort(events)
    service = _service(request_engine, events=events, submission_port=submission_port)
    command = _command(
        action=KnowledgeSpaceFileChangeAction.UPLOAD,
        resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
        resource_id=None,
        upload_id="upload-2",
    )

    first = await service.request_change(command)
    retried = await service.request_change(command)

    assert retried.change_request_id == first.change_request_id
    assert retried.approval_instance_id == first.approval_instance_id
    assert len(submission_port.calls) == 1


async def test_same_upload_retry_repairs_failed_post_commit_stage_retention(request_engine):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    await _seed_stage(request_engine, tenant_id=17, space_id=101, uploader_user_id=9, upload_id="upload-repair")
    events: list[str] = []
    submission_port = _SubmissionPort(events)
    service = _service(
        request_engine,
        events=events,
        submission_port=submission_port,
        retain_failures=[True, False],
    )
    command = _command(
        action=KnowledgeSpaceFileChangeAction.UPLOAD,
        resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
        resource_id=None,
        upload_id="upload-repair",
    )

    first = await service.request_change(command)
    async with AsyncSession(bind=request_engine) as session:
        stage = (await session.exec(select(KnowledgeSpaceUploadStage))).one()
        assert stage.state == KnowledgeSpaceUploadStageState.ATTACHING

    retried = await service.request_change(command)

    assert retried.change_request_id == first.change_request_id
    assert retried.approval_instance_id == first.approval_instance_id
    assert len(submission_port.calls) == 1
    assert events.count("retain:upload-repair") == 2
    async with AsyncSession(bind=request_engine) as session:
        stage = (await session.exec(select(KnowledgeSpaceUploadStage))).one()
        assert stage.state == KnowledgeSpaceUploadStageState.ATTACHED


async def test_same_upload_retry_reuses_knowledge_request_without_reading_approval_storage(request_engine):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    await _seed_stage(request_engine, tenant_id=17, space_id=101, uploader_user_id=9, upload_id="upload-2")
    events: list[str] = []
    submission_port = _SubmissionPort(events)
    service = _service(request_engine, events=events, submission_port=submission_port)
    command = _command(
        action=KnowledgeSpaceFileChangeAction.UPLOAD,
        resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
        resource_id=None,
        upload_id="upload-2",
    )
    first = await service.request_change(command)
    async with AsyncSession(bind=request_engine, expire_on_commit=False) as session:
        async with session.begin():
            instance = await session.get(ApprovalInstance, first.approval_instance_id)
            instance.status = ApprovalInstanceStatus.REJECTED
            session.add(instance)

    retried = await service.request_change(command)

    assert retried.change_request_id == first.change_request_id
    assert retried.approval_instance_id == first.approval_instance_id
    assert retried.approval_status == "pending"
    assert len(submission_port.calls) == 1


async def test_batch_items_commit_independently_and_keep_direct_pending_invalid_results(request_engine):
    set_current_tenant_id(17)
    await _seed_space(request_engine, tenant_id=17, space_id=101)
    events: list[str] = []
    service = _service(request_engine, events=events)
    pending = _command(resource_id=501)
    invalid = _command(resource_id=502)
    failed = _command(resource_id=504)
    direct = _command(resource_id=503)

    original = service.request_change

    async def per_item(command):
        if command is invalid:
            raise SpacePermissionDeniedError()
        if command is failed:
            raise RuntimeError("injected item failure")
        if command is direct:
            return SimpleNamespace(decision="direct", resource={"id": 503})
        return await original(command)

    service.request_change = per_item
    results = await service.request_changes([pending, invalid, failed, direct])

    assert [item.decision for item in results] == ["pending", "invalid", "invalid", "direct"]
    assert results[1].error_code == SpacePermissionDeniedError.Code
    assert results[2].error_message == "Internal file change operation failed"
    assert results[3].resource == {"id": 503}
    assert await _count_rows(request_engine, KnowledgeSpaceFileChangeRequest) == 1
