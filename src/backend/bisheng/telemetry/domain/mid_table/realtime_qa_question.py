from datetime import datetime
from typing import Any

from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.telemetry.domain.mid_table.base import BaseMidTable, BaseRecord

QA_TYPE_LABELS = {
    "expert": "专家问答",
    "smart": "智能问答",
    "document": "文档内AI对话",
}


class RealtimeQaQuestionRecord(BaseRecord):
    tenant_id: int = 1
    question_id: str
    qa_type: str
    qa_type_name: str
    scene: str
    source_app: str
    primary_department_id: int | None = None
    primary_department_name: str | None = None
    department_source: str
    space_id: int | None = None
    file_id: int | None = None
    conversation_id: str | None = None
    business_domain_code: str | None = None
    projection_updated_at: int


class RealtimeQaQuestionFact(BaseMidTable):
    _index_name = "mid_realtime_qa_question_fact"
    _update_mappings_on_existing = True
    _mappings: dict[str, Any] = {
        "tenant_id": {"type": "keyword"},
        "question_id": {"type": "keyword"},
        "qa_type": {"type": "keyword"},
        "qa_type_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "scene": {"type": "keyword"},
        "source_app": {"type": "keyword"},
        "primary_department_id": {"type": "keyword"},
        "primary_department_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "department_source": {"type": "keyword"},
        "space_id": {"type": "keyword"},
        "file_id": {"type": "keyword"},
        "conversation_id": {"type": "keyword"},
        "business_domain_code": {"type": "keyword"},
        "projection_updated_at": {
            "type": "date",
            "format": "strict_date_optional_time||epoch_second",
        },
    }

    @classmethod
    async def delete_question(
        cls,
        *,
        tenant_id: int | None,
        question_id: str | int,
        qa_type: str,
    ) -> int:
        """Remove a deleted question from the mutable real-time fact table."""
        normalized_tenant_id = int(tenant_id or 1)
        fact = cls(ensure_sync_index=False)
        await fact.ensure_index_exists()
        response = await fact._es_client.delete_by_query(
            index=fact._index_name,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"tenant_id": normalized_tenant_id}},
                            {"term": {"question_id": str(question_id)}},
                            {"term": {"qa_type": qa_type}},
                        ]
                    }
                }
            },
            refresh=True,
            conflicts="proceed",
        )
        return int(response.get("deleted", 0))

    @classmethod
    async def record_success(
        cls,
        *,
        tenant_id: int | None,
        user_id: int,
        user_name: str,
        question_id: str | int,
        qa_type: str,
        scene: str,
        source_app: str,
        space_id: int | str | None = None,
        file_id: int | str | None = None,
        conversation_id: str | None = None,
        business_domain_code: str | None = None,
        timestamp: int | None = None,
    ) -> RealtimeQaQuestionRecord:
        if qa_type not in QA_TYPE_LABELS:
            raise ValueError(f"unsupported qa_type: {qa_type}")
        normalized_question_id = str(question_id or "").strip()
        if not normalized_question_id:
            raise ValueError("question_id is required")

        primary_membership = await UserDepartmentDao.aget_user_primary_department(user_id)
        primary_department = (
            await DepartmentDao.aget_by_id(primary_membership.department_id) if primary_membership else None
        )
        now = int(datetime.now().timestamp())
        record = RealtimeQaQuestionRecord(
            es_id=f"qa_{int(tenant_id or 1)}_{qa_type}_{normalized_question_id}",
            tenant_id=int(tenant_id or 1),
            timestamp=int(timestamp or now),
            user_id=int(user_id),
            user_name=user_name or str(user_id),
            user_group_infos=[],
            user_role_infos=[],
            user_department_infos=[],
            question_id=normalized_question_id,
            qa_type=qa_type,
            qa_type_name=QA_TYPE_LABELS[qa_type],
            scene=scene,
            source_app=source_app,
            primary_department_id=(int(primary_department.id) if primary_department else None),
            primary_department_name=(primary_department.name if primary_department else None),
            department_source="event_time",
            space_id=int(space_id) if str(space_id or "").isdigit() else None,
            file_id=int(file_id) if str(file_id or "").isdigit() else None,
            conversation_id=conversation_id,
            business_domain_code=business_domain_code,
            projection_updated_at=now,
        )
        await cls(ensure_sync_index=False).insert_record(record)
        return record
