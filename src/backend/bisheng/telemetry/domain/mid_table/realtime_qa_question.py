from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.telemetry.domain.mid_table.base import BaseMidTable, BaseRecord
from bisheng.telemetry.domain.mid_table.content_stat_reconcile import ContentStatReconciler
from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import resolve_organization_names

QA_TYPE_LABELS = {
    "expert": "专家问答",
    "smart": "智能问答",
    "document": "文档内AI对话",
}

# Asker's primary department, split by org_level on the materialized path.
# Squad stays on primary_department_name; these three are the dashboard dimensions.
ASKER_ORGANIZATION_FIELDS = (
    "asker_company_name",
    "asker_department_name",
    "asker_office_name",
)
ASKER_ORG_RESOLVED = "asker_org_resolved"
_EVENT_DEPARTMENT_FIELDS = (
    "primary_department_id",
    "primary_department_name",
    "department_source",
)


def path_department_ids(department: Any | None) -> list[int]:
    """Department ids on the materialized path, including the start node."""
    if department is None:
        return []
    ordered: list[int] = []
    for value in str(getattr(department, "path", None) or "").strip("/").split("/"):
        if not value.isdigit():
            continue
        department_id = int(value)
        if department_id not in ordered:
            ordered.append(department_id)
    start_id = getattr(department, "id", None)
    if start_id is not None and int(start_id) not in ordered:
        ordered.append(int(start_id))
    return ordered


def collect_path_department_ids(departments: Iterable[Any]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for department in departments:
        for department_id in path_department_ids(department):
            if department_id not in seen:
                seen.add(department_id)
                ordered.append(department_id)
    return ordered


def asker_organization_fields(
    department: Any | None,
    departments_by_id: Mapping[int, Any],
) -> dict[str, str | None]:
    """First active company, department, and office on the asker's primary path."""
    snapshot = resolve_organization_names(department, departments_by_id)
    return {
        "asker_company_name": snapshot.company_name,
        "asker_department_name": snapshot.department_name,
        "asker_office_name": snapshot.office_name,
    }


def asker_organization_document(
    department: Any | None,
    departments_by_id: Mapping[int, Any],
) -> dict[str, str]:
    """Org names plus a resolved marker. Empty levels are omitted so terms aggs skip them."""
    document = {
        field: value for field, value in asker_organization_fields(department, departments_by_id).items() if value
    }
    document[ASKER_ORG_RESOLVED] = "1"
    return document


async def _departments_by_ids(department_ids: list[int]) -> dict[int, Any]:
    if not department_ids:
        return {}
    rows = await DepartmentDao.aget_by_ids(department_ids)
    return {int(row.id): row for row in rows if getattr(row, "id", None) is not None}


def _same_department_id(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return str(left) == str(right)


def merge_qa_document(current: dict, desired: dict) -> dict:
    result = dict(desired)
    if current.get(ASKER_ORG_RESOLVED):
        result[ASKER_ORG_RESOLVED] = current[ASKER_ORG_RESOLVED]
    if current.get("department_source") != "event_time":
        return result
    for field in _EVENT_DEPARTMENT_FIELDS:
        if field in current:
            result[field] = current[field]
        else:
            result.pop(field, None)
    # Repair computes org names from today's primary department. Reuse them only
    # when that department is still the one snapshotted at question time.
    same_department = _same_department_id(
        current.get("primary_department_id"),
        desired.get("primary_department_id"),
    )
    for field in ASKER_ORGANIZATION_FIELDS:
        current_value = current.get(field)
        if current_value not in (None, ""):
            result[field] = current_value
        elif not same_department:
            result.pop(field, None)
    return result


class RealtimeQaQuestionRecord(BaseRecord):
    tenant_id: int = 1
    question_id: str
    qa_type: str
    qa_type_name: str
    scene: str
    source_app: str
    primary_department_id: int | None = None
    primary_department_name: str | None = None
    asker_company_name: str | None = None
    asker_department_name: str | None = None
    asker_office_name: str | None = None
    asker_org_resolved: str | None = None
    department_source: str
    space_id: int | None = None
    file_id: int | None = None
    conversation_id: str | None = None
    business_domain_code: str | None = None
    projection_updated_at: int


class RealtimeQaQuestionFact(BaseMidTable):
    _index_name = "mid_realtime_qa_question_fact"
    _update_mappings_on_existing = True

    def reconcile_records_sync(self, records: list[RealtimeQaQuestionRecord]) -> dict:
        result = ContentStatReconciler(self._es_client_sync, self._index_name, str).reconcile(
            {record.es_id: record.model_dump(exclude={"es_id"}) for record in records}, merge_qa_document
        )
        return result

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
        "asker_company_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "asker_department_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "asker_office_name": {
            "type": "keyword",
            "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
        },
        "asker_org_resolved": {"type": "keyword"},
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
        departments_by_id = await _departments_by_ids(path_department_ids(primary_department))
        if primary_department is not None and getattr(primary_department, "id", None) is not None:
            departments_by_id.setdefault(int(primary_department.id), primary_department)
        org_fields = asker_organization_document(primary_department, departments_by_id)
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
            asker_company_name=org_fields.get("asker_company_name"),
            asker_department_name=org_fields.get("asker_department_name"),
            asker_office_name=org_fields.get("asker_office_name"),
            asker_org_resolved=org_fields.get(ASKER_ORG_RESOLVED),
            department_source="event_time",
            space_id=int(space_id) if str(space_id or "").isdigit() else None,
            file_id=int(file_id) if str(file_id or "").isdigit() else None,
            conversation_id=conversation_id,
            business_domain_code=business_domain_code,
            projection_updated_at=now,
        )
        await cls(ensure_sync_index=False).insert_record(record)
        return record
