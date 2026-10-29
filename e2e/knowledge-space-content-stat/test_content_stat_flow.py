"""知识空间内容统计的 171 接口流转.

只在 BISHENG_E2E=1 时连接毕昇和 171.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("BISHENG_E2E") != "1",
    reason="只在明确跑 e2e 时连接毕昇和 171",
)

PREFIX = "e2e-content-stat-"
CHINA = ZoneInfo("Asia/Shanghai")
DATASET = "mid_knowledge_space_content_stat"
DASHBOARD_ID = 10


def _engine():
    from sqlalchemy import create_engine

    from bisheng.common.services.config_service import settings

    return create_engine(settings.database_url)


def _admin_token() -> str:
    from sqlalchemy import text

    from bisheng.user.domain.services.auth import AuthJwt

    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT user_name, token_version FROM user WHERE user_id = 1 AND `delete` = 0"
            )
        ).one()
    return AuthJwt().create_access_token(
        {
            "user_id": 1,
            "user_name": row.user_name,
            "tenant_id": 1,
            "token_version": int(row.token_version or 0),
        }
    )


def _client():
    import httpx

    base = os.environ.get("BISHENG_BASE_URL", "http://127.0.0.1:7860").rstrip("/")
    token = _admin_token()
    return httpx.Client(
        base_url=base,
        timeout=120,
        cookies={"access_token_cookie": token},
    )


def _today_filter() -> dict:
    now = datetime.now(CHINA)
    start = datetime(now.year, now.month, now.day, tzinfo=CHINA)
    end = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=CHINA)
    return {
        "type": "custom",
        "mode": "fixed",
        "startDate": int(start.timestamp()),
        "endDate": int(end.timestamp()),
    }


def _query(
    client, metric: str, dimensions: list[dict] | None = None, time_filters=None
) -> dict:
    response = client.post(
        "/api/v1/telemetry/dashboard/component/query",
        json={
            "dashboard_id": DASHBOARD_ID,
            "component_data": {
                "dashboard_id": DASHBOARD_ID,
                "title": PREFIX + "query",
                "type": "custom",
                "dataset_code": DATASET,
                "data_config": {
                    "dimensions": dimensions or [],
                    "metrics": [
                        {"fieldId": metric, "fieldName": metric, "isVirtual": True}
                    ],
                },
                "style_config": {},
            },
            "time_filters": time_filters,
        },
    )
    assert response.status_code == 200, response.text[:500]
    body = response.json()
    assert body["status_code"] == 200, body
    return body["data"]


def _scalar(data: dict) -> float:
    assert data["value"], data
    return float(data["value"][0][0])


def _project_pending() -> None:
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
        KnowledgeSpaceContentStat,
    )
    from bisheng.worker.telemetry.mid_table import (
        sync_pending_knowledge_space_content_stat,
    )

    outcome = sync_pending_knowledge_space_content_stat.apply()
    assert outcome.successful(), outcome.traceback
    stat = KnowledgeSpaceContentStat()
    stat._es_client_sync.indices.refresh(index=stat.INDEX_NAME)


def test_contribution_ratio_by_space_level_sums_to_one():
    """知识库大类的知识贡献占比相加等于 1, 无维度的合计也是 1."""
    with _client() as client:
        grouped = _query(
            client,
            "knowledge_contribution_ratio",
            [{"fieldId": "space_level_name", "fieldName": "知识库大类"}],
        )
        grouped_sum = sum(float(row[0]) for row in grouped["value"])
        total = _scalar(_query(client, "knowledge_contribution_ratio"))
    assert abs(grouped_sum - 1.0) < 1e-6, grouped
    assert abs(total - 1.0) < 1e-6, total


def test_admin_delete_removes_file_from_document_counts():
    """admin 删除带文档入口的新文件后, 文件总数和新增文件数各减 1."""
    import asyncio

    from sqlalchemy import text

    from bisheng.knowledge.domain.models.knowledge_file import (
        FileType,
        KnowledgeFileEntryStatus,
        KnowledgeFileEntryType,
        KnowledgeFileProjectionStatus,
        KnowledgeFileStatus,
    )
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
        KnowledgeSpaceContentStat,
    )

    name = PREFIX + uuid.uuid4().hex[:12]
    engine = _engine()
    ids: dict[str, int] = {}
    try:
        assert KnowledgeSpaceContentStat.queue_status_sync()["pending_count"] == 0
        with engine.begin() as conn:
            space_id = conn.execute(
                text(
                    "INSERT INTO knowledge "
                    "(user_id, name, type, state, is_released, is_favorite, auth_type, tenant_id) "
                    "VALUES (1, :name, 3, 1, 0, 0, 'private', 1)"
                ),
                {"name": name},
            ).lastrowid
            conn.execute(
                text(
                    "INSERT INTO knowledge_space_scope "
                    "(tenant_id, space_id, level, owner_type, owner_id, created_by) "
                    "VALUES (1, :space_id, 'personal', 'user', 1, 1)"
                ),
                {"space_id": space_id},
            )
            document_id = conn.execute(
                text(
                    "INSERT INTO knowledge_document (tenant_id, knowledge_id, content_generation) "
                    "VALUES (1, :space_id, 1)"
                ),
                {"space_id": space_id},
            ).lastrowid
            file_id = conn.execute(
                text(
                    "INSERT INTO knowledgefile ("
                    "user_id, user_name, knowledge_id, file_name, status, file_type, tenant_id, "
                    "reference_document_id, entry_type, entry_status, projection_status, object_name"
                    ") VALUES ("
                    "1, 'admin', :space_id, :name, :status, :file_type, 1, "
                    ":document_id, :entry_type, :entry_status, :projection_status, :object_name)"
                ),
                {
                    "space_id": space_id,
                    "name": name + ".txt",
                    "status": KnowledgeFileStatus.SUCCESS.value,
                    "file_type": FileType.FILE.value,
                    "document_id": document_id,
                    "entry_type": KnowledgeFileEntryType.MANAGER.value,
                    "entry_status": KnowledgeFileEntryStatus.ACTIVE.value,
                    "projection_status": KnowledgeFileProjectionStatus.READY.value,
                    "object_name": f"e2e/{name}.txt",
                },
            ).lastrowid
            conn.execute(
                text(
                    "INSERT INTO knowledge_document_version "
                    "(document_id, knowledge_file_id, version_no, is_primary) "
                    "VALUES (:document_id, :file_id, 1, 1)"
                ),
                {"document_id": document_id, "file_id": file_id},
            )
            conn.execute(
                text(
                    "UPDATE knowledge_document SET primary_version_id = :file_id WHERE id = :document_id"
                ),
                {"file_id": file_id, "document_id": document_id},
            )
        ids.update(space_id=space_id, document_id=document_id, file_id=file_id)

        today = [_today_filter()]
        with _client() as client:
            before_total = _scalar(
                _query(client, "total_file_count", time_filters=today)
            )
            before_new = _scalar(_query(client, "new_file_count", time_filters=today))
            asyncio.run(KnowledgeSpaceContentStat.enqueue_file_stat_async([file_id]))
            _project_pending()
            mid_total = _scalar(_query(client, "total_file_count", time_filters=today))
            mid_new = _scalar(_query(client, "new_file_count", time_filters=today))
            assert mid_total == before_total + 1, (before_total, mid_total)
            assert mid_new == before_new + 1, (before_new, mid_new)

            deleted = client.delete(
                f"/api/v1/knowledge/space/{space_id}/files/{file_id}"
            )
            assert deleted.status_code == 200, deleted.text[:800]
            assert deleted.json()["status_code"] == 200, deleted.json()

        with engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT deleted_at, entry_status FROM knowledgefile WHERE id = :file_id"
                ),
                {"file_id": file_id},
            ).one()
            recycle_id = conn.execute(
                text("SELECT id FROM knowledge_recycle_item WHERE file_id = :file_id"),
                {"file_id": file_id},
            ).scalar()
        assert stored.deleted_at is not None
        assert recycle_id is not None

        _project_pending()
        with _client() as client:
            after_total = _scalar(
                _query(client, "total_file_count", time_filters=today)
            )
            after_new = _scalar(_query(client, "new_file_count", time_filters=today))
        assert after_total == before_total
        assert after_new == before_new
        with engine.connect() as conn:
            still_deleted = conn.execute(
                text("SELECT deleted_at FROM knowledgefile WHERE id = :file_id"),
                {"file_id": file_id},
            ).scalar()
        assert still_deleted is not None
    finally:
        if not ids:
            return
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM knowledge_recycle_item WHERE file_id = :file_id"),
                {"file_id": ids["file_id"]},
            )
            conn.execute(
                text(
                    "DELETE FROM knowledge_document_version WHERE knowledge_file_id = :file_id"
                ),
                {"file_id": ids["file_id"]},
            )
            conn.execute(
                text("DELETE FROM knowledgefile WHERE id = :file_id"),
                {"file_id": ids["file_id"]},
            )
            conn.execute(
                text("DELETE FROM knowledge_document WHERE id = :document_id"),
                {"document_id": ids["document_id"]},
            )
            conn.execute(
                text("DELETE FROM knowledge_space_scope WHERE space_id = :space_id"),
                {"space_id": ids["space_id"]},
            )
            conn.execute(
                text("DELETE FROM knowledge WHERE id = :space_id AND name = :name"),
                {"space_id": ids["space_id"], "name": name},
            )
        asyncio.run(KnowledgeSpaceContentStat.enqueue_file_stat_async([ids["file_id"]]))
        _project_pending()
