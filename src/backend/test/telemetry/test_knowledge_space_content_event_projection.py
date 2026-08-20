import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.schemas.telemetry.base_telemetry_schema import BaseTelemetryEvent, UserContext
from bisheng.common.schemas.telemetry.event_data_schema import PortalDocumentReadEventData
from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
    ContentStatEventEnvelope,
    KnowledgeSpaceContentStat,
)
from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import (
    CONTENT_DIMENSION_FIELDS,
)


class _FakeElasticsearch:
    def __init__(self):
        self.update_calls = []
        self.indices = SimpleNamespace(
            exists=lambda **_kwargs: True,
            put_mapping=lambda **_kwargs: {"acknowledged": True},
            put_settings=lambda **_kwargs: {"acknowledged": True},
        )

    def update(self, **kwargs):
        self.update_calls.append(kwargs)


def test_raw_event_serialization_contains_versioned_dimension_snapshot():
    event = BaseTelemetryEvent(
        event_id="event-1",
        event_type=BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ,
        timestamp=1_776_000_000,
        user_context=UserContext(user_id=7, user_name="张三"),
        event_data=PortalDocumentReadEventData(
            source_app="shougang_portal",
            scene="document_preview",
            entry_point="direct",
            file_id=11,
            content_stat_schema_version=2,
            content_stat_local_date="2026-08-20",
            content_stat_daily_id="preview_daily:11:2026-08-20:digest",
            content_stat_snapshot={
                "file_id": 11,
                "uploader_company_name": "首钢",
            },
        ),
    )

    data = event.model_dump()

    assert data["event_data"]["portal_document_read_content_stat_schema_version"] == 2
    assert data["event_data"]["portal_document_read_content_stat_snapshot"] == {
        "file_id": 11,
        "uploader_company_name": "首钢",
    }


def test_daily_projection_uses_monotonic_absolute_count(monkeypatch):
    fake_es = _FakeElasticsearch()
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection_sync",
        lambda: fake_es,
    )
    envelope = ContentStatEventEnvelope(
        event_id="event-1",
        event_type="portal_document_read",
        record_type="preview_daily",
        user_id=7,
        occurred_at=1_776_000_000,
        local_date="2026-08-20",
        daily_id="preview_daily:11:2026-08-20:digest",
        source_app="shougang_portal",
        scene="document_preview",
        entry_point="direct",
        dimensions={
            "space_id": 3,
            "space_level": "public",
            "file_id": 11,
            "file_name": "制度.pdf",
            "file_type": 1,
            "uploader_user_id": 9,
            "uploader_user_name": "上传人",
            "uploader_company_name": "首钢",
        },
    )

    KnowledgeSpaceContentStat().upsert_event_daily_sync(envelope, 3)

    call = fake_es.update_calls[0]
    assert call["id"] == envelope.daily_id
    assert call["upsert"]["preview_count"] == 3
    assert call["upsert"]["record_type"] == "preview_daily"
    assert call["script"]["params"] == {"count": 3}
    assert "< params.count" in call["script"]["source"]


def test_replay_floor_is_persisted_without_expiration(monkeypatch):
    redis_client = SimpleNamespace(set=lambda *args, **kwargs: calls.append((args, kwargs)))
    calls = []
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.knowledge_space_content.get_redis_client_sync",
        lambda: redis_client,
    )

    KnowledgeSpaceContentStat.set_replay_floor_sync(1_776_000_000)

    assert calls == [
        (
            (KnowledgeSpaceContentStat.REPLAY_FLOOR_KEY, 1_776_000_000),
            {"expiration": None},
        )
    ]


async def test_success_event_builds_fresh_versioned_snapshot_before_enqueue(monkeypatch):
    dimensions = dict.fromkeys(CONTENT_DIMENSION_FIELDS)
    dimensions.update(
        {
            "space_id": 3,
            "space_name": "制度库",
            "space_level": "department",
            "space_level_name": "部门库",
            "file_id": 11,
            "file_name": "制度.pdf",
            "file_type": 1,
            "uploader_user_id": 9,
            "uploader_user_name": "上传人",
            "uploader_company_name": "新公司名称",
            "belonging_department_name": "质量部",
        }
    )
    event_record = SimpleNamespace(**dimensions)
    hset = AsyncMock()
    zadd = AsyncMock()
    redis_client = SimpleNamespace(
        acluster_nodes=AsyncMock(),
        async_connection=SimpleNamespace(hset=hset, zadd=zadd),
    )

    async def get_redis():
        return redis_client

    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.telemetry.mid_table",
        SimpleNamespace(
            build_knowledge_space_content_event_record=(lambda file_id: event_record if file_id == 11 else None)
        ),
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.knowledge_space_content.get_redis_client",
        get_redis,
    )
    monkeypatch.setattr(
        KnowledgeSpaceContentStat,
        "_schedule_event_pending_async",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.knowledge_space_content.generate_uuid",
        lambda: "event-1",
    )

    queued = await KnowledgeSpaceContentStat.enqueue_success_event_async(
        file_id=11,
        user_id=7,
        event_type="portal_document_read",
        record_type="preview_daily",
        source_app="shougang_portal",
        scene="document_preview",
        entry_point="direct",
        occurred_at=datetime(
            2026,
            8,
            20,
            9,
            30,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )

    assert queued is True
    payload = ContentStatEventEnvelope.model_validate_json(hset.await_args.args[2])
    assert payload.event_id == "event-1"
    assert payload.local_date == "2026-08-20"
    assert payload.dimensions["uploader_company_name"] == "新公司名称"
    assert "uploader_department_name" not in payload.dimensions
    assert payload.daily_id.startswith("preview_daily:11:2026-08-20:")
    zadd.assert_awaited_once()
