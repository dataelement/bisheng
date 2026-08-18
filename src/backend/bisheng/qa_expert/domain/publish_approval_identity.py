# ruff: noqa: RUF002, RUF003
"""转公开审批展示身份：匿名者用同题别名，且不带部门。"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from bisheng.qa_expert.domain.identity import IdentityService
from bisheng.qa_expert.domain.repositories import AnswerRepository, QuestionRepository

# 审批 UI 不破匿名，与站内信同一视角。
_ANON_VIEWER = SimpleNamespace(user_id=0, is_admin=lambda: False, role=None)


@dataclass(frozen=True)
class PublishApprovalIdentity:
    """审批展示用身份；anonymous 为真时部门字段必须清空。"""

    display_name: str
    anonymous: bool


def question_id_from_instance(instance: Any) -> int | None:
    """从审批实例快照或业务资源 ID 取出 qa_question.id。"""
    payload = getattr(instance, "payload_snapshot", None) or {}
    raw = payload.get("question_id") if isinstance(payload, dict) else None
    if raw is None:
        raw = getattr(instance, "business_resource_id", None)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def anonymous_choice_for_user(question: Any, answers: list[Any], user_id: int) -> tuple[bool, int | None]:
    """按提问者预选项或该用户有效回答，取出匿名与 reveal_on_public。"""
    anonymous = False
    reveal: int | None = None
    if int(getattr(question, "user_id", 0) or 0) == int(user_id):
        anonymous = bool(int(getattr(question, "asker_anonymous", 0) or 0))
        reveal = getattr(question, "asker_reveal_on_public", None)
    for answer in answers:
        if int(getattr(answer, "user_id", 0) or 0) != int(user_id):
            continue
        if not bool(int(getattr(answer, "anonymous", 0) or 0)):
            continue
        anonymous = True
        reveal = getattr(answer, "reveal_on_public", None)
        break
    return anonymous, reveal


async def display_name_for_publish_user(
    question: Any,
    *,
    user_id: int,
    real_name: str,
    answers: list[Any] | None = None,
    identity_service: IdentityService | None = None,
) -> PublishApprovalIdentity:
    """单人展示名；创建审批实例时给发起人用。"""
    if answers is None:
        answers = await AnswerRepository().list_all_by_question_id(int(question.id))
    mapping = await build_publish_identity_map(
        question,
        user_ids=[int(user_id)],
        real_name_map={int(user_id): real_name or ""},
        answers=answers,
        identity_service=identity_service,
    )
    found = mapping.get(int(user_id))
    if found is not None:
        return found
    return PublishApprovalIdentity(display_name=real_name or "", anonymous=False)


async def build_publish_identity_map(
    question: Any,
    *,
    user_ids: list[int],
    real_name_map: dict[int, str],
    answers: list[Any],
    identity_service: IdentityService | None = None,
) -> dict[int, PublishApprovalIdentity]:
    """本题内若干用户的审批展示名。"""
    identity_svc = identity_service or IdentityService()
    result: dict[int, PublishApprovalIdentity] = {}
    question_type = str(getattr(question, "question_type", "") or "")
    tenant_id = int(getattr(question, "tenant_id", 1) or 1)
    question_id = int(question.id)
    for raw_uid in user_ids:
        user_id = int(raw_uid)
        if user_id <= 0:
            continue
        anonymous, reveal = anonymous_choice_for_user(question, answers, user_id)
        real_name = real_name_map.get(user_id) or ""
        if not anonymous:
            result[user_id] = PublishApprovalIdentity(display_name=real_name, anonymous=False)
            continue
        view = await identity_svc.mask_identity(
            _ANON_VIEWER,
            question_id=question_id,
            user_id=user_id,
            real_name=real_name,
            anonymous=True,
            question_type=question_type,
            reveal_on_public=reveal,
            tenant_id=tenant_id,
        )
        result[user_id] = PublishApprovalIdentity(display_name=view.display_name, anonymous=True)
    return result


async def load_identities_for_instances(
    instances: list[Any],
    *,
    extra_user_ids_by_instance: dict[int, list[int]],
    real_name_map: dict[int, str],
) -> dict[int, dict[int, PublishApprovalIdentity]]:
    """按审批实例批量加载展示身份；返回 instance_id → {user_id → identity}。"""
    question_ids: list[int] = []
    instance_question: dict[int, int] = {}
    user_ids_by_question: dict[int, set[int]] = {}
    for instance in instances:
        if instance is None:
            continue
        instance_id = int(getattr(instance, "id", 0) or 0)
        question_id = question_id_from_instance(instance)
        if instance_id <= 0 or question_id is None:
            continue
        instance_question[instance_id] = question_id
        question_ids.append(question_id)
        wanted = user_ids_by_question.setdefault(question_id, set())
        applicant_id = int(getattr(instance, "applicant_user_id", 0) or 0)
        if applicant_id > 0:
            wanted.add(applicant_id)
        for uid in extra_user_ids_by_instance.get(instance_id, []):
            if int(uid) > 0:
                wanted.add(int(uid))
    unique_qids = list(dict.fromkeys(question_ids))
    if not unique_qids:
        return {}

    questions = await QuestionRepository().get_by_ids(unique_qids)
    question_map = {int(row.id): row for row in questions}
    answers = await AnswerRepository().list_all_by_question_ids(unique_qids)
    answers_by_question: dict[int, list[Any]] = {}
    for answer in answers:
        answers_by_question.setdefault(int(answer.question_id), []).append(answer)

    identity_svc = IdentityService()
    await identity_svc.preload_for_questions(unique_qids)
    by_question: dict[int, dict[int, PublishApprovalIdentity]] = {}
    for question_id, user_ids in user_ids_by_question.items():
        question = question_map.get(question_id)
        if question is None:
            continue
        by_question[question_id] = await build_publish_identity_map(
            question,
            user_ids=list(user_ids),
            real_name_map=real_name_map,
            answers=answers_by_question.get(question_id, []),
            identity_service=identity_svc,
        )

    result: dict[int, dict[int, PublishApprovalIdentity]] = {}
    for instance_id, question_id in instance_question.items():
        result[instance_id] = by_question.get(question_id, {})
    return result
