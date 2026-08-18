# ruff: noqa: RUF002
"""转公开审批展示身份：匿名标志与实例 question_id 解析。"""

from types import SimpleNamespace

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
