"""门户问答引用计入被系统化调用知识数的真实库存流转.

只在 BISHENG_E2E=1 时连接配置里的 MySQL、Redis 和看板 Elasticsearch.
不调用大模型。写入只发生在名称以 e2e-qa-citation- 开头的知识库，结束时删除。
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("BISHENG_E2E") != "1",
    reason="只在明确跑 e2e 时连接真实库和统计索引",
)

PREFIX = "e2e-qa-citation-"
DATASET = "mid_knowledge_space_content_stat"


def _engine():
    from sqlalchemy import create_engine

    from bisheng.common.services.config_service import settings

    return create_engine(settings.database_url)


def _project_files() -> None:
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
        KnowledgeSpaceContentStat,
    )
    from bisheng.worker.telemetry.mid_table import (
        sync_pending_knowledge_space_content_stat,
    )

    outcome = sync_pending_knowledge_space_content_stat.apply()
    assert outcome.successful(), outcome.traceback
    KnowledgeSpaceContentStat().ensure_index_exists_sync()
    KnowledgeSpaceContentStat()._es_client_sync.indices.refresh(index=DATASET)


def _write_citation_daily(file_id: int) -> None:
    """共享 Redis 上已有工人会抢走队列。这里用同一套日统计写入，核对真实 ES。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
        ContentStatEventEnvelope,
        KnowledgeSpaceContentStat,
    )
    from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import (
        CONTENT_DIMENSION_FIELDS,
        build_daily_document_id,
    )
    from bisheng.utils import generate_uuid
    from bisheng.worker.telemetry.mid_table import (
        build_knowledge_space_content_event_record,
    )

    record = build_knowledge_space_content_event_record(file_id)
    assert record is not None
    local_time = datetime.now(ZoneInfo("Asia/Shanghai"))
    dimensions = {
        field: getattr(record, field)
        for field in CONTENT_DIMENSION_FIELDS
        if getattr(record, field, None) is not None
    }
    local_date = local_time.date().isoformat()
    envelope = ContentStatEventEnvelope(
        event_id=generate_uuid(),
        event_type="portal_qa_citation",
        record_type="qa_citation_daily",
        user_id=1,
        occurred_at=int(local_time.timestamp()),
        local_date=local_date,
        daily_id=build_daily_document_id(
            record_type="qa_citation_daily",
            file_id=file_id,
            local_date=local_date,
            dimensions=dimensions,
        ),
        source_app="shougang_portal",
        scene="smart_qa",
        entry_point="portal_qa_citation",
        dimensions=dimensions,
    )
    errors = KnowledgeSpaceContentStat().upsert_events_daily_sync([(envelope, 1)])
    assert errors == {}
    KnowledgeSpaceContentStat()._es_client_sync.indices.refresh(index=DATASET)


async def _called(file_id: int) -> int:
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.core.search.elasticsearch.manager import (
        get_statistics_es_connection_sync,
    )
    from bisheng.telemetry_search.domain.services.knowledge_document_reader import (
        DocumentReader,
    )

    set_current_tenant_id(1)

    class SyncES:
        def __init__(self, client):
            self.client = client

        async def search(self, **kwargs):
            return self.client.search(**kwargs)

    reader = DocumentReader(SyncES(get_statistics_es_connection_sync()), DATASET)
    stats = await reader.load([{"term": {"file_id": str(file_id)}}], include_usage=True)
    if not stats.records:
        return 0
    return int(stats.aggregate([], "called_document_count")[0][0])


def _qa_question_count() -> int:
    from bisheng.common.constants.telemetry import REALTIME_QA_QUESTION_FACT_INDEX
    from bisheng.core.search.elasticsearch.manager import (
        get_statistics_es_connection_sync,
    )

    client = get_statistics_es_connection_sync()
    if not client.indices.exists(index=REALTIME_QA_QUESTION_FACT_INDEX):
        return 0
    response = client.count(
        index=REALTIME_QA_QUESTION_FACT_INDEX, query={"match_all": {}}
    )
    return int(response["count"])


def _citation_docs(file_id: int) -> list[dict]:
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
        KnowledgeSpaceContentStat,
    )

    client = KnowledgeSpaceContentStat()._es_client_sync
    response = client.search(
        index=DATASET,
        size=20,
        query={
            "bool": {
                "filter": [
                    {"term": {"file_id": str(file_id)}},
                    {"term": {"record_type": "qa_citation_daily"}},
                ]
            }
        },
    )
    return [hit["_source"] for hit in response["hits"]["hits"]]


def test_portal_qa_citation_counts_non_personal_file_once_and_drops_after_delete():
    asyncio.run(_run_portal_qa_citation_flow())


async def _run_portal_qa_citation_flow():
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
    from scripts.export_portal_category_usage import (
        called_file_ids,
        create_dashboard_es_client,
    )
    from bisheng.common.services.config_service import settings

    name = PREFIX + uuid.uuid4().hex[:12]
    engine = _engine()
    ids: dict[str, int] = {}
    try:
        with engine.begin() as conn:
            department_id = conn.execute(
                text("SELECT id FROM department ORDER BY id LIMIT 1")
            ).scalar()
            assert department_id, "真实库没有部门，无法建非个人知识空间"
            public_space = conn.execute(
                text(
                    "INSERT INTO knowledge "
                    "(user_id, name, type, state, is_released, is_favorite, auth_type, tenant_id) "
                    "VALUES (1, :name, 3, 1, 0, 0, 'private', 1)"
                ),
                {"name": name + "-public"},
            ).lastrowid
            personal_space = conn.execute(
                text(
                    "INSERT INTO knowledge "
                    "(user_id, name, type, state, is_released, is_favorite, auth_type, tenant_id) "
                    "VALUES (1, :name, 3, 1, 0, 0, 'private', 1)"
                ),
                {"name": name + "-personal"},
            ).lastrowid
            conn.execute(
                text(
                    "INSERT INTO knowledge_space_scope "
                    "(tenant_id, space_id, level, owner_type, owner_id, created_by) "
                    "VALUES (1, :space_id, 'department', 'department', :owner_id, 1)"
                ),
                {"space_id": public_space, "owner_id": int(department_id)},
            )
            conn.execute(
                text(
                    "INSERT INTO knowledge_space_scope "
                    "(tenant_id, space_id, level, owner_type, owner_id, created_by) "
                    "VALUES (1, :space_id, 'personal', 'user', 1, 1)"
                ),
                {"space_id": personal_space},
            )
            file_ids = {}
            for label, space_id in (
                ("public", public_space),
                ("personal", personal_space),
            ):
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
                        "name": f"{name}-{label}.txt",
                        "status": KnowledgeFileStatus.SUCCESS.value,
                        "file_type": FileType.FILE.value,
                        "document_id": document_id,
                        "entry_type": KnowledgeFileEntryType.MANAGER.value,
                        "entry_status": KnowledgeFileEntryStatus.ACTIVE.value,
                        "projection_status": KnowledgeFileProjectionStatus.READY.value,
                        "object_name": f"e2e/{name}-{label}.txt",
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
                file_ids[label] = int(file_id)
                ids[f"{label}_document_id"] = int(document_id)
            ids.update(
                public_space=int(public_space),
                personal_space=int(personal_space),
                public_file=file_ids["public"],
                personal_file=file_ids["personal"],
            )

        await KnowledgeSpaceContentStat.enqueue_file_stat_async(
            [ids["public_file"], ids["personal_file"]]
        )
        _project_files()
        assert await _called(ids["public_file"]) == 0

        from bisheng.worker.telemetry.mid_table import (
            build_knowledge_space_content_event_record,
        )

        public_snapshot = build_knowledge_space_content_event_record(ids["public_file"])
        personal_snapshot = build_knowledge_space_content_event_record(
            ids["personal_file"]
        )
        assert public_snapshot is not None
        assert str(public_snapshot.space_level) == "department", (
            public_snapshot.space_level
        )
        assert personal_snapshot is not None
        assert str(personal_snapshot.space_level) == "personal", (
            personal_snapshot.space_level
        )

        qa_before = _qa_question_count()
        queued = await KnowledgeSpaceContentStat.enqueue_portal_qa_citations_async(
            file_ids=[ids["public_file"], ids["personal_file"]],
            user_id=1,
        )
        assert queued == 1
        _write_citation_daily(ids["public_file"])
        assert _qa_question_count() == qa_before
        assert await _called(ids["public_file"]) == 1
        assert await _called(ids["personal_file"]) == 0
        public_docs = _citation_docs(ids["public_file"])
        assert public_docs
        assert all(int(doc["qa_citation_count"]) > 0 for doc in public_docs)
        assert all(doc["space_level"] == "department" for doc in public_docs)
        assert _citation_docs(ids["personal_file"]) == []
        exported = called_file_ids(
            create_dashboard_es_client(settings),
            DATASET,
            [ids["public_file"], ids["personal_file"]],
        )
        assert exported == {ids["public_file"]}

        queued_again = (
            await KnowledgeSpaceContentStat.enqueue_portal_qa_citations_async(
                file_ids=[ids["public_file"]],
                user_id=1,
            )
        )
        assert queued_again == 1
        _write_citation_daily(ids["public_file"])
        assert await _called(ids["public_file"]) == 1

        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE knowledgefile SET deleted_at = CURRENT_TIMESTAMP WHERE id = :file_id"
                ),
                {"file_id": ids["public_file"]},
            )
        await KnowledgeSpaceContentStat.enqueue_file_stat_async([ids["public_file"]])
        _project_files()
        assert await _called(ids["public_file"]) == 0
    finally:
        if not ids:
            return
        from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
            KnowledgeSpaceContentStat,
        )

        client = KnowledgeSpaceContentStat()._es_client_sync
        file_ids = [str(ids["public_file"]), str(ids["personal_file"])]
        if client.indices.exists(index=DATASET):
            client.delete_by_query(
                index=DATASET,
                query={"terms": {"file_id": file_ids}},
                refresh=True,
                conflicts="proceed",
            )
        with engine.begin() as conn:
            for file_id in (ids["public_file"], ids["personal_file"]):
                conn.execute(
                    text(
                        "DELETE FROM knowledge_document_version WHERE knowledge_file_id = :file_id"
                    ),
                    {"file_id": file_id},
                )
                conn.execute(
                    text("DELETE FROM knowledgefile WHERE id = :file_id"),
                    {"file_id": file_id},
                )
            for document_id in (ids["public_document_id"], ids["personal_document_id"]):
                conn.execute(
                    text("DELETE FROM knowledge_document WHERE id = :document_id"),
                    {"document_id": document_id},
                )
            for space_id, space_name in (
                (ids["public_space"], name + "-public"),
                (ids["personal_space"], name + "-personal"),
            ):
                conn.execute(
                    text(
                        "DELETE FROM knowledge_space_scope WHERE space_id = :space_id"
                    ),
                    {"space_id": space_id},
                )
                conn.execute(
                    text("DELETE FROM knowledge WHERE id = :space_id AND name = :name"),
                    {"space_id": space_id, "name": space_name},
                )
