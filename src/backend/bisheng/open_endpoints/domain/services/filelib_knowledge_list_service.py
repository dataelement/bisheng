from fastapi import Request

from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeInvalidCursorError
from bisheng.common.schemas.api import PageInfiniteCursorData
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.open_endpoints.domain.schemas.filelib import FilelibKnowledgeRead

_SPACE_LIST_CURSOR_CONTEXT = "filelib-space|sort_by=update_time"


class FilelibKnowledgeListService:
    """按门户可见范围查询 Filelib 知识空间列表。"""

    def __init__(self, request: Request, login_user: UserPayload):
        self.login_user = login_user
        self.space_service = KnowledgeSpaceService(request=request, login_user=login_user)

    async def list_spaces(
        self,
        *,
        name: str | None,
        cursor: str | None,
        page_size: int,
    ) -> PageInfiniteCursorData[FilelibKnowledgeRead]:
        try:
            decoded_cursor = decode_cursor(
                cursor,
                expected_key_len=2,
                expected_context=_SPACE_LIST_CURSOR_CONTEXT,
            )
        except CursorDecodeError as exc:
            raise KnowledgeInvalidCursorError(exception=exc)

        level_by_id = await self.space_service.get_existing_portal_visible_space_levels()
        rows = await KnowledgeDao.aget_knowledge_by_ids_cursor(
            list(level_by_id),
            knowledge_type=KnowledgeTypeEnum.SPACE,
            name=name,
            sort_by="update_time",
            limit=page_size + 1,
            cursor=decoded_cursor,
        )

        has_more = len(rows) > page_size
        visible_rows = rows[:page_size]
        converted = await KnowledgeService.aconvert_knowledge_read(
            self.login_user,
            visible_rows,
            permission_map={},
        )
        items = [
            FilelibKnowledgeRead(
                **item.model_dump(),
                space_level=level_by_id[int(item.id)],
            )
            for item in converted
        ]

        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(
                (last.update_time, last.id),
                context=_SPACE_LIST_CURSOR_CONTEXT,
            )
        return PageInfiniteCursorData(
            data=items,
            page_size=page_size,
            has_more=has_more,
            next_cursor=next_cursor,
        )
