from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
    ContentStatEventEnvelope,
    KnowledgeSpaceContentStat,
)
from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import (
    ORIGINAL_DIMENSION_FIELDS,
    build_daily_document_id,
)
from test.test_knowledge_space_content_telemetry import _import_worker_mid_table, _stub_file_dimension_lookups


@pytest.mark.parametrize("origin_tenant", [1, 2, None])
def test_original_space_after_publish_and_legacy_fallback(monkeypatch, origin_tenant):
    worker = _import_worker_mid_table()
    _stub_file_dimension_lookups(worker, monkeypatch)
    monkeypatch.setattr(worker, "get_user_from_ids_with_cache", lambda _ids, cache: cache)
    departments = {
        index: SimpleNamespace(id=index, name=name, org_level=level, path="/1/2/3/4", status="active")
        for index, name, level in (
            (1, "原始公司", "company"),
            (2, "原始部门", "dept"),
            (3, "原始科室", "office"),
            (4, "原始班组", "squad"),
        )
    }
    monkeypatch.setattr(worker, "_get_dimension_department_map", lambda _departments: departments)
    names = Mock(return_value={10: (origin_tenant, "首次上传库")} if origin_tenant else {})
    worker.KnowledgeStatisticsRepository.space_names = names
    files = [
        SimpleNamespace(
            id=index,
            tenant_id=1,
            user_id=7,
            user_name="上传人",
            original_knowledge_id=origin,
            create_time=None,
            file_name="制度.pdf",
            file_type=1,
        )
        for index, origin in ((11, 10), (12, 10), (13, None))
    ]
    space = SimpleNamespace(id=20, tenant_id=1, name="发布目标库")
    cache = {}
    kwargs = {
        "space_scope_map": {20: SimpleNamespace(level="department")},
        "space_department_map": {20: None},
        "original_space_scope_map": {10: SimpleNamespace(level="department"), 20: SimpleNamespace(level="department")},
        "original_space_department_map": {10: departments[4], 20: None},
        "primary_department_map": {7: None},
        "original_space_name_map": cache,
    }
    records, _ = worker._build_knowledge_space_content_records([(file, space) for file in files], {}, **kwargs)
    assert [row.original_space_name for row in records] == [
        "首次上传库" if origin_tenant == 1 else None,
        "首次上传库" if origin_tenant == 1 else None,
        "发布目标库",
    ]
    assert [getattr(records[0], field) for field in ORIGINAL_DIMENSION_FIELDS[1:]] == [
        "原始公司",
        "原始部门",
        "原始科室",
        "原始班组",
    ]
    assert records[0].space_name == "发布目标库"
    assert records[0].belonging_department_name is None
    worker._build_knowledge_space_content_records([(files[0], space)], {}, **kwargs)
    names.assert_called_once_with([10])


@pytest.mark.parametrize(
    "record_type,metric",
    [
        ("preview_daily", "preview_count"),
        ("download_daily", "download_count"),
        ("favorite_daily", "favorite_count"),
    ],
)
def test_original_dimensions_keep_daily_identity_and_reach_both_write_paths(monkeypatch, record_type, metric):
    from test.telemetry.test_knowledge_space_content_event_projection import _FakeElasticsearch

    dimensions = {
        "space_id": 20,
        "space_name": "目标库",
        "file_id": 11,
        "file_name": "制度.pdf",
        "file_type": 1,
        "uploader_user_id": 7,
        "uploader_user_name": "上传人",
    }
    original = dict(zip(ORIGINAL_DIMENSION_FIELDS, ["首次上传库", "公司", "部门", "科室", "班组"], strict=True))
    old_id = build_daily_document_id(
        record_type=record_type, file_id=11, local_date="2026-10-15", dimensions=dimensions
    )
    # Captured from the deployed field list before this feature.
    assert old_id == f"{record_type}:11:2026-10-15:b5f90aed6c6ed61dc0e883732d545b4f64abc789cb943acd4b2a8019a5eba9ad"
    dimensions.update(original)
    assert (
        build_daily_document_id(
            record_type=record_type,
            file_id=11,
            local_date="2026-10-15",
            dimensions=dimensions,
        )
        == old_id
    )
    envelope = ContentStatEventEnvelope(
        event_id="event",
        event_type="portal_document_read",
        record_type=record_type,
        user_id=7,
        occurred_at=1_790_000_000,
        local_date="2026-10-15",
        daily_id=old_id,
        dimensions=dimensions,
        source_app="shougang_portal",
        scene="test",
        entry_point="direct",
    )
    es = _FakeElasticsearch()
    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: es)
    bulk = Mock(return_value={"items": [{"update": {"_id": old_id, "status": 200}}]})
    es.bulk = bulk
    stat = KnowledgeSpaceContentStat()
    stat.upsert_event_daily_sync(envelope, 3)
    assert stat.upsert_events_daily_sync([(envelope, 3)]) == {}
    single = es.update_calls[0]
    batch = bulk.call_args.kwargs["operations"][1]
    for body in (single, batch):
        assert {field: body["upsert"][field] for field in ORIGINAL_DIMENSION_FIELDS} == original
        assert body["upsert"][metric] == 3
        assert body["script"]["params"] == {"count": 3, "original": original}
    mapping = stat._mappings
    assert mapping["original_space_name"]["type"] == "keyword"
