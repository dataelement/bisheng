# ruff: noqa: RUF002
"""关联文档 knowledge 鉴权适配：无权=forbidden，无文件=not_found。不在本域另造映射。"""

from __future__ import annotations

from typing import Any

RELATED_DOC_ACCESS_TIMEOUT_SEC = 3.0


async def check_related_doc_access(user: Any, space_id: int, file_id: int) -> bool | None:
    """True 文件存在；None 文件不存在。

    不在这里调 PermissionService / OpenFGA：当前 LoginUser 缺 get_visible_tenants，
    list_accessible_ids 会卡住 uvicorn 单 worker，整道问题详情 8s 超时。
    可见性由 QuestionService.hydrate_related_docs 按提问者/路人切开。
    """
    del user
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
    return True
