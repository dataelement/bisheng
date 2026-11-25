"""MCP-local orchestration for QA-library entries.

Mirrors the frozen v2 filelib QA endpoints (``add_qa``, ``add_relative_qa``,
``update_qa``, ``delete_qa``, ``detail_qa``, ``query_qa``) without calling the
FastAPI endpoint functions, in the same way as ``application.py``. Business
authorization still runs in ``KnowledgeService.judge_knowledge_access``.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from starlette.concurrency import run_in_threadpool

from bisheng.api.services import knowledge_imp
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.knowledge.domain.models.knowledge_file import QAKnoweldgeDao, QAKnowledgeUpsert
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.open_endpoints.domain.utils import get_open_api_operator

# query_qa reads back only these QA sources (1 manual, 2 audit), the same selection as the v2 endpoint.
_QUERY_SOURCES = [1, 2]


def decode_answers(value: object) -> list[str] | None:
    """Decode the historical JSON answers field; return None for malformed legacy rows."""
    if isinstance(value, list):
        answers = value
    elif isinstance(value, str):
        try:
            answers = json.loads(value)
        except json.JSONDecodeError:
            return None
    else:
        return None
    if not isinstance(answers, list) or any(not isinstance(item, str) for item in answers):
        return None
    return answers


def _normalize_knowledge_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdecimal():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _qa_with_access(qa_id: int, *, login_user, action: str):
    qa = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(qa_id)
    if qa is None:
        raise NotFoundError.http_exception()
    knowledge = KnowledgeService.judge_knowledge_access(login_user, qa.knowledge_id, action)
    return qa, knowledge


def _query_sync(login_user, time_range: list[str]) -> list[Any]:
    rows = QAKnoweldgeDao.query_by_condition_v1(
        source=_QUERY_SOURCES, create_start=time_range[0], create_end=time_range[1]
    )
    candidates = []
    invalid = 0
    for qa in rows or []:
        knowledge_id = _normalize_knowledge_id(getattr(qa, "knowledge_id", None))
        if knowledge_id is None:
            invalid += 1
            continue
        candidates.append((qa, knowledge_id))
    knowledge_ids = list(dict.fromkeys(item[1] for item in candidates))
    action_map = {}
    if knowledge_ids:
        action_map = KnowledgeService.permission_service.get_knowledge_action_map_sync(
            login_user, knowledge_ids, ["visible"]
        )
    visible = []
    for qa, knowledge_id in candidates:
        if "visible" not in action_map.get(knowledge_id, set()):
            continue
        answers = decode_answers(getattr(qa, "answers", None))
        if answers is None:
            invalid += 1
            continue
        qa.answers = answers
        visible.append(qa)
    if invalid:
        logger.warning("mcp qa_query filtered legacy rows: invalid_count={}", invalid)
    return visible


async def query_qa(*, time_range: list[str]) -> list[Any]:
    login_user = get_open_api_operator()
    return await run_in_threadpool(_query_sync, login_user, time_range)


def _detail_sync(login_user, qa_id: int):
    qa, _ = _qa_with_access(qa_id, login_user=login_user, action="visible")
    return qa


async def detail_qa(*, qa_id: int):
    login_user = get_open_api_operator()
    return await run_in_threadpool(_detail_sync, login_user, qa_id)


def _add_sync(login_user, knowledge_id: int, items) -> list[Any]:
    knowledge = KnowledgeService.judge_knowledge_access(login_user, knowledge_id, "edit")
    logger.info("mcp qa_add knowledge_id={} size={}", knowledge_id, len(items))
    results = []
    for item in items:
        upsert = QAKnowledgeUpsert(
            knowledge_id=knowledge_id,
            questions=[item.question],
            answers=item.answer,
            user_id=login_user.user_id,
            extra_meta=json.dumps(item.extra or {}),
            source=3,
        )
        results.append(knowledge_imp.add_qa(knowledge, upsert))
    return results


async def add_qa(*, knowledge_id: int, items) -> list[Any]:
    login_user = get_open_api_operator()
    return await run_in_threadpool(_add_sync, login_user, knowledge_id, items)


def _add_relative_sync(login_user, knowledge_id: int, qa_id: int, relative_questions: list[str]):
    qa_db, knowledge = _qa_with_access(qa_id, login_user=login_user, action="edit")
    if qa_db.knowledge_id != knowledge_id:
        raise NotFoundError.http_exception()
    data = qa_db.dict()
    data["answers"] = json.loads(data["answers"])
    upsert = QAKnowledgeUpsert.validate(data)
    upsert.questions.extend(relative_questions)
    return knowledge_imp.add_qa(knowledge, upsert)


async def add_relative_qa(*, knowledge_id: int, qa_id: int, relative_questions: list[str]):
    login_user = get_open_api_operator()
    return await run_in_threadpool(_add_relative_sync, login_user, knowledge_id, qa_id, relative_questions)


def _update_sync(login_user, command) -> None:
    qa, knowledge = _qa_with_access(command.id, login_user=login_user, action="edit")
    if command.original_question:
        qa.questions = [command.question if item == command.original_question else item for item in qa.questions]
    elif command.question is not None:
        qa.questions = [command.question]
    if command.answer:
        qa.answers = json.dumps(command.answer, ensure_ascii=False)
    QAKnoweldgeDao.update(qa)
    if command.question:
        knowledge_imp.delete_vector_data(knowledge, file_ids=[command.id])
        knowledge_imp.QA_save_knowledge(knowledge, qa)


async def update_qa(*, command) -> None:
    login_user = get_open_api_operator()
    await run_in_threadpool(_update_sync, login_user, command)


def _delete_sync(login_user, qa_id: int, question: str | None) -> None:
    qa, knowledge = _qa_with_access(qa_id, login_user=login_user, action="edit")
    if question:
        qa.questions = [item for item in qa.questions if item != question]
        QAKnoweldgeDao.update(qa)
    else:
        QAKnoweldgeDao.delete_batch([qa_id])
    knowledge_imp.delete_vector_data(knowledge, file_ids=[qa_id])
    if question:
        knowledge_imp.QA_save_knowledge(knowledge, qa)


async def delete_qa(*, qa_id: int, question: str | None) -> None:
    login_user = get_open_api_operator()
    await run_in_threadpool(_delete_sync, login_user, qa_id, question)


__all__ = [
    "add_qa",
    "add_relative_qa",
    "decode_answers",
    "delete_qa",
    "detail_qa",
    "query_qa",
    "update_qa",
]
