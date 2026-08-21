# ruff: noqa: RUF002
"""关联文档 knowledge 鉴权：文件存在性 + 知识空间 can_read。无权=forbidden，无文件=not_found。"""

from __future__ import annotations

from typing import Any

from loguru import logger

RELATED_DOC_ACCESS_TIMEOUT_SEC = 3.0


def related_doc_display_title(row: Any | None) -> str | None:
    """展示名与提问选择器一致：优先 file_name，没有再退 alias_name。"""
    if row is None:
        return None
    name = str(getattr(row, "file_name", None) or "").strip()
    alias = str(getattr(row, "alias_name", None) or "").strip()
    return name or alias or None


def favorite_source_ref(row: Any | None) -> tuple[int, int] | None:
    """收藏引用解析为源空间/源文件；非引用或元数据残缺返回 None。"""
    if row is None:
        return None
    if str(getattr(row, "file_source", "") or "") != "favorite_reference":
        return None
    meta = getattr(row, "user_metadata", None) or {}
    if not isinstance(meta, dict):
        return None
    ref = meta.get("favorite_reference") or {}
    if not isinstance(ref, dict):
        return None
    try:
        src_space = int(ref.get("source_space_id") or 0)
        src_file = int(ref.get("source_file_id") or 0)
    except (TypeError, ValueError):
        return None
    if src_space <= 0 or src_file <= 0:
        return None
    return src_space, src_file


async def _load_related_doc_file(space_id: int, file_id: int) -> Any | None:
    """取出 knowledgefile；无记录或空间不匹配则 None。"""
    try:
        from sqlmodel import select

        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    except Exception:
        return None

    async with get_async_db_session() as session:
        stmt = select(KnowledgeFile).where(KnowledgeFile.id == int(file_id))
        result = await session.exec(stmt)
        row = result.first()
    if row is None:
        return None
    knowledge_id = int(getattr(row, "knowledge_id", 0) or 0)
    if knowledge_id and knowledge_id != int(space_id):
        return None
    return row


async def resolve_related_doc_target(space_id: int, file_id: int) -> tuple[int, int] | None:
    """解析应对齐预览的 space/file。

    普通缺失文件返回原 pair，交给 checker 标 not_found/forbidden。
    收藏引用且源存在则返回源 pair；收藏指针在但源已删返回 None。
    """
    row = await _load_related_doc_file(int(space_id), int(file_id))
    if row is None:
        return int(space_id), int(file_id)
    source = favorite_source_ref(row)
    if source is None:
        return int(space_id), int(file_id)
    src_row = await _load_related_doc_file(source[0], source[1])
    if src_row is None:
        return None
    return source


async def canonicalize_related_docs(raw: str | None) -> str | None:
    """把 related_docs 串里的收藏引用改写成源 space-file，避免详情链到空指针。"""
    from bisheng.qa_expert.domain.question_query import parse_related_doc_ref, parse_related_doc_tokens

    tokens = parse_related_doc_tokens(raw)
    if not tokens:
        return None
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        parsed = parse_related_doc_ref(token)
        if parsed is None:
            if token not in seen:
                seen.add(token)
                out.append(token)
            continue
        resolved = await resolve_related_doc_target(*parsed)
        pair = resolved if resolved is not None else parsed
        canonical = f"{pair[0]}-{pair[1]}"
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return ";".join(out) if out else None


async def safe_canonicalize_related_docs(raw: str | None) -> str | None:
    """canonicalize 的容错包装：解析失败保留原串，不阻断提问/回答。"""
    if not raw:
        return raw
    try:
        canonical = await canonicalize_related_docs(raw)
    except Exception:
        logger.exception("canonicalize related_docs failed")
        return raw
    return canonical if canonical is not None else raw


async def _file_belongs_to_space(space_id: int, file_id: int) -> bool:
    """knowledgefile 是否存在且归属该知识空间。"""
    return await _load_related_doc_file(space_id, file_id) is not None


async def load_related_doc_title(space_id: int, file_id: int) -> str | None:
    """读取 knowledgefile 展示名；找不到则 None。不鉴权，由 hydrate 决定是否下发。"""
    try:
        row = await _load_related_doc_file(int(space_id), int(file_id))
    except Exception:
        return None
    return related_doc_display_title(row)


async def _personal_space_owner_id(space_id: int) -> int | None:
    """个人知识库返回 owner 的 user_id；部门/公开等返回 None。"""
    try:
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
        from bisheng.knowledge.domain.models.knowledge_space_scope import (
            KnowledgeSpaceLevelEnum,
            KnowledgeSpaceScopeDao,
        )

        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(int(space_id))
        if scope is not None:
            level = getattr(scope.level, "value", scope.level)
            if level != KnowledgeSpaceLevelEnum.PERSONAL.value:
                return None
            owner_id = int(getattr(scope, "owner_id", 0) or 0)
            if owner_id:
                return owner_id
        space = await KnowledgeDao.aquery_by_id(int(space_id))
        if space is None:
            return None
        if scope is None:
            # 无 scope 行时与知识空间列表一致：按个人库 + knowledge.user_id 推断
            owner_id = int(getattr(space, "user_id", 0) or 0)
            return owner_id if owner_id else None
        owner_id = int(getattr(space, "user_id", 0) or 0)
        return owner_id if owner_id else None
    except Exception:
        return None


async def _space_can_read(user: Any, space_id: int) -> bool:
    """单点 PermissionService.check，禁止 list_accessible_ids。"""
    user_id = getattr(user, "user_id", None) if user is not None else None
    if user_id is None:
        return False
    try:
        from bisheng.permission.domain.services.permission_service import PermissionService

        return bool(
            await PermissionService.check(
                user_id=int(user_id),
                relation="can_read",
                object_type="knowledge_space",
                object_id=str(int(space_id)),
                login_user=user,
            )
        )
    except Exception:
        return False


async def check_related_doc_access_with_qa_context(
    user: Any,
    space_id: int,
    file_id: int,
    *,
    space_cache: dict[int, bool] | None = None,
    question_id: int | None = None,
    doc_source: str | None = None,
) -> bool | None:
    """在知识空间 can_read 之外，按专家问答上下文补只读 accessible。"""
    base = await check_related_doc_access(user, space_id, file_id, space_cache=space_cache)
    if base is True:
        return True
    if base is None:
        return None
    if question_id is None or doc_source not in {"question", "answer"}:
        return False
    from bisheng.qa_expert.domain.qa_related_doc_context_access import (
        check_qa_related_doc_context_access,
    )

    if await check_qa_related_doc_context_access(
        user,
        question_id=int(question_id),
        space_id=int(space_id),
        file_id=int(file_id),
        doc_source=doc_source,  # type: ignore[arg-type]
    ):
        return True
    return False


async def check_related_doc_access(
    user: Any,
    space_id: int,
    file_id: int,
    *,
    space_cache: dict[int, bool] | None = None,
) -> bool | None:
    """True 可读；False 文件在但当前用户无权；None 文件不存在或空间不匹配。

    同一次 hydrate 通过 space_cache 对相同 space_id 只 check 一次。
    """
    if not await _file_belongs_to_space(int(space_id), int(file_id)):
        return None
    cache_key = int(space_id)
    viewer_id = getattr(user, "user_id", None) if user is not None else None
    is_admin = bool(callable(getattr(user, "is_admin", None)) and user.is_admin())
    personal_owner_id = await _personal_space_owner_id(cache_key)
    if (
        not is_admin
        and personal_owner_id is not None
        and viewer_id is not None
        and int(personal_owner_id) != int(viewer_id)
    ):
        # 非管理员看他人个人库：不走 can_read（避免误共享）；系统管理员仍走下方鉴权。
        if space_cache is not None:
            space_cache[cache_key] = False
        return False
    if space_cache is not None and cache_key in space_cache:
        return space_cache[cache_key]
    allowed = await _space_can_read(user, cache_key)
    if space_cache is not None:
        space_cache[cache_key] = allowed
    return allowed
