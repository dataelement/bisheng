# ruff: noqa: RUF002
"""转公开审批展示身份：匿名标志与实例 question_id 解析。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.qa_expert.domain.publish_approval_bridge import applicant_department_id_for_initiator
from bisheng.qa_expert.domain.publish_approval_identity import (
    anonymous_choice_for_user,
    question_id_from_instance,
)


def test_question_id_prefers_payload_snapshot():
    instance = SimpleNamespace(payload_snapshot={"question_id": 42}, business_resource_id="99")
    assert question_id_from_instance(instance) == 42


def test_question_id_falls_back_to_business_resource_id():
    instance = SimpleNamespace(payload_snapshot={}, business_resource_id="18")
    assert question_id_from_instance(instance) == 18


def test_asker_anonymous_choice():
    question = SimpleNamespace(user_id=7, asker_anonymous=1, asker_reveal_on_public=0)
    anonymous, reveal = anonymous_choice_for_user(question, [], 7)
    assert anonymous is True
    assert int(reveal) == 0


def test_answerer_anonymous_choice_overrides_non_asker():
    question = SimpleNamespace(user_id=7, asker_anonymous=0, asker_reveal_on_public=None)
    answers = [SimpleNamespace(user_id=9, anonymous=1, reveal_on_public=0)]
    anonymous, reveal = anonymous_choice_for_user(question, answers, 9)
    assert anonymous is True
    assert int(reveal) == 0
    named, named_reveal = anonymous_choice_for_user(question, answers, 8)
    assert named is False
    assert named_reveal is None


async def test_applicant_department_id_skips_anonymous(monkeypatch) -> None:
    """匿名发起人不查、不写部门。"""
    lookup = AsyncMock(return_value=SimpleNamespace(department_id=101))
    monkeypatch.setattr(
        "bisheng.database.models.department.UserDepartmentDao.aget_user_primary_department",
        lookup,
    )
    assert await applicant_department_id_for_initiator(anonymous=True, user_id=7) is None
    lookup.assert_not_awaited()


async def test_applicant_department_id_uses_primary_department(monkeypatch) -> None:
    """实名发起人写入主部门 ID。"""
    monkeypatch.setattr(
        "bisheng.database.models.department.UserDepartmentDao.aget_user_primary_department",
        AsyncMock(return_value=SimpleNamespace(department_id=101)),
    )
    assert await applicant_department_id_for_initiator(anonymous=False, user_id=7) == 101
