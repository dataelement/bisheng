# ruff: noqa: RUF002
"""T018：专家停用/恢复、非管理员 18307、DELETE 映射为停用。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.qa_expert import QaExpertAdminRequiredError, QaExpertDisabledError
from bisheng.qa_expert.domain.schemas import ExpertCreateRequest, QuestionCreateRequest
from bisheng.qa_expert.domain.services import ExpertService, QuestionService


def _admin() -> SimpleNamespace:
    return SimpleNamespace(user_id=9, user_name="admin", is_admin=lambda: False, role="管理员", is_global_super=False)


def _staff() -> SimpleNamespace:
    return SimpleNamespace(user_id=2, user_name="staff", is_admin=lambda: False, role="员工", is_global_super=False)


def _expert_service() -> ExpertService:
    svc = ExpertService()
    svc.repository = MagicMock()
    svc.publish_service = MagicMock()
    svc.publish_service.on_expert_disabled = AsyncMock(return_value=[])
    svc.repository.get_by_id = AsyncMock(return_value=SimpleNamespace(id=5, user_id=50, status=1, expert_name="专家"))
    svc.repository.update = AsyncMock(
        side_effect=lambda eid, **kw: SimpleNamespace(id=eid, user_id=50, expert_name="专家", **kw)
    )
    svc.repository.delete = AsyncMock()
    svc.repository.get_by_user_name = AsyncMock(return_value=None)
    svc.repository.create = AsyncMock(
        return_value=SimpleNamespace(id=8, user_id=80, expert_name="新专家", depart_ment=None, status=1)
    )
    svc._sync_wechat_user_id = AsyncMock()
    return svc


async def test_non_admin_write_raises_18307():
    svc = _expert_service()
    with pytest.raises(QaExpertAdminRequiredError) as exc:
        await svc.disable_expert(5, _staff())
    assert exc.value.Code == 18307
    svc.repository.update.assert_not_awaited()


async def test_disable_sets_status_zero_and_notifies_publish():
    svc = _expert_service()
    row = await svc.disable_expert(5, _admin())
    assert int(row.status) == 0
    svc.publish_service.on_expert_disabled.assert_awaited_once_with(50)
    svc.repository.delete.assert_not_awaited()


async def test_delete_maps_to_disable_not_hard_delete():
    svc = _expert_service()
    await svc.delete_expert(5, user=_admin())
    svc.repository.delete.assert_not_awaited()
    svc.repository.update.assert_awaited()
    assert svc.repository.update.await_args.kwargs.get("status") == 0


async def test_enable_does_not_rejoin_ended_publish():
    svc = _expert_service()
    svc.repository.get_by_id = AsyncMock(return_value=SimpleNamespace(id=5, user_id=50, status=0, expert_name="专家"))
    row = await svc.enable_expert(5, _admin())
    assert int(row.status) == 1
    svc.publish_service.on_expert_disabled.assert_not_awaited()


async def test_disabled_expert_cannot_be_invited():
    qsvc = QuestionService()
    qsvc.expert_repo = MagicMock()
    qsvc.expert_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=5, user_id=50, status=0, expert_name="专家"))
    with pytest.raises(QaExpertDisabledError):
        await qsvc._validate_invites(
            1,
            "directed",
            [5],
            QuestionCreateRequest(
                title="题",
                description="描",
                business_domain="steel",
                asker_reveal_on_public=True,
            ),
        )


async def test_create_expert_requires_admin():
    svc = _expert_service()
    with pytest.raises(QaExpertAdminRequiredError):
        await svc.create_expert(ExpertCreateRequest(expert_name="x", user_id=3), user=_staff())
