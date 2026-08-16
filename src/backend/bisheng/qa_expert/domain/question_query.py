# ruff: noqa: RUF001, RUF002, RUF003
"""提问/列表辅助：邀请解析、筛参归一、展示态匹配。不查库。"""

from __future__ import annotations

from typing import Any

from bisheng.qa_expert.domain.capability import (
    derive_display_status,
    is_unresolved,
)

MAX_INVITES = 3
QUESTION_TYPE_PUBLIC = "public"
QUESTION_TYPE_DIRECTED = "directed"
FILTER_MINE = "mine"
FILTER_INVITED_ME = "invited_me"
# 现网列表 status=3/4 只表示「我的 / 邀请我的」，不是待采纳
LEGACY_STATUS_MINE = 3
LEGACY_STATUS_INVITED_ME = 4


def parse_invite_expert_ids(*, invited_expert_ids: list[int] | None, invited_experts: str | None) -> list[int]:
    """合并 invited_expert_ids 与分号串，去重保序。"""
    values: list[int] = []
    seen: set[int] = set()
    source: list[Any] = list(invited_expert_ids or [])
    if not source and invited_experts:
        source = [part for part in str(invited_experts).replace("，", ";").split(";") if part.strip()]
    for item in source:
        try:
            expert_id = int(item)
        except (TypeError, ValueError):
            continue
        if expert_id <= 0 or expert_id in seen:
            continue
        seen.add(expert_id)
        values.append(expert_id)
    return values


def serialize_invite_ids(expert_ids: list[int]) -> str | None:
    """双写旧列 invited_experts，供存量读路径过渡。"""
    if not expert_ids:
        return None
    return ";".join(str(item) for item in expert_ids)


def serialize_expert_names(experts: list[Any]) -> str | None:
    """按邀请顺序拼接专家姓名，写入 qa_question.experts_names。"""
    names: list[str] = []
    for expert in experts:
        name = str(getattr(expert, "expert_name", "") or "").strip()
        if name:
            names.append(name)
    if not names:
        return None
    return ";".join(names)


def invite_display_names_need_hydrate(experts_names: str | None, invited_experts: str | None) -> bool:
    """名字为空，或误把专家 ID 串当成名字时，需要按档案回填。"""
    ids = parse_invite_expert_ids(invited_expert_ids=None, invited_experts=invited_experts)
    if not ids:
        return False
    names = (experts_names or "").strip()
    if not names:
        return True
    tokens = [part.strip() for part in names.replace("，", ";").split(";") if part.strip()]
    return bool(tokens) and all(token.isdigit() for token in tokens)


def serialize_related_doc_ids(related_doc_ids: list[str] | None, related_docs: str | None) -> str | None:
    """优先 related_doc_ids；否则沿用已有 related_docs 串。"""
    if related_doc_ids:
        tokens = [str(item).strip() for item in related_doc_ids if str(item).strip()]
        return ";".join(tokens) if tokens else None
    if related_docs and str(related_docs).strip():
        return str(related_docs).strip()
    return None


def parse_related_doc_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    text = str(raw).strip()
    if not text:
        return []
    return [part.strip() for part in text.replace(",", ";").split(";") if part.strip()]


def parse_related_doc_ref(token: str) -> tuple[int, int] | None:
    """解析 `{spaceId}-{fileId}`；失败返回 None。"""
    parts = str(token).strip().split("-", 1)
    if len(parts) != 2:
        return None
    try:
        space_id = int(parts[0])
        file_id = int(parts[1])
    except (TypeError, ValueError):
        return None
    if space_id <= 0 or file_id <= 0:
        return None
    return space_id, file_id


def normalize_list_filter(*, status: int | None, list_filter: str | None) -> str | None:
    """filter 优先；status=3/4 映射为 mine/invited_me，禁止当成待采纳。"""
    if list_filter in {FILTER_MINE, FILTER_INVITED_ME}:
        return list_filter
    if status == LEGACY_STATUS_MINE:
        return FILTER_MINE
    if status == LEGACY_STATUS_INVITED_ME:
        return FILTER_INVITED_ME
    return None


def question_display_status(question: Any) -> str:
    adopt_count = int(getattr(question, "adopt_count", 0) or 0)
    effective = int(
        getattr(question, "effective_answer_count", None)
        if getattr(question, "effective_answer_count", None) is not None
        else (getattr(question, "answer_count", 0) or 0)
    )
    return derive_display_status(effective_answer_count=effective, adopt_count=adopt_count)


def matches_display_status(question: Any, display_status: str | None) -> bool:
    if not display_status:
        return True
    current = question_display_status(question)
    if display_status == "unresolved":
        return is_unresolved(current)
    return current == display_status


def normalize_question_type(value: Any) -> str:
    text = str(value or QUESTION_TYPE_PUBLIC).strip().lower()
    if text == QUESTION_TYPE_DIRECTED:
        return QUESTION_TYPE_DIRECTED
    return QUESTION_TYPE_PUBLIC
