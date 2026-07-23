from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import (
    ApprovalInstanceRepository,
)
from bisheng.approval.domain.repositories.approval_query_repository import (
    ApprovalQueryRepository,
)
from bisheng.approval.domain.repositories.user_menu_access_repository import (
    UserMenuAccessRepository,
)
from bisheng.approval.domain.schemas.approval_center_schema import (
    DepartmentFileViewApplyRequest,
)
from bisheng.approval.domain.services.approval_center_service import (
    ApprovalCenterService,
)
from bisheng.approval.domain.services.department_file_view_approval_service import (
    DepartmentFileViewApprovalService,
)
from bisheng.common.errcode.approval import (
    ApprovalReasonRequiredError,
    ApprovalRequestAlreadyProcessedError,
)
from bisheng.database.models.audit_log import AuditLog
from bisheng.knowledge.domain.models.department_file_view_grant import (
    DepartmentFileViewGrant,
    DepartmentFileViewGrantStatus,
)
from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
    DepartmentFileViewGrantRepositoryImpl,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessDecision,
    DepartmentFileAccessStatus,
    DepartmentFileResource,
)
from bisheng.user.domain.models.user import UserDao


@pytest_asyncio.fixture
async def approval_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        ApprovalInstance.__table__,
        ApprovalTask.__table__,
        ApprovalOutbox.__table__,
        ApprovalActionLog.__table__,
        AuditLog.__table__,
        DepartmentFileViewGrant.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: SQLModel.metadata.create_all(
                sync_connection,
                tables=tables,
            )
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def approval_repo_session_factory(approval_engine, monkeypatch):
    @asynccontextmanager
    async def factory():
        async with AsyncSession(approval_engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session",
        factory,
    )
    return factory


async def _seed_fixed_request(
    factory,
) -> tuple[ApprovalInstance, ApprovalTask, ApprovalTask]:
    async with factory() as session:
        instance = ApprovalInstance(
            tenant_id=1,
            scenario_code="department_file_view_request",
            scenario_name="部门文件查看审批",
            handler_key="department_file_view_request",
            business_key="department-file:10:11",
            business_resource_type="department_knowledge_file",
            business_resource_id="11",
            business_name="安全制度.pdf",
            applicant_user_id=9,
            applicant_user_name="申请人",
            status=ApprovalInstanceStatus.PENDING,
            current_node_name="文件所属部门管理员审批",
            payload_snapshot={"space_id": 10, "file_id": 11, "department_id": 12},
            detail_snapshot={"file_name": "安全制度.pdf"},
        )
        session.add(instance)
        await session.flush()
        first = ApprovalTask(
            tenant_id=1,
            instance_id=instance.id,
            flow_version_id=1,
            node_code="department_file_owner_approvers",
            node_name="文件所属部门管理员审批",
            node_order=0,
            approver_user_id=20,
            approver_source_type="resolved",
            node_mode="or",
            status=ApprovalTaskStatus.PENDING,
        )
        second = ApprovalTask(
            tenant_id=1,
            instance_id=instance.id,
            flow_version_id=1,
            node_code="department_file_owner_approvers",
            node_name="文件所属部门管理员审批",
            node_order=0,
            approver_user_id=21,
            approver_source_type="resolved",
            node_mode="or",
            status=ApprovalTaskStatus.PENDING,
        )
        session.add_all([first, second])
        await session.commit()
        return instance, first, second


def test_apply_request_trims_reason_and_enforces_limit() -> None:
    request = DepartmentFileViewApplyRequest(
        space_id=10,
        file_id=11,
        reason="  因项目协作需要  ",
    )
    assert request.reason == "因项目协作需要"

    with pytest.raises(ValueError):
        DepartmentFileViewApplyRequest(space_id=10, file_id=11, reason="   ")
    with pytest.raises(ValueError):
        DepartmentFileViewApplyRequest(space_id=10, file_id=11, reason="a" * 2001)


@pytest.mark.asyncio
async def test_apply_service_rejects_blank_reason_before_any_side_effect() -> None:
    service = DepartmentFileViewApprovalService(
        session=AsyncMock(),
        file_repository=AsyncMock(),
        access_service=AsyncMock(),
        provisioner=AsyncMock(),
    )

    with pytest.raises(ApprovalReasonRequiredError):
        await service.apply(
            login_user=SimpleNamespace(user_id=9, user_name="u", tenant_id=1),
            space_id=10,
            file_id=11,
            reason="  ",
        )

    service.file_repository.find_by_id_for_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_persists_datetime_metadata_as_json_safe_string(
    approval_engine,
) -> None:
    file = SimpleNamespace(
        id=11,
        knowledge_id=10,
        file_name="安全制度.pdf",
        file_level_path="/20/21/",
        file_source="space_upload",
        file_subcategory_code="policy",
        update_time=datetime(2026, 7, 23, 12, 0, 0),
    )
    decision = DepartmentFileAccessDecision(
        file_id=11,
        space_id=10,
        status=DepartmentFileAccessStatus.APPROVAL_REQUIRED,
        department_id=12,
    )
    resource = DepartmentFileResource(
        file=file,
        space=SimpleNamespace(id=10, name="炼钢部知识库"),
        scope=SimpleNamespace(),
        binding=SimpleNamespace(department_id=12),
        department=SimpleNamespace(id=12, name="炼钢部"),
        valid=True,
    )
    access_service = SimpleNamespace(
        evaluate_file=AsyncMock(return_value=decision),
        load_resource=AsyncMock(return_value=resource),
        resolve_department_approvers=AsyncMock(return_value={20}),
    )
    provisioner = SimpleNamespace(
        get_contract=AsyncMock(
            return_value=SimpleNamespace(
                scenario=SimpleNamespace(scenario_name="部门文件查看审批"),
                flow_version=SimpleNamespace(id=1),
                route=SimpleNamespace(id=2),
                node=SimpleNamespace(
                    node_code="department_file_owner_approvers",
                    node_name="文件所属部门管理员审批",
                    node_order=0,
                ),
            )
        )
    )

    async with AsyncSession(approval_engine, expire_on_commit=False) as session:
        service = DepartmentFileViewApprovalService(
            session=session,
            file_repository=SimpleNamespace(
                find_by_id_for_update=AsyncMock(return_value=file),
            ),
            access_service=access_service,
            provisioner=provisioner,
        )
        service._get_applicant_department_id = AsyncMock(return_value=30)
        service._notify_approvers = AsyncMock()

        result = await service.apply(
            login_user=SimpleNamespace(
                user_id=9,
                user_name="申请人",
                tenant_id=1,
            ),
            space_id=10,
            file_id=11,
            reason="项目协作",
        )
        instance = (
            await session.exec(
                select(ApprovalInstance).where(
                    ApprovalInstance.id == result["instance_id"],
                )
            )
        ).one()
        tasks = (
            await session.exec(
                select(ApprovalTask).where(
                    ApprovalTask.instance_id == result["instance_id"],
                )
            )
        ).all()
        audits = (
            await session.exec(
                select(AuditLog).where(
                    AuditLog.target_id == str(result["instance_id"]),
                )
            )
        ).all()

    assert result["status"] == "pending"
    assert instance.detail_snapshot["updated_at"] == "2026-07-23T12:00:00"
    assert len(tasks) == 1
    assert len(audits) == 1
    service._notify_approvers.assert_awaited_once()


@pytest.mark.asyncio
async def test_status_allows_non_department_file_without_department_approval() -> None:
    file = SimpleNamespace(id=11, knowledge_id=10, file_name="公共制度.pdf")
    decision = DepartmentFileAccessDecision(
        file_id=11,
        space_id=10,
        status=DepartmentFileAccessStatus.NOT_APPLICABLE,
    )
    resource = DepartmentFileResource(
        file=file,
        space=SimpleNamespace(name="公共知识库"),
        scope=None,
        binding=None,
        department=None,
        valid=True,
        applicable=False,
    )
    file_repository = AsyncMock()
    file_repository.find_by_id.return_value = file
    access_service = AsyncMock()
    access_service.evaluate_file.return_value = decision
    access_service.load_resource.return_value = resource
    service = DepartmentFileViewApprovalService(
        session=AsyncMock(),
        file_repository=file_repository,
        access_service=access_service,
        provisioner=AsyncMock(),
    )

    result = await service.status(
        login_user=SimpleNamespace(user_id=9, user_name="u", tenant_id=1),
        space_id=10,
        file_id=11,
    )

    assert result["status"] == "allowed"
    assert result["content_access"] == "allowed"
    assert result["instance_id"] is None
    assert result["safe_metadata"]["file_name"] == "公共制度.pdf"
    service.provisioner.get_contract.assert_not_awaited()


@pytest.mark.asyncio
async def test_fixed_or_first_approval_is_atomic_and_second_decision_has_no_effect(
    approval_repo_session_factory,
) -> None:
    instance, first, second = await _seed_fixed_request(approval_repo_session_factory)

    result = await ApprovalInstanceRepository.decide_fixed_or_node_atomic(
        task_id=first.id,
        action="approve",
        operator_user_id=20,
        operator_user_name="审批人A",
        operator_tenant_id=1,
        operator_is_admin=False,
        comment="同意",
    )

    assert result.instance_status == ApprovalInstanceStatus.APPROVED
    assert result.outbox_id is not None

    with pytest.raises(ApprovalRequestAlreadyProcessedError):
        await ApprovalInstanceRepository.decide_fixed_or_node_atomic(
            task_id=second.id,
            action="reject",
            operator_user_id=21,
            operator_user_name="审批人B",
            operator_tenant_id=1,
            operator_is_admin=False,
            comment="拒绝",
        )

    async with approval_repo_session_factory() as session:
        refreshed = await session.get(ApprovalInstance, instance.id)
        tasks = list((await session.exec(select(ApprovalTask).where(ApprovalTask.instance_id == instance.id))).all())
        action_logs = list(
            (await session.exec(select(ApprovalActionLog).where(ApprovalActionLog.instance_id == instance.id))).all()
        )
        outboxes = list(
            (await session.exec(select(ApprovalOutbox).where(ApprovalOutbox.instance_id == instance.id))).all()
        )
        audits = list((await session.exec(select(AuditLog).where(AuditLog.target_id == str(first.id)))).all())

    assert refreshed.status == ApprovalInstanceStatus.APPROVED
    assert {task.approver_user_id: task.status for task in tasks} == {
        20: ApprovalTaskStatus.APPROVED,
        21: ApprovalTaskStatus.SKIPPED,
    }
    assert len(action_logs) == 1
    assert len(outboxes) == 1
    assert len(audits) == 1


@pytest.mark.asyncio
async def test_revoke_commits_grant_action_log_and_audit_in_one_transaction(
    approval_engine,
) -> None:
    async with AsyncSession(approval_engine, expire_on_commit=False) as session:
        instance = ApprovalInstance(
            tenant_id=1,
            scenario_code="department_file_view_request",
            scenario_name="部门文件查看审批",
            handler_key="department_file_view_request",
            business_key="department-file:10:11",
            business_resource_type="department_knowledge_file",
            business_resource_id="11",
            business_name="安全制度.pdf",
            applicant_user_id=9,
            applicant_user_name="申请人",
            status=ApprovalInstanceStatus.EXECUTED,
            payload_snapshot={
                "space_id": 10,
                "file_id": 11,
                "department_id": 12,
            },
            detail_snapshot={"file_name": "安全制度.pdf"},
        )
        session.add(instance)
        await session.flush()
        session.add(
            DepartmentFileViewGrant(
                tenant_id=1,
                user_id=9,
                space_id=10,
                file_id=11,
                department_id=12,
                approval_instance_id=int(instance.id),
            )
        )
        await session.commit()

        file = SimpleNamespace(id=11, knowledge_id=10)
        file_repository = AsyncMock()
        file_repository.find_by_id_for_update.return_value = file
        access_service = SimpleNamespace(
            grant_repository=DepartmentFileViewGrantRepositoryImpl(session),
            load_resource=AsyncMock(
                return_value=DepartmentFileResource(
                    file=file,
                    space=SimpleNamespace(id=10),
                    scope=SimpleNamespace(),
                    binding=SimpleNamespace(department_id=12),
                    department=SimpleNamespace(id=12),
                    valid=True,
                )
            ),
            resolve_department_approvers=AsyncMock(return_value={20, 21}),
        )
        service = DepartmentFileViewApprovalService(
            session=session,
            file_repository=file_repository,
            access_service=access_service,
            provisioner=AsyncMock(),
        )

        result = await service.revoke(
            login_user=SimpleNamespace(
                user_id=20,
                user_name="审批人",
                tenant_id=1,
                is_admin=lambda: False,
            ),
            instance_id=int(instance.id),
            reason="  权限回收  ",
        )

        grant = (await session.exec(select(DepartmentFileViewGrant))).one()
        action_log = (
            await session.exec(
                select(ApprovalActionLog).where(
                    ApprovalActionLog.instance_id == instance.id,
                    ApprovalActionLog.action == "revoke_grant",
                )
            )
        ).one()
        audit = (
            await session.exec(select(AuditLog).where(AuditLog.action == "approval.department_file_view.grant.revoke"))
        ).one()

    assert result["grant_status"] == DepartmentFileViewGrantStatus.REVOKED
    assert grant.status == DepartmentFileViewGrantStatus.REVOKED
    assert grant.revoked_reason == "权限回收"
    assert action_log.detail["reason"] == "权限回收"
    assert audit.reason == "权限回收"
    assert audit.audit_metadata["old_status"] == "active"
    assert audit.audit_metadata["new_status"] == "revoked"


@pytest.mark.asyncio
async def test_approval_center_exposes_department_grant_revoked_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = ApprovalInstance(
        id=1,
        tenant_id=1,
        scenario_code="department_file_view_request",
        scenario_name="部门文件查看审批",
        handler_key="department_file_view_request",
        business_key="department-file:10:11",
        business_resource_type="department_knowledge_file",
        business_resource_id="11",
        business_name="安全制度.pdf",
        applicant_user_id=9,
        applicant_user_name="申请人",
        status=ApprovalInstanceStatus.EXECUTED,
        reason="项目协作",
        payload_snapshot={
            "space_id": 10,
            "file_id": 11,
            "file_name": "安全制度.pdf",
            "space_name": "部门知识库",
            "department_id": 12,
            "department_name": "安全部",
        },
        detail_snapshot={
            "file_name": "安全制度.pdf",
            "space_name": "部门知识库",
            "department_name": "安全部",
            "file_ext": "pdf",
        },
    )
    task = ApprovalTask(
        id=2,
        tenant_id=1,
        instance_id=1,
        flow_version_id=1,
        node_code="department_file_owner_approvers",
        node_name="文件所属部门管理员审批",
        node_order=0,
        approver_user_id=20,
        approver_source_type="department_file_approvers",
        node_mode="or",
        status=ApprovalTaskStatus.APPROVED,
    )
    revoke_log = ApprovalActionLog(
        id=3,
        tenant_id=1,
        instance_id=1,
        action="revoke_grant",
        operator_user_id=20,
        operator_user_name="审批人",
        detail={"reason": "权限回收"},
    )
    monkeypatch.setattr(
        ApprovalQueryRepository,
        "list_tasks_by_approver",
        AsyncMock(return_value=[task]),
    )
    monkeypatch.setattr(
        ApprovalInstanceRepository,
        "get_instances_by_ids",
        AsyncMock(return_value=[instance]),
    )
    monkeypatch.setattr(
        ApprovalInstanceRepository,
        "get_instance_ids_with_action",
        AsyncMock(return_value={1}),
    )
    monkeypatch.setattr(
        UserMenuAccessRepository,
        "get_revoked_instance_ids",
        AsyncMock(return_value=set()),
    )

    listed = await ApprovalCenterService.list_my_tasks(
        tenant_id=1,
        approver_user_id=20,
    )

    monkeypatch.setattr(
        ApprovalInstanceRepository,
        "get_instance",
        AsyncMock(return_value=instance),
    )
    monkeypatch.setattr(
        ApprovalInstanceRepository,
        "list_tasks",
        AsyncMock(return_value=[task]),
    )
    monkeypatch.setattr(
        ApprovalInstanceRepository,
        "list_action_logs",
        AsyncMock(return_value=[revoke_log]),
    )
    monkeypatch.setattr(
        UserDao,
        "aget_user_by_ids",
        AsyncMock(
            return_value=[
                SimpleNamespace(user_id=20, user_name="审批人"),
            ]
        ),
    )

    detail = await ApprovalCenterService.get_instance_detail(
        instance_id=1,
        login_user=SimpleNamespace(
            user_id=20,
            tenant_id=1,
            is_admin=lambda: False,
        ),
    )

    assert listed["data"][0]["grant_revoked"] is True
    assert detail["grant_revoked"] is True
    assert detail["detail_snapshot"] == {
        "file_name": "安全制度.pdf",
        "space_name": "部门知识库",
        "department_name": "安全部",
        "file_ext": "pdf",
    }
    assert detail["tasks"][0]["node_mode"] == "or"
