from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from bisheng.common.schemas.telemetry.base_telemetry_schema import UserDepartmentInfo
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.telemetry.domain.mid_table.base import BaseMidTable, BaseRecord
from bisheng.user.domain.repositories.implementations.user_repository_impl import UserRepositoryImpl
from bisheng.utils import generate_uuid


class KnowledgeSpaceContentRecord(BaseRecord):
    record_type: str
    sync_run_id: Optional[str] = None

    space_id: int
    space_name: str
    file_id: int
    file_name: str
    file_type: int

    uploader_user_id: int
    uploader_user_name: str
    uploader_department_infos: List[UserDepartmentInfo] = Field(default_factory=list)

    event_id: Optional[str] = None
    viewer_user_id: Optional[int] = None
    viewer_user_name: Optional[str] = None
    action_result: Optional[str] = None


class KnowledgeSpaceContentStat(BaseMidTable):
    _index_name: str = "mid_knowledge_space_content_stat"
    _mappings: Dict[str, Any] = {
        "record_type": {"type": "keyword"},
        "sync_run_id": {"type": "keyword"},
        "space_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "space_name": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "file_id": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "file_name": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}}},
        "file_type": {"type": "integer"},
        "uploader_user_id": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "uploader_user_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "uploader_department_infos": {
            "type": "nested",
            "properties": {
                "department_id": {
                    "type": "keyword",
                    "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
                },
                "department_name": {
                    "type": "keyword",
                    "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
                },
            },
        },
        "event_id": {"type": "keyword"},
        "viewer_user_id": {"type": "keyword"},
        "viewer_user_name": {"type": "keyword"},
        "action_result": {"type": "keyword"},
    }

    @staticmethod
    async def _get_user_departments(user_id: Optional[int]) -> List[UserDepartmentInfo]:
        if not user_id:
            return []
        async with get_async_db_session() as session:
            user_repository = UserRepositoryImpl(session)
            user = await user_repository.get_user_with_groups_and_roles_by_user_id(user_id)
        if not user:
            return []
        return [
            UserDepartmentInfo(department_id=dept.id, department_name=dept.name)
            for dept in getattr(user, "departments", []) or []
        ]

    @classmethod
    async def log_preview_success(
        cls,
        *,
        file_record: KnowledgeFile,
        space: Knowledge,
        viewer_user_id: int,
        viewer_user_name: str,
    ) -> None:
        event_id = generate_uuid()
        uploader_user_id = int(file_record.user_id or 0)
        uploader_user_name = file_record.user_name or str(uploader_user_id or "")
        record = KnowledgeSpaceContentRecord(
            es_id=f"preview_{event_id}",
            record_type="preview",
            timestamp=int(datetime.now().timestamp()),
            user_id=int(viewer_user_id or 0),
            user_name=viewer_user_name or str(viewer_user_id or ""),
            user_group_infos=[],
            user_role_infos=[],
            user_department_infos=[],
            space_id=int(space.id),
            space_name=space.name,
            file_id=int(file_record.id),
            file_name=file_record.file_name,
            file_type=int(file_record.file_type),
            uploader_user_id=uploader_user_id,
            uploader_user_name=uploader_user_name,
            uploader_department_infos=await cls._get_user_departments(uploader_user_id),
            event_id=event_id,
            viewer_user_id=int(viewer_user_id or 0),
            viewer_user_name=viewer_user_name or str(viewer_user_id or ""),
            action_result="success",
        )
        await cls(ensure_sync_index=False).insert_record(record)

    def delete_stale_file_records_sync(self, sync_run_id: str) -> int:
        result = self.delete_by_query_sync(
            {
                "bool": {
                    "filter": [{"term": {"record_type": "file"}}],
                    "must_not": [{"term": {"sync_run_id": sync_run_id}}],
                }
            },
            refresh=True,
        )
        return int(result.get("deleted", 0) or 0)
