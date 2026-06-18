from __future__ import annotations

import datetime
import json
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from elasticsearch import Elasticsearch, helpers
from elasticsearch import exceptions as es_exceptions
from loguru import logger
from sqlalchemy import text

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_sync_db_session, sync_get_database_connection
from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection_sync

ES_MAPPING = {
    "mappings": {
        "properties": {
            "timestamp": {"type": "date", "format": "strict_date_optional_time||epoch_second"},
            "file_id": {"type": "keyword"},
            "file_name": {"type": "keyword"},
            "file_size": {"type": "long"},
            "file_type": {"type": "keyword"},
            "user_id": {"type": "keyword"},
            "user_name": {"type": "keyword"},
            "knowledge_base_id": {"type": "integer"},
            "knowledge_base_type": {"type": "keyword"},
            "user_group_infos": {
                "type": "nested",
                "properties": {
                    "user_group_id": {"type": "integer"},
                    "user_group_name": {"type": "keyword"},
                },
            },
            "user_role_infos": {
                "type": "nested",
                "properties": {
                    "role_id": {"type": "integer"},
                    "role_name": {"type": "keyword"},
                    "group_id": {"type": "integer"},
                },
            },
            "user_department_infos": {
                "type": "nested",
                "properties": {
                    "department_id": {"type": "integer"},
                    "department_name": {"type": "keyword"},
                },
            },
        }
    }
}

FILE_SQL = """
SELECT
    t.upload_time,
    t.file_id,
    COALESCE(t.file_name, '未命名') AS file_name,
    COALESCE(t.file_size, 0) AS file_size,
    'file' AS file_type,
    t.user_id,
    u.user_name,
    t.knowledge_id AS knowledge_base_id,
    k.type AS knowledge_type
FROM (
    SELECT
        create_time AS upload_time,
        id AS file_id,
        file_name,
        file_size,
        user_id,
        knowledge_id
    FROM {knowledgefile}
    WHERE create_time >= :start_time AND create_time < :end_time
) t
LEFT JOIN {user} u ON t.user_id = u.user_id
LEFT JOIN {knowledge} k ON t.knowledge_id = k.id
"""

QA_SQL = """
SELECT
    t.upload_time,
    t.file_id,
    t.questions,
    'qa' AS file_type,
    t.user_id,
    u.user_name,
    t.knowledge_id AS knowledge_base_id,
    k.type AS knowledge_type
FROM (
    SELECT
        create_time AS upload_time,
        id AS file_id,
        questions,
        user_id,
        knowledge_id
    FROM {qaknowledge}
    WHERE create_time >= :start_time AND create_time < :end_time
) t
LEFT JOIN {user} u ON t.user_id = u.user_id
LEFT JOIN {knowledge} k ON t.knowledge_id = k.id
"""

USER_GROUP_SQL = """
SELECT ug.user_id, g.id AS group_id, g.group_name
FROM {usergroup} ug
JOIN {group} g ON ug.group_id = g.id
"""

USER_ROLE_SQL = """
SELECT ur.user_id, r.id AS role_id, r.role_name, r.group_id
FROM {userrole} ur
JOIN {role} r ON ur.role_id = r.id
"""

USER_DEPARTMENT_SQL = """
SELECT ud.user_id, d.id AS department_id, d.name AS department_name
FROM {user_department} ud
JOIN {department} d ON ud.department_id = d.id
"""

KNOWLEDGE_TYPE_MAP = {
    0: "文档知识库",
    1: "QA知识库",
    2: "个人知识库",
}


def quote_ident(name: str) -> str:
    engine = sync_get_database_connection().engine
    return engine.dialect.identifier_preparer.quote(name)


def lower_keys(mapping: Any) -> dict[str, Any]:
    return {str(key).lower(): value for key, value in mapping.items()}


def stream_query(sql: str, params: dict[str, Any], batch_size: int = 1000) -> Iterable[dict[str, Any]]:
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            result = session.exec(text(sql).execution_options(stream_results=True), params=params)
            for partition in result.mappings().partitions(batch_size):
                for row in partition:
                    yield lower_keys(row)


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            result = session.exec(text(sql), params=params or {})
            return [lower_keys(row) for row in result.mappings()]


class MidKnowledgeFileIncrementJob:
    index_name = "mid_knowledge_file_increment"
    es_mapping = ES_MAPPING
    base_batch_size = 1000

    def __init__(self, es_client: Elasticsearch | None = None):
        self._es_client = es_client or get_statistics_es_connection_sync()

    def ensure_index_exists(self) -> None:
        try:
            if not self._es_client.indices.exists(index=self.index_name):
                self._es_client.indices.create(index=self.index_name, body=self.es_mapping)
        except es_exceptions.RequestError as exc:
            if "resource_already_exists_exception" not in str(exc):
                logger.exception("Failed to create telemetry index {}", self.index_name)
                raise

    def init_index(self, end_time: datetime.datetime | None = None) -> None:
        logger.info("Initializing telemetry index '{}'.", self.index_name)
        if self._es_client.indices.exists(index=self.index_name):
            return

        self._es_client.indices.create(index=self.index_name, body=self.es_mapping)
        end_time = datetime.datetime.combine(datetime.date.today(), datetime.time.min) if end_time is None else end_time
        self._run_incremental_update(end_time=end_time)

    def _sql(self, template: str) -> str:
        return template.format(
            knowledgefile=quote_ident("knowledgefile"),
            qaknowledge=quote_ident("qaknowledge"),
            user=quote_ident("user"),
            knowledge=quote_ident("knowledge"),
            usergroup=quote_ident("usergroup"),
            group=quote_ident("group"),
            userrole=quote_ident("userrole"),
            role=quote_ident("role"),
            user_department=quote_ident("user_department"),
            department=quote_ident("department"),
        )

    def _load_user_group_map(self) -> dict[int, list[dict[str, Any]]]:
        result: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in fetch_all(self._sql(USER_GROUP_SQL)):
            result[row["user_id"]].append(
                {
                    "user_group_id": row["group_id"],
                    "user_group_name": row["group_name"],
                }
            )
        return result

    def _load_user_role_map(self) -> dict[int, list[dict[str, Any]]]:
        result: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in fetch_all(self._sql(USER_ROLE_SQL)):
            result[row["user_id"]].append(
                {
                    "role_id": row["role_id"],
                    "role_name": row["role_name"],
                    "group_id": row["group_id"],
                }
            )
        return result

    def _load_user_department_map(self) -> dict[int, list[dict[str, Any]]]:
        result: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in fetch_all(self._sql(USER_DEPARTMENT_SQL)):
            result[row["user_id"]].append(
                {
                    "department_id": row["department_id"],
                    "department_name": row["department_name"],
                }
            )
        return result

    @staticmethod
    def _first_question(raw: Any) -> str:
        if raw is None:
            return "未命名"
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return raw or "未命名"
        if isinstance(raw, list):
            return str(raw[0]) if raw else "未命名"
        return str(raw)

    @staticmethod
    def _normalize_upload_time(raw: Any) -> datetime.datetime:
        if isinstance(raw, datetime.datetime):
            return raw
        if isinstance(raw, datetime.date):
            return datetime.datetime.combine(raw, datetime.time.min)
        return datetime.datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S")

    def _transform_row_to_action(
        self,
        row: dict[str, Any],
        group_map: dict[int, list[dict[str, Any]]],
        role_map: dict[int, list[dict[str, Any]]],
        department_map: dict[int, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        file_type = row["file_type"]
        if file_type == "qa":
            file_name = self._first_question(row.get("questions"))
            file_size = 0
        else:
            file_name = row.get("file_name") or "未命名"
            file_size = row.get("file_size") or 0

        upload_time = self._normalize_upload_time(row["upload_time"])
        user_id = row["user_id"]
        doc = {
            "timestamp": int(upload_time.timestamp()),
            "file_id": row["file_id"],
            "file_name": file_name,
            "file_size": file_size,
            "file_type": file_type,
            "user_id": str(user_id) if user_id is not None else None,
            "user_name": row.get("user_name"),
            "knowledge_base_id": row["knowledge_base_id"],
            "knowledge_base_type": KNOWLEDGE_TYPE_MAP.get(row.get("knowledge_type"), "未知类型"),
            "user_group_infos": group_map.get(user_id, []),
            "user_role_infos": role_map.get(user_id, []),
            "user_department_infos": department_map.get(user_id, []),
        }
        return {
            "_index": self.index_name,
            "_id": f"{file_type}-{row['file_id']}",
            "_source": doc,
        }

    def _actions_generator(
        self,
        sql_params: dict[str, datetime.datetime],
        group_map: dict[int, list[dict[str, Any]]],
        role_map: dict[int, list[dict[str, Any]]],
        department_map: dict[int, list[dict[str, Any]]],
    ) -> Iterable[dict[str, Any]]:
        for template in (FILE_SQL, QA_SQL):
            for row in stream_query(self._sql(template), sql_params, batch_size=self.base_batch_size):
                yield self._transform_row_to_action(row, group_map, role_map, department_map)

    def _run_incremental_update(
        self,
        start_time: datetime.datetime | None = None,
        end_time: datetime.datetime | None = None,
    ) -> None:
        self.ensure_index_exists()
        start_time = start_time or datetime.datetime(1970, 1, 1)
        end_time = end_time or datetime.datetime.now()
        logger.info(
            "Starting telemetry index '{}' update from {} to {}.",
            self.index_name,
            start_time.isoformat(),
            end_time.isoformat(),
        )

        group_map = self._load_user_group_map()
        role_map = self._load_user_role_map()
        department_map = self._load_user_department_map()
        success, errors = helpers.bulk(
            self._es_client,
            self._actions_generator(
                {"start_time": start_time, "end_time": end_time},
                group_map,
                role_map,
                department_map,
            ),
            chunk_size=self.base_batch_size,
            raise_on_error=False,
        )
        logger.info("Telemetry index '{}' updated. indexed={}", self.index_name, success)
        if errors:
            logger.error("Telemetry index '{}' bulk errors. first_error={}", self.index_name, errors[0])
            raise RuntimeError(f"Failed to bulk index {len(errors)} documents into {self.index_name}.")

    def add_one_day_data(self) -> None:
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        start_time = datetime.datetime.combine(yesterday, datetime.time.min)
        end_time = datetime.datetime.combine(today, datetime.time.min)
        self._run_incremental_update(start_time=start_time, end_time=end_time)
