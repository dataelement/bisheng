from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String, func
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstance,
    ApprovalOutbox,
    ApprovalTask,
)
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision, ApprovalGateRequest
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id


class FileChangeRequestForUowTest(SQLModel, table=True):
    __tablename__ = "file_change_request_for_uow_test"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    business_key: str = Field(sa_column=Column(String(255), nullable=False))


@pytest_asyncio.fixture
async def gate_uow_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        FileChangeRequestForUowTest.__table__,
        ApprovalInstance.__table__,
        ApprovalTask.__table__,
        ApprovalActionLog.__table__,
        ApprovalOutbox.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def gate_uow_tenant_context():
    token = current_tenant_id.set(None)
    set_current_tenant_id(17)
    yield
    current_tenant_id.reset(token)


def _pending_gate() -> ApprovalGate:
    first_node = SimpleNamespace(
        node_code="space-file-change-review",
        node_name="知识空间管理员审核",
        node_order=1,
        node_mode="or",
        approver_config={"sources": [{"type": "knowledge_space_owner"}]},
    )
    handler = SimpleNamespace(
        build_detail=AsyncMock(return_value={"action": "rename"}),
        build_title=AsyncMock(return_value="重命名文件"),
        resolve_approvers=AsyncMock(return_value=[31, 32]),
    )
    return ApprovalGate(
        registry=SimpleNamespace(get_handler=AsyncMock(return_value=handler)),
        scenario_repository=SimpleNamespace(
            get_scenario_by_code=AsyncMock(
                return_value=SimpleNamespace(id=1, scenario_name="知识空间文件变更审核", enabled=True)
            ),
            list_route_rules=AsyncMock(return_value=[SimpleNamespace(id=11, route_type="flow", flow_definition_id=21)]),
            get_active_flow_version=AsyncMock(return_value=SimpleNamespace(id=41)),
            list_node_definitions=AsyncMock(return_value=[first_node]),
        ),
    )


def _pass_gate() -> ApprovalGate:
    handler = SimpleNamespace(
        build_detail=AsyncMock(return_value={"action": "upload"}),
        build_title=AsyncMock(return_value="上传文件"),
        resolve_approvers=AsyncMock(),
    )
    return ApprovalGate(
        registry=SimpleNamespace(get_handler=AsyncMock(return_value=handler)),
        scenario_repository=SimpleNamespace(
            get_scenario_by_code=AsyncMock(
                return_value=SimpleNamespace(id=1, scenario_name="知识空间文件变更审核", enabled=True)
            ),
            list_route_rules=AsyncMock(return_value=[SimpleNamespace(id=12, route_type="pass")]),
        ),
    )


def _request() -> ApprovalGateRequest:
    return ApprovalGateRequest(
        tenant_id=17,
        scenario_code="knowledge_space_file_change_request",
        business_key="knowledge-space-change:501",
        business_resource_type="knowledge_space_file_change",
        business_resource_id="501",
        business_name="文件变更",
        applicant_user_id=7,
        applicant_user_name="alice",
        payload_snapshot={"space_id": 9, "action": "rename"},
    )


async def _count(session: AsyncSession, model: type[SQLModel]) -> int:
    statement = select(func.count()).select_from(model)
    return int((await session.exec(statement)).one())


@pytest.mark.asyncio
async def test_gate_uow_rolls_back_file_change_and_entire_approval_bundle(gate_uow_engine):
    gate = _pending_gate()
    audit = AsyncMock()

    with patch("bisheng.approval.domain.services.approval_gate.AuditLogDao.ainsert_v2", audit):
        async with AsyncSession(bind=gate_uow_engine, expire_on_commit=False) as session:
            try:
                async with session.begin():
                    session.add(
                        FileChangeRequestForUowTest(
                            tenant_id=17,
                            business_key="knowledge-space-change:501",
                        )
                    )
                    effect_result = await gate.request_or_pass_in_uow(_request(), session=session)
                    assert effect_result.result.decision == ApprovalGateDecision.PENDING
                    assert len(effect_result.result.task_ids) == 2
                    assert audit.await_count == 0
                    raise RuntimeError("injected failure after approval bundle flush")
            except RuntimeError as exc:
                assert str(exc) == "injected failure after approval bundle flush"

        async with AsyncSession(bind=gate_uow_engine) as verification:
            assert await _count(verification, FileChangeRequestForUowTest) == 0
            assert await _count(verification, ApprovalInstance) == 0
            assert await _count(verification, ApprovalTask) == 0
            assert await _count(verification, ApprovalActionLog) == 0
        audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_uow_commits_bundle_before_running_post_commit_effects(gate_uow_engine):
    gate = _pending_gate()
    audit = AsyncMock()

    with patch("bisheng.approval.domain.services.approval_gate.AuditLogDao.ainsert_v2", audit):
        async with AsyncSession(bind=gate_uow_engine, expire_on_commit=False) as session:
            async with session.begin():
                session.add(
                    FileChangeRequestForUowTest(
                        tenant_id=17,
                        business_key="knowledge-space-change:501",
                    )
                )
                effect_result = await gate.request_or_pass_in_uow(_request(), session=session)
                audit.assert_not_awaited()
                with pytest.raises(RuntimeError, match="before transaction completion"):
                    await effect_result.run_post_commit_effects()
                audit.assert_not_awaited()

            async with AsyncSession(bind=gate_uow_engine) as verification:
                assert await _count(verification, FileChangeRequestForUowTest) == 1
                assert await _count(verification, ApprovalInstance) == 1
                assert await _count(verification, ApprovalTask) == 2
                assert await _count(verification, ApprovalActionLog) == 1

            audit.assert_not_awaited()
            await effect_result.run_post_commit_effects()
            audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_gate_uow_dispatches_celery_effect_with_request_tenant_header(gate_uow_engine):
    gate = _pass_gate()
    audit = AsyncMock()
    dispatch = MagicMock()
    tenant_token = current_tenant_id.set(None)

    try:
        # A leaked/wrong request ContextVar must not override the request's
        # authoritative tenant when the deferred worker effect is built.
        set_current_tenant_id(999)
        with (
            patch("bisheng.approval.domain.services.approval_gate.AuditLogDao.ainsert_v2", audit),
            patch(
                "bisheng.worker.approval.tasks.execute_approval_outbox.apply_async",
                dispatch,
            ),
        ):
            async with AsyncSession(bind=gate_uow_engine, expire_on_commit=False) as session:
                async with session.begin():
                    effect_result = await gate.request_or_pass_in_uow(_request(), session=session)
                    assert effect_result.result.decision == ApprovalGateDecision.PASS
                    dispatch.assert_not_called()
                    audit.assert_not_awaited()

                # Post-commit execution may happen after request context cleanup
                # or under an unrelated context. The Gate request remains the
                # authoritative tenant source for the worker header.
                current_tenant_id.set(999)
                await effect_result.run_post_commit_effects()

            dispatch.assert_called_once()
            assert dispatch.call_args.kwargs == {
                "args": [1],
                "headers": {"tenant_id": 17},
            }
            audit.assert_awaited_once()
    finally:
        current_tenant_id.reset(tenant_token)
