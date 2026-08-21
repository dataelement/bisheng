# ruff: noqa: RUF002
"""专家问答关联文档上下文只读放行：can_read 不足时按问答角色补预览权。"""

from __future__ import annotations

from typing import Any, Literal

from loguru import logger

from bisheng.database.models.qa_expert import (
    EXPERT_STATUS_ACTIVE,
    QUESTION_TYPE_DIRECTED,
    QUESTION_TYPE_PUBLIC,
)
from bisheng.qa_expert.domain.capability import CapabilityResolver, CapabilitySnapshot
from bisheng.qa_expert.domain.question_query import parse_related_doc_ref, parse_related_doc_tokens
from bisheng.qa_expert.domain.related_docs_access import resolve_related_doc_target

DocSource = Literal["question", "answer"]


async def canonical_pairs_in_related_docs(raw: str | None) -> set[tuple[int, int]]:
    """解析 related_docs 串为 canonical (space_id, file_id) 集合（含收藏引用改写）。"""
    pairs: set[tuple[int, int]] = set()
    for token in parse_related_doc_tokens(raw):
        parsed = parse_related_doc_ref(token)
        if parsed is None:
            continue
        try:
            resolved = await resolve_related_doc_target(*parsed)
        except Exception:
            logger.exception("resolve related doc target failed token=%s", token)
            resolved = parsed
        if resolved is None:
            continue
        pairs.add((int(resolved[0]), int(resolved[1])))
    return pairs


async def _load_question(question_id: int) -> Any | None:
    from bisheng.qa_expert.domain.repositories import QuestionRepository

    return await QuestionRepository().get_by_id(int(question_id))


async def _load_invited_user_ids(question_id: int) -> frozenset[int]:
    from bisheng.qa_expert.domain.repositories import QuestionInviteRepository

    invite_map = await QuestionInviteRepository().list_user_ids_by_question_ids([int(question_id)])
    return frozenset(invite_map.get(int(question_id), set()))


async def _is_active_expert_user(user_id: int) -> bool:
    from bisheng.qa_expert.domain.repositories import ExpertRepository

    expert = await ExpertRepository().get_by_user_id(int(user_id))
    if expert is None:
        return False
    return int(getattr(expert, "status", 0) or 0) == EXPERT_STATUS_ACTIVE


def _viewer_user_id(user: Any | None) -> int | None:
    if user is None:
        return None
    value = getattr(user, "user_id", None)
    return int(value) if value is not None else None


def _question_visible_to_viewer(user: Any, question: Any, invited_user_ids: frozenset[int]) -> bool:
    """与详情页一致：不可见问题不得借 QA 上下文越权读文档。"""
    snapshot = CapabilitySnapshot(invited_user_ids=invited_user_ids)
    result = CapabilityResolver().resolve(user, question, snapshot)
    return bool(result.capabilities.visible)


async def _can_view_question_related_doc(
    user: Any,
    *,
    question: Any,
    invited_user_ids: frozenset[int],
    space_id: int,
    file_id: int,
) -> bool:
    """提问侧关联文档：定向/公开邀请专家，或公开无邀请时全体在库专家。"""
    viewer_id = _viewer_user_id(user)
    if viewer_id is None:
        return False
    pairs = await canonical_pairs_in_related_docs(getattr(question, "related_docs", None))
    if (int(space_id), int(file_id)) not in pairs:
        return False

    question_type = str(getattr(question, "question_type", QUESTION_TYPE_PUBLIC) or QUESTION_TYPE_PUBLIC)
    if question_type == QUESTION_TYPE_DIRECTED:
        return viewer_id in invited_user_ids
    if invited_user_ids:
        return viewer_id in invited_user_ids
    return await _is_active_expert_user(viewer_id)


async def _can_view_answer_related_doc(
    user: Any,
    *,
    question: Any,
    space_id: int,
    file_id: int,
) -> bool:
    """回答侧关联文档：仅提问者可读，且文档须出现在该问题下任一回答的 related_docs。"""
    viewer_id = _viewer_user_id(user)
    asker_id = int(getattr(question, "user_id", 0) or 0)
    if viewer_id is None or asker_id <= 0 or viewer_id != asker_id:
        return False

    from bisheng.qa_expert.domain.repositories import AnswerRepository

    answers = await AnswerRepository().list_all_by_question_id(int(question.id))
    target = (int(space_id), int(file_id))
    for answer in answers:
        pairs = await canonical_pairs_in_related_docs(getattr(answer, "related_docs", None))
        if target in pairs:
            return True
    return False


async def check_qa_related_doc_context_access(
    user: Any,
    *,
    question_id: int,
    space_id: int,
    file_id: int,
    doc_source: DocSource,
) -> bool:
    """校验 QA 上下文是否允许只读预览指定文档；失败不抛错。"""
    try:
        from bisheng.qa_expert.domain.related_docs_access import _file_belongs_to_space

        if not await _file_belongs_to_space(int(space_id), int(file_id)):
            return False
        question = await _load_question(int(question_id))
        if question is None:
            return False
        invited_user_ids = await _load_invited_user_ids(int(question_id))
        if not _question_visible_to_viewer(user, question, invited_user_ids):
            return False
        if doc_source == "question":
            return await _can_view_question_related_doc(
                user,
                question=question,
                invited_user_ids=invited_user_ids,
                space_id=int(space_id),
                file_id=int(file_id),
            )
        if doc_source == "answer":
            return await _can_view_answer_related_doc(
                user,
                question=question,
                space_id=int(space_id),
                file_id=int(file_id),
            )
        return False
    except Exception:
        logger.exception(
            "check_qa_related_doc_context_access failed question_id=%s space=%s file=%s source=%s",
            question_id,
            space_id,
            file_id,
            doc_source,
        )
        return False
