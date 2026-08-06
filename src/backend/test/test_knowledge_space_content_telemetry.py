import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _FakeAsyncIndexClient:
    def __init__(self):
        self.get_calls = []
        self.update_calls = []
        self.indices = SimpleNamespace(
            exists=AsyncMock(return_value=True),
            put_mapping=AsyncMock(return_value={"acknowledged": True}),
            put_settings=AsyncMock(return_value={"acknowledged": True}),
        )

    async def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return {
            "_source": {
                "record_type": "file",
                "space_id": 3,
                "space_name": "知识空间",
                "space_level": "department",
                "space_level_name": "部门库",
                "file_id": 11,
                "file_name": "方案.pdf",
                "file_type": 1,
                "uploader_user_id": 7,
                "uploader_user_name": "上传人",
                "uploader_department_infos": [],
            }
        }

    async def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return {"result": "updated"}


class _FakeSyncIndexClient:
    def __init__(self):
        self.deleted_queries = []
        self.refreshed_indices = []
        self.put_mappings = []
        self.put_settings_calls = []
        self.indices = SimpleNamespace(
            exists=lambda **kwargs: True,
            refresh=self.refresh_index,
            put_mapping=self.put_mapping,
            put_settings=self.put_settings,
        )

    def put_mapping(self, **kwargs):
        self.put_mappings.append(kwargs)
        return {"acknowledged": True}

    def refresh_index(self, **kwargs):
        self.refreshed_indices.append(kwargs)
        return {"_shards": {"successful": 1}}

    def put_settings(self, **kwargs):
        self.put_settings_calls.append(kwargs)
        return {"acknowledged": True}

    def delete_by_query(self, **kwargs):
        self.deleted_queries.append(kwargs)
        return {"deleted": 3}


class _FakeRedisSetClient:
    def __init__(self):
        self.sets = {}
        self.nx_keys = set()
        self.deleted_keys = []
        self.connection = self

    def cluster_nodes(self, _key):
        return None

    def sadd(self, key, *values):
        target = self.sets.setdefault(key, set())
        before = len(target)
        target.update(str(value) for value in values)
        return len(target) - before

    def spop(self, key, count=None):
        target = self.sets.setdefault(key, set())
        if count is None:
            if not target:
                return None
            value = next(iter(target))
            target.remove(value)
            return value.encode()
        popped = set()
        for value in list(target)[:count]:
            target.remove(value)
            popped.add(value.encode())
        return popped

    def srandmember(self, key, count=None):
        target = self.sets.setdefault(key, set())
        if count is None:
            if not target:
                return None
            return next(iter(target)).encode()
        return {value.encode() for value in list(target)[:count]}

    def srem(self, key, *values):
        target = self.sets.setdefault(key, set())
        removed = 0
        for value in values:
            if isinstance(value, bytes):
                value = value.decode()
            value = str(value)
            if value in target:
                target.remove(value)
                removed += 1
        return removed

    def scard(self, key):
        return len(self.sets.get(key, set()))

    def setNx(self, key, _value, expiration=3600):
        if key in self.nx_keys:
            return False
        self.nx_keys.add(key)
        return True

    def delete(self, key):
        self.deleted_keys.append(key)
        self.nx_keys.discard(key)
        self.sets.pop(key, None)
        return 1


class _FakeCeleryTask:
    def __init__(self):
        self.apply_async_calls = []

    def apply_async(self, **kwargs):
        self.apply_async_calls.append(kwargs)


_MISSING = object()


def _import_worker_mid_table():
    class _DummyTask:
        def __init__(self, fn):
            self.run = fn

        def __call__(self, *args, **kwargs):
            return self.run(*args, **kwargs)

        def apply_async(self, **_kwargs):
            return None

    class _DummyCelery:
        @staticmethod
        def task(*_args, **_kwargs):
            return lambda fn: _DummyTask(fn)

    stubbed_modules = {
        "bisheng.worker.main": SimpleNamespace(bisheng_celery=_DummyCelery()),
        "bisheng.api.services.workflow": SimpleNamespace(WorkFlowService=SimpleNamespace()),
        "bisheng.knowledge.domain.services.knowledge_service": SimpleNamespace(KnowledgeService=SimpleNamespace()),
    }
    previous_modules = {name: sys.modules.get(name, _MISSING) for name in stubbed_modules}
    try:
        sys.modules.update(stubbed_modules)
        module_path = Path(__file__).parents[1] / "bisheng" / "worker" / "telemetry" / "mid_table.py"
        spec = importlib.util.spec_from_file_location("test_pending_mid_table_under_test", module_path)
        worker_module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(worker_module)
        return worker_module
    finally:
        for name, previous in previous_modules.items():
            if previous is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _stub_file_dimension_lookups(worker_module, monkeypatch):
    monkeypatch.setattr(
        worker_module.KnowledgeSpaceScopeDao,
        "get_map_by_space_ids",
        lambda _space_ids: {},
    )
    monkeypatch.setattr(
        worker_module,
        "_get_knowledge_space_department_map",
        lambda space_ids, _scope_map: dict.fromkeys(space_ids),
    )
    monkeypatch.setattr(
        worker_module.UserDepartmentDao,
        "get_primary_department_map_by_user_ids",
        lambda _user_ids: {},
    )
    monkeypatch.setattr(
        worker_module.FileClassificationLabelService,
        "get_label_lookup_for_tenant",
        lambda _tenant_id: ({}, {}),
    )


@pytest.mark.asyncio
async def test_knowledge_space_content_log_preview_success_upserts_daily_counter(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    fake_client = _FakeAsyncIndexClient()

    async def fake_get_es_connection():
        return fake_client

    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection", fake_get_es_connection)

    file_record = SimpleNamespace(
        id=11,
        user_id=7,
        user_name="上传人",
        file_name="方案.pdf",
        file_type=1,
    )
    space = SimpleNamespace(id=3, name="知识空间")

    await module.KnowledgeSpaceContentStat.log_preview_success(
        file_record=file_record,
        space=space,
        viewer_user_id=9,
        viewer_user_name="查看人",
        occurred_at=datetime(2026, 8, 3, 15, 30, tzinfo=timezone.utc),
    )

    assert fake_client.get_calls == [{"index": "mid_knowledge_space_content_stat", "id": "11"}]
    call = fake_client.update_calls[0]
    assert call["index"] == "mid_knowledge_space_content_stat"
    assert call["id"] == "preview_11_2026-08-03"
    assert call["retry_on_conflict"] == 5
    assert call["script"]["source"] == "ctx._source.preview_count += params.increment"
    assert call["upsert"]["record_type"] == "preview_daily"
    assert call["upsert"]["local_date"] == "2026-08-03"
    assert call["upsert"]["preview_count"] == 1
    assert call["upsert"]["file_name"] == "方案.pdf"
    assert "refresh" not in call
    assert not {
        "tenant_id",
        "event_id",
        "viewer_user_id",
        "viewer_user_name",
        "action_result",
        "user_id",
        "user_name",
    }.intersection(call["upsert"])


@pytest.mark.asyncio
async def test_favorite_space_preview_is_not_projected(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    fake_client = _FakeAsyncIndexClient()

    async def fake_get_es_connection():
        return fake_client

    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection", fake_get_es_connection)

    await module.KnowledgeSpaceContentStat.log_preview_success(
        file_record=SimpleNamespace(id=11),
        space=SimpleNamespace(id=3, name="我的收藏", is_favorite=True),
        viewer_user_id=9,
        viewer_user_name="查看人",
    )

    assert fake_client.get_calls == []
    assert fake_client.update_calls == []


@pytest.mark.asyncio
async def test_knowledge_space_content_log_preview_success_does_not_retry_es_failure(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    class _FailingAsyncIndexClient(_FakeAsyncIndexClient):
        async def update(self, **kwargs):
            raise RuntimeError("es unavailable")

    async def fake_get_es_connection():
        return _FailingAsyncIndexClient()

    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection", fake_get_es_connection)

    file_record = SimpleNamespace(
        id=11,
        user_id=7,
        user_name="上传人",
        file_name="方案.pdf",
        file_type=1,
    )
    space = SimpleNamespace(id=3, name="知识空间")

    await module.KnowledgeSpaceContentStat.log_preview_success(
        file_record=file_record,
        space=space,
        viewer_user_id=9,
        viewer_user_name="查看人",
    )

    assert not hasattr(module.KnowledgeSpaceContentStat, "enqueue_preview_record_async")
    assert not hasattr(module.KnowledgeSpaceContentStat, "PREVIEW_PENDING_KEY")


def test_knowledge_space_content_build_file_record_contains_realtime_dimensions():
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    file_record = SimpleNamespace(
        id=11,
        tenant_id=7,
        user_id=9,
        user_name="上传人",
        create_time=None,
        file_name="制度.pdf",
        file_type=1,
        split_rule='{"file_category_code":"POL","business_domain_code":"QM"}',
        file_subcategory_code="POL-01",
        file_encoding=None,
    )
    space = SimpleNamespace(id=3, tenant_id=7, name="质量制度库")
    uploader = SimpleNamespace(user_name="上传人", departments=[], groups=[], roles=[])
    space_department = SimpleNamespace(id=31, name="质量管理处")
    primary_department = SimpleNamespace(id=21, name="质量部")

    record = module.KnowledgeSpaceContentStat.build_file_record(
        file_record=file_record,
        space=space,
        uploader=uploader,
        space_level="department",
        space_department=space_department,
        primary_department=primary_department,
        file_category_labels={"POL": "政策制度"},
        file_subcategory_labels={"POL-01": "管理制度"},
    )

    dumped = record.model_dump(exclude={"es_id"})
    assert record.es_id == "11"
    assert "tenant_id" not in dumped
    assert not {
        "user_id",
        "user_name",
        "user_group_infos",
        "user_role_infos",
        "user_department_infos",
    }.intersection(dumped)
    assert record.space_level == "department"
    assert record.space_level_name == "部门库"
    assert record.file_category_code == "POL"
    assert record.file_category_name == "政策制度"
    assert record.file_subcategory_code == "POL-01"
    assert record.file_subcategory_name == "管理制度"
    assert record.business_domain_code == "QM"
    assert record.space_department_id == 31
    assert record.space_department_name == "质量管理处"
    assert record.primary_department_id == 21
    assert record.primary_department_name == "质量部"
    assert record.projection_updated_at


def test_knowledge_space_content_mapping_excludes_tenant_and_common_user_context():
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
        KnowledgeSpaceContentStat,
    )

    stat = KnowledgeSpaceContentStat(ensure_sync_index=False)
    assert stat._include_common_mappings is False
    assert not {
        "tenant_id",
        "user_id",
        "user_name",
        "user_group_infos",
        "user_role_infos",
        "user_department_infos",
    }.intersection(stat._mappings)
    assert stat._mappings["timestamp"] == {
        "type": "date",
        "format": "strict_date_optional_time||epoch_second",
    }
    assert stat._mappings["download_count"] == {"type": "long"}


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("department", True),
        ("team_ks", True),
        ("personal", False),
        ("team", False),
        ("public", False),
    ],
)
def test_only_department_and_clinic_spaces_are_department_bound(level, expected):
    worker_module = _import_worker_mid_table()

    assert worker_module._is_department_bound_space_scope(SimpleNamespace(level=level)) is expected


@pytest.mark.parametrize(
    ("is_favorite", "expected"),
    [(False, True), (True, False)],
)
def test_content_projection_excludes_favorite_spaces(is_favorite, expected):
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus

    worker_module = _import_worker_mid_table()
    file_record = SimpleNamespace(
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        deleted_at=None,
    )
    space = SimpleNamespace(type=3, is_favorite=is_favorite)

    assert worker_module._is_file_content_stat_visible(file_record, space) is expected


def test_unbound_space_content_has_no_owning_department():
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    record = module.KnowledgeSpaceContentStat.build_file_record(
        file_record=SimpleNamespace(
            id=12,
            tenant_id=7,
            user_id=9,
            user_name="上传人",
            create_time=None,
            file_name="公共制度.pdf",
            file_type=1,
            split_rule=None,
            file_subcategory_code=None,
            file_encoding=None,
        ),
        space=SimpleNamespace(id=4, tenant_id=7, name="公共知识库"),
        uploader=SimpleNamespace(
            user_name="上传人",
            departments=[],
            groups=[],
            roles=[],
        ),
        space_level="public",
        space_department=None,
    )

    assert record.space_department_id is None
    assert record.space_department_name is None


def test_knowledge_space_content_delete_stale_file_records_uses_sync_run_id(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    fake_client = _FakeSyncIndexClient()

    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: fake_client)

    deleted = module.KnowledgeSpaceContentStat().delete_stale_file_records_sync("run-1")

    assert deleted == 3
    assert fake_client.refreshed_indices == [{"index": "mid_knowledge_space_content_stat"}]
    call = fake_client.deleted_queries[0]
    assert call["index"] == "mid_knowledge_space_content_stat"
    assert call["refresh"] is True
    assert call["conflicts"] == "proceed"
    assert call["body"]["query"]["bool"]["filter"] == [{"term": {"record_type": "file"}}]
    assert call["body"]["query"]["bool"]["must_not"] == [{"term": {"sync_run_id": "run-1"}}]


def test_knowledge_space_content_builds_idempotent_download_daily_record():
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    file_record = module.KnowledgeSpaceContentStat.build_file_record(
        file_record=SimpleNamespace(
            id=11,
            tenant_id=7,
            user_id=9,
            user_name="上传人",
            create_time=None,
            file_name="制度.pdf",
            file_type=1,
            split_rule=None,
            file_subcategory_code=None,
            file_encoding=None,
        ),
        space=SimpleNamespace(id=3, tenant_id=7, name="制度库"),
        space_level="department",
        space_department=SimpleNamespace(id=31, name="质量管理处"),
    )

    first = module.KnowledgeSpaceContentStat.build_download_daily_record(
        file_record=file_record,
        local_date="2026-08-03",
        download_count=2,
        sync_run_id="run-1",
    )
    second = module.KnowledgeSpaceContentStat.build_download_daily_record(
        file_record=file_record,
        local_date="2026-08-03",
        download_count=5,
        sync_run_id="run-2",
    )

    assert first.es_id == second.es_id == "download_11_2026-08-03"
    assert first.record_type == "download_daily"
    assert first.download_count == 2
    assert first.timestamp == 1785686400
    assert first.space_department_name == "质量管理处"
    assert second.download_count == 5


def test_delete_stale_download_daily_records_uses_sync_run_id(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    fake_client = _FakeSyncIndexClient()
    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: fake_client)

    deleted = module.KnowledgeSpaceContentStat().delete_stale_download_daily_records_sync("run-1")

    assert deleted == 3
    call = fake_client.deleted_queries[0]
    assert call["refresh"] is True
    assert call["conflicts"] == "proceed"
    assert call["body"]["query"]["bool"] == {
        "filter": [{"term": {"record_type": "download_daily"}}],
        "must_not": [{"term": {"sync_run_id": "run-1"}}],
    }


def test_portal_download_aggregation_query_filters_source_and_uses_after_key(monkeypatch):
    worker_module = _import_worker_mid_table()
    search_calls = []

    class _FakeStatisticsEs:
        def search(self, **kwargs):
            search_calls.append(kwargs)
            return {
                "aggregations": {
                    "download_daily": {
                        "buckets": [
                            {
                                "key": {"local_date": "2026-08-03", "file_id": 11},
                                "doc_count": 2,
                            }
                        ],
                        "after_key": {"local_date": "2026-08-03", "file_id": 11},
                    }
                }
            }

    monkeypatch.setattr(worker_module, "get_statistics_es_connection_sync", lambda: _FakeStatisticsEs())
    worker_module.telemetry_service.index_name = "base_telemetry_events"

    buckets, after_key = worker_module._get_portal_download_aggregation_page(
        after_key={"local_date": "2026-08-02", "file_id": 9},
        page_size=200,
    )

    assert buckets[0]["download_count"] == 2
    assert buckets[0]["file_id"] == 11
    assert buckets[0]["local_date"] == "2026-08-03"
    assert after_key == {"local_date": "2026-08-03", "file_id": 11}
    call = search_calls[0]
    assert call["index"] == "base_telemetry_events"
    body = call["body"]
    assert body["query"]["bool"]["filter"] == [
        {"term": {"event_type": "portal_document_download"}},
        {
            "term": {
                "event_data.portal_document_download_source_app.keyword": "shougang_portal"
            }
        },
        {"term": {"event_data.portal_document_download_status.keyword": "success"}},
    ]
    composite = body["aggs"]["download_daily"]["composite"]
    assert composite["size"] == 200
    assert composite["after"] == {"local_date": "2026-08-02", "file_id": 9}
    assert composite["sources"][0]["local_date"]["date_histogram"]["time_zone"] == "+08:00"


def test_portal_download_aggregation_treats_missing_event_index_as_empty(monkeypatch):
    worker_module = _import_worker_mid_table()

    class _MissingIndexError(Exception):
        pass

    class _FakeStatisticsEs:
        def search(self, **_kwargs):
            raise _MissingIndexError

    monkeypatch.setattr(worker_module.es_exceptions, "NotFoundError", _MissingIndexError)
    monkeypatch.setattr(worker_module, "get_statistics_es_connection_sync", lambda: _FakeStatisticsEs())

    assert worker_module._get_portal_download_aggregation_page() == ([], None)


def test_rebuild_download_projection_skips_missing_files_and_cleans_after_write(monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus

    worker_module = _import_worker_mid_table()
    stat_cls = worker_module.KnowledgeSpaceContentStat
    _stub_file_dimension_lookups(worker_module, monkeypatch)
    file_record = SimpleNamespace(
        id=11,
        tenant_id=7,
        user_id=9,
        user_name="上传人",
        create_time=None,
        knowledge_id=3,
        file_name="制度.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        deleted_at=None,
        split_rule=None,
        file_subcategory_code=None,
        file_encoding=None,
    )
    space = SimpleNamespace(id=3, tenant_id=7, name="制度库", type=3, is_favorite=False)
    pages = iter(
        [
            (
                [
                    {"file_id": 11, "local_date": "2026-08-03", "download_count": 2},
                    {"file_id": 404, "local_date": "2026-08-03", "download_count": 7},
                ],
                {"local_date": "2026-08-03", "file_id": 404},
            ),
            ([], None),
        ]
    )
    inserted = []
    cleaned = []

    monkeypatch.setattr(worker_module, "_get_portal_download_aggregation_page", lambda **_kwargs: next(pages))
    monkeypatch.setattr(
        worker_module,
        "_get_knowledge_space_content_rows_by_file_ids",
        lambda _file_ids: [(file_record, space)],
    )
    monkeypatch.setattr(worker_module, "get_user_from_ids_with_cache", lambda _ids, user_map: user_map)
    monkeypatch.setattr(stat_cls, "renew_lock_sync", lambda _owner: True)
    monkeypatch.setattr(stat_cls, "insert_records_sync", lambda self, records: inserted.extend(records))
    monkeypatch.setattr(
        stat_cls,
        "delete_stale_download_daily_records_sync",
        lambda self, sync_run_id: cleaned.append(sync_run_id) or 4,
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection_sync",
        lambda: _FakeSyncIndexClient(),
    )

    result = worker_module.rebuild_knowledge_space_content_download_projection(
        owner_token="owner-a",
        mid_table=stat_cls(),
        sync_run_id="run-1",
    )

    assert [record.es_id for record in inserted] == ["download_11_2026-08-03"]
    assert inserted[0].download_count == 2
    assert cleaned == ["run-1"]
    assert result == {"synced_download_daily": 1, "deleted_stale_download_daily": 4}


def test_rebuild_download_projection_does_not_cleanup_after_failed_write(monkeypatch):
    worker_module = _import_worker_mid_table()
    stat_cls = worker_module.KnowledgeSpaceContentStat
    cleaned = []

    monkeypatch.setattr(
        worker_module,
        "_get_portal_download_aggregation_page",
        lambda **_kwargs: ([{"file_id": 11, "local_date": "2026-08-03", "download_count": 1}], None),
    )
    monkeypatch.setattr(
        worker_module,
        "_get_knowledge_space_content_rows_by_file_ids",
        lambda _file_ids: [
            (
                SimpleNamespace(id=11, file_type=1, status=2, deleted_at=None),
                SimpleNamespace(id=3, type=3, is_favorite=False),
            )
        ],
    )
    monkeypatch.setattr(
        worker_module,
        "_build_knowledge_space_content_records",
        lambda *_args, **_kwargs: ([SimpleNamespace(file_id=11)], {}),
    )
    monkeypatch.setattr(stat_cls, "renew_lock_sync", lambda _owner: True)
    monkeypatch.setattr(
        stat_cls,
        "build_download_daily_record",
        lambda **_kwargs: SimpleNamespace(es_id="download_11_2026-08-03"),
    )
    monkeypatch.setattr(
        stat_cls,
        "insert_records_sync",
        lambda self, _records: (_ for _ in ()).throw(RuntimeError("es down")),
    )
    monkeypatch.setattr(
        stat_cls,
        "delete_stale_download_daily_records_sync",
        lambda self, sync_run_id: cleaned.append(sync_run_id),
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection_sync",
        lambda: _FakeSyncIndexClient(),
    )

    with pytest.raises(RuntimeError, match="es down"):
        worker_module.rebuild_knowledge_space_content_download_projection(
            owner_token="owner-a",
            mid_table=stat_cls(),
            sync_run_id="run-1",
        )

    assert cleaned == []


def test_delete_space_records_removes_file_and_preview_rows(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    fake_client = _FakeSyncIndexClient()
    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: fake_client)

    deleted = module.KnowledgeSpaceContentStat().delete_space_records_sync([3, 4])

    assert deleted == 3
    query = fake_client.deleted_queries[0]["body"]["query"]
    assert query == {"terms": {"space_id": [3, 4]}}


def test_sync_pending_knowledge_space_content_stat_reloads_current_file_state(monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus

    worker_module = _import_worker_mid_table()
    stat_cls = worker_module.KnowledgeSpaceContentStat
    _stub_file_dimension_lookups(worker_module, monkeypatch)
    success_file = SimpleNamespace(
        id=21,
        user_id=7,
        user_name="上传人",
        create_time=None,
        knowledge_id=3,
        file_name="成功.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        deleted_at=None,
    )
    waiting_file = SimpleNamespace(
        id=22,
        user_id=7,
        user_name="上传人",
        create_time=None,
        knowledge_id=3,
        file_name="等待.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.WAITING.value,
        deleted_at=None,
    )
    space = SimpleNamespace(id=3, name="空间", type=3)
    claimed = [
        SimpleNamespace(member="file:21", kind="file", resource_id=21, enqueued_at_ms=1_000),
        SimpleNamespace(member="file:22", kind="file", resource_id=22, enqueued_at_ms=1_000),
        SimpleNamespace(member="file:404", kind="file", resource_id=404, enqueued_at_ms=1_000),
    ]
    upserted = []
    deleted = []
    acked = []

    monkeypatch.setattr(stat_cls, "clear_scheduled_sync", lambda: None)
    monkeypatch.setattr(stat_cls, "acquire_lock_sync", lambda: "owner-a")
    monkeypatch.setattr(stat_cls, "renew_lock_sync", lambda _owner: True)
    monkeypatch.setattr(stat_cls, "renew_claims_sync", lambda _owner, _members: True)
    monkeypatch.setattr(stat_cls, "release_lock_sync", lambda _owner: True)
    monkeypatch.setattr(stat_cls, "claim_pending_sync", lambda _owner, _size: claimed)
    monkeypatch.setattr(
        stat_cls,
        "ack_claimed_sync",
        lambda _owner, members: acked.extend(members) or True,
    )
    monkeypatch.setattr(stat_cls, "has_pending_sync", lambda: False)
    monkeypatch.setattr(
        stat_cls,
        "queue_status_sync",
        lambda: {"pending_count": 0, "processing_count": 0, "oldest_pending_age_ms": 0},
    )
    monkeypatch.setattr(stat_cls, "insert_records_sync", lambda self, records: upserted.extend(records))
    monkeypatch.setattr(
        stat_cls,
        "delete_file_records_sync",
        lambda self, file_ids: deleted.extend(file_ids),
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection_sync",
        lambda: _FakeSyncIndexClient(),
    )
    monkeypatch.setattr(
        worker_module,
        "_get_knowledge_space_content_rows_by_file_ids",
        lambda _file_ids: [(success_file, space), (waiting_file, space)],
    )
    monkeypatch.setattr(worker_module, "get_user_from_ids_with_cache", lambda _ids, user_map: user_map)

    worker_module.sync_pending_knowledge_space_content_stat.run()

    assert [record.es_id for record in upserted] == ["21"]
    assert deleted == [22, 404]
    assert acked == ["file:21", "file:22", "file:404"]


def test_sync_pending_knowledge_space_content_stat_does_not_ack_failed_write(monkeypatch):
    worker_module = _import_worker_mid_table()
    stat_cls = worker_module.KnowledgeSpaceContentStat
    _stub_file_dimension_lookups(worker_module, monkeypatch)
    file_record = SimpleNamespace(
        id=21,
        user_id=7,
        user_name="上传人",
        create_time=None,
        knowledge_id=3,
        file_name="成功.pdf",
        file_type=1,
        status=2,
        deleted_at=None,
    )
    space = SimpleNamespace(id=3, name="空间", type=3)
    claimed = [SimpleNamespace(member="file:21", kind="file", resource_id=21, enqueued_at_ms=1_000)]
    acked = []

    monkeypatch.setattr(stat_cls, "clear_scheduled_sync", lambda: None)
    monkeypatch.setattr(stat_cls, "acquire_lock_sync", lambda: "owner-a")
    monkeypatch.setattr(stat_cls, "renew_lock_sync", lambda _owner: True)
    monkeypatch.setattr(stat_cls, "renew_claims_sync", lambda _owner, _members: True)
    monkeypatch.setattr(stat_cls, "release_lock_sync", lambda _owner: True)
    monkeypatch.setattr(stat_cls, "claim_pending_sync", lambda _owner, _size: claimed)
    monkeypatch.setattr(
        stat_cls,
        "ack_claimed_sync",
        lambda _owner, members: acked.extend(members) or True,
    )
    monkeypatch.setattr(stat_cls, "has_pending_sync", lambda: False)
    monkeypatch.setattr(
        stat_cls,
        "insert_records_sync",
        lambda self, records: (_ for _ in ()).throw(RuntimeError("es down")),
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection_sync",
        lambda: _FakeSyncIndexClient(),
    )
    monkeypatch.setattr(
        worker_module,
        "_get_knowledge_space_content_rows_by_file_ids",
        lambda _file_ids: [(file_record, space)],
    )
    monkeypatch.setattr(worker_module, "get_user_from_ids_with_cache", lambda _ids, user_map: user_map)

    with pytest.raises(RuntimeError, match="es down"):
        worker_module.sync_pending_knowledge_space_content_stat.run()

    assert acked == []


def test_add_embedding_enqueues_file_stat_after_success(monkeypatch):
    from bisheng.api.services import knowledge_imp
    from bisheng.api.services import workstation as workstation_api
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus

    space = SimpleNamespace(id=3, type=KnowledgeTypeEnum.SPACE.value)
    file_record = SimpleNamespace(
        id=41,
        user_id=7,
        updater_id=7,
        knowledge_id=3,
        file_name="成功.pdf",
        file_type=FileType.FILE.value,
        object_name="source/成功.pdf",
        parse_type=None,
        status=KnowledgeFileStatus.PROCESSING.value,
        remark="",
        simhash=None,
        similar_status=0,
    )
    updated_statuses = []
    enqueued = []
    telemetry_events = []

    class _FakePipeline:
        def __init__(self, **_kwargs):
            pass

        def run(self):
            return SimpleNamespace(documents=[])

    monkeypatch.setattr(knowledge_imp.KnowledgeDao, "query_by_id", staticmethod(lambda _knowledge_id: space))
    monkeypatch.setattr(
        knowledge_imp.KnowledgeRag,
        "init_knowledge_milvus_vectorstore_sync",
        staticmethod(lambda *_args, **_kwargs: object()),
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeRag,
        "init_knowledge_es_vectorstore_sync",
        staticmethod(lambda *_args, **_kwargs: object()),
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeUtils,
        "ensure_milvus_schema_ready",
        staticmethod(lambda **kwargs: kwargs["vector_client"]),
    )
    monkeypatch.setattr(knowledge_imp, "KnowledgeFilePipeline", _FakePipeline)
    monkeypatch.setattr(
        workstation_api.WorkStationService,
        "query_knowledge_space_config_with_meta",
        lambda: (SimpleNamespace(review_tag_visible=False), False, 1, False),
        raising=False,
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeSpaceReviewTagService,
        "apply_after_review_upload_parse",
        classmethod(lambda cls, **_kwargs: None),
        raising=False,
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeFileDao,
        "update",
        staticmethod(lambda db_file: updated_statuses.append(db_file.status)),
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeSpaceContentStat,
        "enqueue_file_stat_sync",
        staticmethod(lambda file_ids: enqueued.extend(file_ids)),
    )
    monkeypatch.setattr(
        knowledge_imp.telemetry_service,
        "log_event_sync",
        lambda **kwargs: telemetry_events.append(kwargs),
    )

    knowledge_imp.addEmbedding(3, [file_record])

    assert updated_statuses == [KnowledgeFileStatus.SUCCESS.value]
    assert enqueued == [41]
    assert telemetry_events[0]["event_data"].status == "success"
