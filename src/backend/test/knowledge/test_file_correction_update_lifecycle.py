"""采纳并更新: 解析后再关单, 每人每日 10 分封顶, 失败可重解析."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_file_correction_update import (
    UPDATE_PHASE_FAILED,
    UPDATE_PHASE_IDLE,
    UPDATE_PHASE_UPDATING,
    classify_update_phase,
)
from test.knowledge.test_file_correction_flow import (
    _app,
    _body,
    _cleanup,
    _insert_file,
    _insert_space,
    _insert_user,
    _submit,
    _user,
    flow_env,
)


def test_classify_update_phase_from_file_status():
    """没有指针是 idle, 失败态是 failed, 其余有指针是 updating."""
    assert classify_update_phase(None, 1) == UPDATE_PHASE_IDLE
    assert classify_update_phase(0, 3) == UPDATE_PHASE_IDLE
    assert classify_update_phase(9, KnowledgeFileStatus.FAILED.value) == UPDATE_PHASE_FAILED
    assert classify_update_phase(9, KnowledgeFileStatus.TIMEOUT.value) == UPDATE_PHASE_FAILED
    assert classify_update_phase(9, KnowledgeFileStatus.VIOLATION.value) == UPDATE_PHASE_FAILED
    assert classify_update_phase(9, KnowledgeFileStatus.PROCESSING.value) == UPDATE_PHASE_UPDATING
    assert classify_update_phase(9, KnowledgeFileStatus.SUCCESS.value) == UPDATE_PHASE_UPDATING


@pytest.mark.asyncio
async def test_update_daily_cap_ten_points_mysql(flow_env):
    """同一反馈人当天第 6 次采纳并更新仍换版本, 这次 0 分, 合计 10."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _insert_user(session, f"fc-cap-{suffix}")
            uploader = await _insert_user(session, f"fc-capu-{suffix}")
            user_ids.extend([reader, uploader])
            space_id = await _insert_space(session, name=f"fc-cap-{suffix}", level="department")
            space_ids.append(space_id)
            origin = await _insert_file(session, space_id=space_id, name=f"cap-o-{suffix}", user_id=uploader)
            file_ids.append(origin)
            new_ids = []
            for index in range(6):
                new_id = await _insert_file(
                    session,
                    space_id=space_id,
                    name=f"cap-n-{suffix}-{index}",
                    user_id=uploader,
                )
                new_ids.append(new_id)
                file_ids.append(new_id)
                await session.execute(text("UPDATE knowledgefile SET status = 2 WHERE id = :id"), {"id": new_id})
            await session.commit()
        last_task = None
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as reader_client:
            async with AsyncClient(
                transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
                base_url="http://test",
            ) as up_client:
                for index, new_id in enumerate(new_ids):
                    created = _body(await _submit(reader_client, origin, f"第{index + 1}处"))
                    assert created["status_code"] == 200, created
                    decided = _body(
                        await up_client.post(
                            f"/api/v1/approval/tasks/{created['data']['task_id']}/decision",
                            json={"action": "adopt_update", "new_file_id": new_id},
                        )
                    )
                    assert decided["status_code"] == 200, decided
                    last_task = created["data"]["task_id"]
        async with AsyncSession(engine, expire_on_commit=False) as session:
            total = (
                await session.execute(
                    text("SELECT COALESCE(SUM(delta), 0) FROM user_point_log WHERE user_id = :id AND rule_code = 'G8'"),
                    {"id": reader},
                )
            ).scalar_one()
            skipped = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM knowledge_file_correction_award
                        WHERE applicant_user_id = :id AND award_kind = 'update' AND award_state = 'skipped'
                        """
                    ),
                    {"id": reader},
                )
            ).scalar_one()
            primary = (
                await session.execute(
                    text(
                        """
                        SELECT knowledge_file_id FROM knowledge_document_version
                        WHERE knowledge_file_id = :id AND is_primary = 1
                        """
                    ),
                    {"id": new_ids[-1]},
                )
            ).scalar_one()
            assert int(total) == 10
            assert int(skipped) == 1
            assert int(primary) == int(new_ids[-1])
        assert last_task
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            for file_id in file_ids:
                await session.execute(
                    text("DELETE FROM knowledge_document_version WHERE knowledge_file_id = :id"),
                    {"id": file_id},
                )
            await session.commit()
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)


@pytest.mark.asyncio
async def test_retry_failed_update_and_block_withdraw_mysql(flow_env, monkeypatch):
    """登记失败文件后可重解析; 解析中撤回返回 18411, 积分为 0."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    dispatched: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _insert_user(session, f"fc-rt-{suffix}")
            uploader = await _insert_user(session, f"fc-rtu-{suffix}")
            user_ids.extend([reader, uploader])
            space_id = await _insert_space(session, name=f"fc-rt-{suffix}", level="department")
            space_ids.append(space_id)
            origin = await _insert_file(session, space_id=space_id, name=f"rt-o-{suffix}", user_id=uploader)
            file_ids.append(origin)

        async def _fake_add(_request, _login_user, **kwargs):
            async with AsyncSession(engine, expire_on_commit=False) as session:
                new_id = await _insert_file(
                    session,
                    space_id=space_id,
                    name=f"rt-n-{suffix}",
                    user_id=uploader,
                )
                await session.execute(
                    text("UPDATE knowledgefile SET status = 3 WHERE id = :id"),
                    {"id": new_id},
                )
                await session.commit()
            file_ids.append(new_id)
            return [SimpleNamespace(id=new_id, status=3, file_name=f"rt-n-{suffix}")]

        async def _fake_dispatch(**kwargs):
            dispatched.append(int(kwargs["file_id"]))
            return "ticket"

        async def _fake_pdf(_file):
            return None

        monkeypatch.setattr(
            "bisheng.knowledge.domain.services.knowledge_file_correction_service._add_correction_file",
            _fake_add,
        )
        monkeypatch.setattr(
            "bisheng.knowledge.domain.services.knowledge_parse_dispatch_service.dispatch_knowledge_parse_task",
            _fake_dispatch,
        )
        monkeypatch.setattr(
            "bisheng.knowledge.domain.services.knowledge_pdf_artifact_service.request_pdf_artifact_generation",
            _fake_pdf,
        )

        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            created = _body(await _submit(client, origin, "失败后重试"))
            assert created["status_code"] == 200, created
            correction_id = created["data"]["correction_id"]
            instance_id = created["data"]["instance_id"]
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            registered = _body(
                await up_client.post(
                    f"/api/v1/knowledge/file-corrections/{correction_id}/update-file",
                    json={"file_path": "tmp/fail.pdf"},
                )
            )
            assert registered["status_code"] == 200, registered
            detail = _body(await up_client.get(f"/api/v1/knowledge/file-corrections/{correction_id}"))
            assert detail["data"]["status"] == "pending"
            assert detail["data"]["update_phase"] == "failed"
            retried = _body(
                await up_client.post(f"/api/v1/knowledge/file-corrections/{correction_id}/retry-update-file")
            )
            assert retried["status_code"] == 200, retried
            assert retried["data"]["update_phase"] == "updating"
            assert dispatched == [int(registered["data"]["id"])]
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            withdrawn = _body(await client.post(f"/api/v1/approval/instances/{instance_id}/withdraw", json={}))
            assert withdrawn["status_code"] == 18411, withdrawn
        async with AsyncSession(engine, expire_on_commit=False) as session:
            status = (
                await session.execute(
                    text("SELECT status FROM knowledge_file_correction WHERE id = :id"),
                    {"id": correction_id},
                )
            ).scalar_one()
            total = (
                await session.execute(
                    text("SELECT COALESCE(SUM(delta), 0) FROM user_point_log WHERE user_id = :id AND rule_code = 'G8'"),
                    {"id": reader},
                )
            ).scalar_one()
            assert str(status) == "pending"
            assert int(total) == 0
    finally:
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)
