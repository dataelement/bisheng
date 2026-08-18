# ruff: noqa: RUF002
"""关联文档 knowledge 鉴权：文件存在性 + 知识空间 can_read。无权=forbidden，无文件=not_found。"""

from __future__ import annotations

from typing import Any

RELATED_DOC_ACCESS_TIMEOUT_SEC = 3.0


async def _file_belongs_to_space(space_id: int, file_id: int) -> bool:
    """knowledgefile 是否存在且归属该知识空间。"""
    try:
        from sqlmodel import select

        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    except Exception:
        return False

    async with get_async_db_session() as session:
        stmt = select(KnowledgeFile).where(KnowledgeFile.id == int(file_id))
        result = await session.exec(stmt)
        row = result.first()
    if row is None:
        return False
    knowledge_id = int(getattr(row, "knowledge_id", 0) or 0)
    return (not knowledge_id) or knowledge_id == int(space_id)


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
    if space_cache is not None and cache_key in space_cache:
        return space_cache[cache_key]
    allowed = await _space_can_read(user, cache_key)
    if space_cache is not None:
        space_cache[cache_key] = allowed
    return allowed
