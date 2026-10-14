"""分享撤回、再次申请和独立历史的本地闭环回归。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import SQLModel, select

from bisheng.approval.domain.models.approval_instance import ApprovalActionLog, ApprovalInstance, ApprovalTask
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceFileShareApprovalHandler
from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import ShareKnowledgeDocumentCommand
from test.knowledge.test_knowledge_document_distribution_share import _command, _seed_document, _service


async def seed(session):
    async with session.bind.begin() as connection:
        await connection.run_sync(
            lambda bind: SQLModel.metadata.create_all(
                bind,
                tables=[ApprovalInstance.__table__, ApprovalTask.__table__, ApprovalActionLog.__table__],
            )
        )
    await _seed_document(session)
    for instance_id in (8001, 8002):
        session.add(
            ApprovalInstance(
                id=instance_id,
                tenant_id=7,
                scenario_code="knowledge_space_file_share_request",
                scenario_name="部门文件分享",
                handler_key="knowledge_space_file_share_request",
                business_key="knowledge-file-share:document:91:target:30",
                business_resource_type="knowledge_space_file_share_request",
                business_resource_id="91:30",
                business_name="分享文件",
                applicant_user_id=7,
                applicant_user_name="申请人",
                status="executed",
                payload_snapshot={
                    "canonical_document_id": 91,
                    "source_space_id": 20,
                    "source_entry_id": 100,
                    "target_space_id": 30,
                },
            )
        )
        session.add(
            ApprovalTask(
                id=instance_id,
                tenant_id=7,
                instance_id=instance_id,
                flow_version_id=1,
                node_code="n1",
                node_name="审批",
                approver_user_id=9,
                approver_source_type="user",
                node_mode="or",
                status="approved",
            )
        )
    await session.commit()


def command():
    return ShareKnowledgeDocumentCommand(
        tenant_id=7,
        approval_instance_id=8002,
        document_id=91,
        source_entry_id=100,
        target_space_id=30,
        allow_download=False,
        target_file_level_path="/901",
        target_level=1,
    )


@pytest.mark.parametrize("failed", [False, True])
async def test_reshare_replaces_revoked_entry_without_reusing_old_identity(async_db_session, failed):
    await seed(async_db_session)
    service = _service(async_db_session)
    old = await service.share_approved(_command())
    await service.remove_share_entry(tenant_id=7, document_id=91, share_entry_id=old.share_entry_id, actor_entry_id=100)
    row = await service.file_repository.find_by_id(old.share_entry_id)
    if failed:
        row.projection_status = "failed"
        row.projection_retry_count = 4
        await async_db_session.commit()
    new = await service.share_approved(command())
    repeated = await service.share_approved(command())
    assert new.share_entry_id != old.share_entry_id
    assert repeated.share_entry_id == new.share_entry_id and repeated.idempotent
    current = await service.file_repository.find_by_id(new.share_entry_id)
    assert current.entry_status == "active" and current.approval_instance_id == 8002
    assert current.file_level_path == "/901" and not current.allow_download
    assert current.projection_retry_count == 0
    assert (await service.file_repository.find_by_id(old.share_entry_id)).entry_status == "deleting"
    assert (await service.file_repository.find_by_id(100)).entry_status == "active"


async def test_submit_source_normalization_ignores_only_revoked_share(async_db_session, monkeypatch):
    await seed(async_db_session)
    distribution = _service(async_db_session)
    old = await distribution.share_approved(_command())
    await distribution.remove_share_entry(
        tenant_id=7, document_id=91, share_entry_id=old.share_entry_id, actor_entry_id=100
    )

    @asynccontextmanager
    async def db():
        yield async_db_session

    monkeypatch.setattr("bisheng.core.database.get_async_db_session", db)
    service = ShougangApprovalService()
    service._normalize_publish_source = AsyncMock(return_value=SimpleNamespace(document_id=91))
    source = await distribution.file_repository.find_by_id(100)
    result = await service._normalize_share_source(tenant_id=7, source_file=source, target_space_id=30)
    assert result.document_id == 91
    await distribution.share_approved(command())
    with pytest.raises(Exception, match="目标知识库已存在"):
        await service._normalize_share_source(tenant_id=7, source_file=source, target_space_id=30)


@pytest.mark.parametrize("recipient", [False, True])
async def test_history_survives_cleanup_and_new_share(async_db_session, monkeypatch, recipient):
    await seed(async_db_session)
    service = _service(async_db_session)
    old = await service.share_approved(_command())
    for _ in range(2):
        await service.remove_share_entry(
            tenant_id=7,
            document_id=91,
            share_entry_id=old.share_entry_id,
            actor_entry_id=old.share_entry_id if recipient else 100,
        )
    logs = list((await async_db_session.exec(select(ApprovalActionLog))).all())
    assert len(logs) == 1 and logs[0].action == "share_revoked" and logs[0].instance_id == 8001
    assert logs[0].detail["share_entry_id"] == old.share_entry_id
    await service.file_repository.prepare_delete_by_ids([old.share_entry_id])
    await async_db_session.commit()
    await service.share_approved(command())

    @asynccontextmanager
    async def db():
        yield async_db_session

    for module in ("approval_instance_repository", "approval_query_repository"):
        monkeypatch.setattr(f"bisheng.approval.domain.repositories.{module}.get_async_db_session", db)
    monkeypatch.setattr(ApprovalCenterService, "_load_department_projection_map", AsyncMock(return_value={}))
    monkeypatch.setattr(ApprovalCenterService, "_overlay_live_space_names", AsyncMock())
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.UserDao.aget_user_by_ids", AsyncMock(return_value=[])
    )
    tasks = await ApprovalCenterService.list_my_tasks(tenant_id=7, approver_user_id=9)
    requests = await ApprovalCenterService.list_my_requests(tenant_id=7, applicant_user_id=7)
    user = SimpleNamespace(user_id=7, tenant_id=7, is_admin=lambda: False)
    task = await ApprovalCenterService.get_task_detail(task_id=8001, login_user=user)
    request = await ApprovalCenterService.get_instance_detail(instance_id=8001, login_user=user)
    for response in (tasks, requests):
        assert response["total"] == 2
        rows = {item["instance_id"]: item for item in response["data"]}
        assert rows[8001]["share_revoked"] is True
        assert rows[8002]["share_revoked"] is False
    assert task["share_revoked"] and request["share_revoked"]
    assert request["status"] == "executed"


async def test_old_approval_replay_cannot_resurrect_removed_share(async_db_session, monkeypatch):
    await seed(async_db_session)
    service = _service(async_db_session)
    old = await service.share_approved(_command())
    await service.remove_share_entry(tenant_id=7, document_id=91, share_entry_id=old.share_entry_id, actor_entry_id=100)
    await service.file_repository.prepare_delete_by_ids([old.share_entry_id])
    await async_db_session.commit()

    @asynccontextmanager
    async def db():
        yield async_db_session

    monkeypatch.setattr("bisheng.core.database.get_async_db_session", db)
    instance = await async_db_session.get(ApprovalInstance, 8001)
    result = await KnowledgeSpaceFileShareApprovalHandler().on_approved(
        8001, {"tenant_id": 7, **instance.payload_snapshot}
    )
    assert result["share_revoked"] is True
    assert await service.file_repository.find_by_approval_instance_id(8001) is None


async def test_revocation_event_failure_rolls_back_stop_access(async_db_session, monkeypatch):
    await seed(async_db_session)
    service = _service(async_db_session)
    old = await service.share_approved(_command())
    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.ApprovalInstanceRepository.create_action_log",
        AsyncMock(side_effect=RuntimeError("audit storage failed")),
    )
    with pytest.raises(Exception, match="audit storage failed"):
        await service.remove_share_entry(
            tenant_id=7, document_id=91, share_entry_id=old.share_entry_id, actor_entry_id=100
        )
    assert (await service.file_repository.find_by_id(old.share_entry_id)).entry_status == "active"


async def test_revoked_failed_approval_does_not_hide_new_pending_application(async_db_session, monkeypatch):
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

    await seed(async_db_session)
    service = _service(async_db_session)
    old = await service.share_approved(_command())
    await service.remove_share_entry(tenant_id=7, document_id=91, share_entry_id=old.share_entry_id, actor_entry_id=100)
    old_instance = await async_db_session.get(ApprovalInstance, 8001)
    old_instance.status = "execute_failed"
    await async_db_session.commit()

    @asynccontextmanager
    async def db():
        yield async_db_session

    monkeypatch.setattr("bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session", db)
    key = "knowledge-file-share:document:91:target:30"
    scenario = "knowledge_space_file_share_request"
    assert (
        await ApprovalInstanceRepository.find_duplicate_active_instance(
            tenant_id=7,
            scenario_code=scenario,
            business_key=key,
            applicant_user_id=7,
        )
        is None
    )
    assert (
        await ApprovalInstanceRepository.find_pending_instance_by_business_resource_id(
            tenant_id=7,
            scenario_code=scenario,
            business_resource_id="91:30",
        )
        is None
    )
    new_instance = await async_db_session.get(ApprovalInstance, 8002)
    new_instance.status = "pending"
    await async_db_session.commit()
    pending = await ApprovalInstanceRepository.find_pending_instance_by_business_resource_id(
        tenant_id=7,
        scenario_code=scenario,
        business_resource_id="91:30",
    )
    assert pending.id == 8002


@pytest.mark.parametrize("conflict", ["active", "preparing", "deleting_publish"])
async def test_override_never_ignores_live_or_publish_occupancy(async_db_session, conflict):
    await seed(async_db_session)
    service = _service(async_db_session)
    old = await service.share_approved(_command())
    entry = await service.file_repository.find_by_id(old.share_entry_id)
    entry.entry_status = "deleting" if conflict == "deleting_publish" else conflict
    if conflict == "deleting_publish":
        entry.entry_type = "publish"
    await async_db_session.commit()
    with pytest.raises(Exception, match="already has an entry"):
        await service.share_approved(command())


@pytest.mark.parametrize("mismatch", ["tenant", "approval_target"])
async def test_revoke_rejects_foreign_scope_without_mutating_share(async_db_session, mismatch):
    await seed(async_db_session)
    service = _service(async_db_session)
    old = await service.share_approved(_command())
    if mismatch == "approval_target":
        instance = await async_db_session.get(ApprovalInstance, 8001)
        instance.payload_snapshot = {**instance.payload_snapshot, "target_space_id": 40}
        await async_db_session.commit()
    with pytest.raises(Exception, match="mismatch"):
        await service.remove_share_entry(
            tenant_id=8 if mismatch == "tenant" else 7,
            document_id=91,
            share_entry_id=old.share_entry_id,
            actor_entry_id=100,
        )
    assert (await service.file_repository.find_by_id(old.share_entry_id)).entry_status == "active"
