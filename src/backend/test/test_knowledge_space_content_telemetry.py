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
    monkeypatch.setattr(
        worker_module,
        "_get_dimension_department_map",
        lambda _departments: {},
    )


@pytest.mark.asyncio
async def test_knowledge_space_content_log_preview_success_queues_fresh_event(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(module.KnowledgeSpaceContentStat, "enqueue_success_event_async", enqueue)

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

    enqueue.assert_awaited_once_with(
        file_id=11,
        user_id=9,
        event_type="portal_document_read",
        record_type="preview_daily",
        source_app="bisheng_my_knowledge",
        scene="document_preview",
        entry_point="my_knowledge_preview",
        occurred_at=datetime(2026, 8, 3, 15, 30, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_favorite_space_preview_is_not_projected(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(module.KnowledgeSpaceContentStat, "enqueue_success_event_async", enqueue)

    await module.KnowledgeSpaceContentStat.log_preview_success(
        file_record=SimpleNamespace(id=11),
        space=SimpleNamespace(id=3, name="我的收藏", is_favorite=True),
        viewer_user_id=9,
        viewer_user_name="查看人",
    )

    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_knowledge_space_content_log_preview_success_does_not_raise_on_enqueue_failure(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module
    monkeypatch.setattr(
        module.KnowledgeSpaceContentStat,
        "enqueue_success_event_async",
        AsyncMock(return_value=False),
    )

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

    assert module.KnowledgeSpaceContentStat.enqueue_success_event_async.await_count == 1


def test_knowledge_space_content_build_file_record_contains_realtime_dimensions():
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module
    from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import (
        OrganizationNameSnapshot,
    )

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
    record = module.KnowledgeSpaceContentStat.build_file_record(
        file_record=file_record,
        space=space,
        uploader=uploader,
        space_level="department",
        uploader_organization=OrganizationNameSnapshot(company_name="首钢", department_name="质量部"),
        belonging_organization=OrganizationNameSnapshot(company_name="首钢", department_name="质量管理处"),
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
    assert record.uploader_company_name == "首钢"
    assert record.uploader_department_name == "质量部"
    assert record.belonging_company_name == "首钢"
    assert record.belonging_department_name == "质量管理处"
    assert record.projection_updated_at


@pytest.mark.parametrize(
    ("level", "expected_name"),
    [
        ("team", "团队库"),
        ("team_ks", "科室库"),
    ],
)
def test_content_sync_keeps_team_and_clinic_levels_separate(
    monkeypatch,
    level,
    expected_name,
):
    worker_module = _import_worker_mid_table()
    monkeypatch.setattr(
        worker_module,
        "get_user_from_ids_with_cache",
        lambda _ids, user_map: user_map,
    )
    monkeypatch.setattr(worker_module, "_get_dimension_department_map", lambda _departments: {})
    file_record = SimpleNamespace(
        id=11,
        tenant_id=1,
        user_id=0,
        user_name="",
        create_time=None,
        file_name="制度.pdf",
        file_type=1,
        split_rule=None,
        file_subcategory_code=None,
        file_encoding=None,
    )
    space = SimpleNamespace(id=3, tenant_id=1, name="知识空间")

    records, _ = worker_module._build_knowledge_space_content_records(
        [(file_record, space)],
        {},
        space_scope_map={3: SimpleNamespace(level=level)},
        space_department_map={3: None},
        # file_record has no original_knowledge_id, so 原始上传库 falls back to the current
        # space (id 3) — same fixture as space_scope_map/space_department_map above.
        original_space_scope_map={3: SimpleNamespace(level=level)},
        original_space_department_map={3: None},
        primary_department_map={},
        category_label_cache={1: ({}, {})},
    )

    assert records[0].space_level == level
    assert records[0].space_level_name == expected_name


def test_original_upload_organization_follows_original_space_not_current_uploader_department(monkeypatch):
    """Customer correction (2026-09-01): 原始上传库XX is a NEW, separate dimension — the
    library->org mapping of the file's ORIGINAL upload space (frozen forever, via
    KnowledgeFile.original_knowledge_id — see F081), not "whichever department the
    uploading person currently sits in". A file originally uploaded into dept-库A (bound
    to department A), later moved to dept-库B (bound to department B) by a DIFFERENT user
    who now belongs to department B, must report 原始上传库部门=A (frozen at the original
    space) while 上传人部门 keeps its OLD, UNCHANGED meaning — the current uploader-of-record's
    current department, B — and belonging follows the CURRENT space, also B."""
    worker_module = _import_worker_mid_table()
    monkeypatch.setattr(
        worker_module,
        "get_user_from_ids_with_cache",
        lambda _ids, user_map: user_map,
    )
    department_a = SimpleNamespace(id=101, org_level="dept", name="部门A", path="/101", status="active")
    department_b = SimpleNamespace(id=102, org_level="dept", name="部门B", path="/102", status="active")
    monkeypatch.setattr(
        worker_module,
        "_get_dimension_department_map",
        lambda _departments: {101: department_a, 102: department_b},
    )

    # Current entry: file now lives in space 20 (bound to department B), moved there by
    # user 2, who — per primary_department_map — currently sits in department B. Under the
    # OLD (buggy) logic, 原始上传库 would resolve to department B via this mover's own
    # department; under the fix it must resolve to department A (space 10, where the file
    # was ORIGINALLY uploaded), regardless of who moved it or where they sit today.
    file_record = SimpleNamespace(
        id=11,
        tenant_id=1,
        user_id=2,
        user_name="搬运者",
        original_knowledge_id=10,
        create_time=None,
        file_name="方案.pdf",
        file_type=1,
        split_rule=None,
        file_subcategory_code=None,
        file_encoding=None,
    )
    current_space = SimpleNamespace(id=20, tenant_id=1, name="部门B知识库")

    records, _ = worker_module._build_knowledge_space_content_records(
        [(file_record, current_space)],
        {},
        space_scope_map={20: SimpleNamespace(level="department")},
        space_department_map={20: department_b},
        original_space_scope_map={10: SimpleNamespace(level="department")},
        original_space_department_map={10: department_a},
        primary_department_map={2: department_b},
        category_label_cache={1: ({}, {})},
    )

    record = records[0]
    assert record.original_upload_department_name == "部门A"
    assert record.uploader_department_name == "部门B"
    assert record.belonging_department_name == "部门B"


def test_original_upload_organization_falls_back_to_current_space_when_original_id_missing(monkeypatch):
    """Files created before 2026-08-10 (or not yet covered by
    backfill_knowledge_file_original_origin.py) have original_knowledge_id=None — 原始上传库
    must degrade to the current space's library->org mapping (still correct-shaped, just
    not frozen), not crash and not silently fall back to zero/empty."""
    worker_module = _import_worker_mid_table()
    monkeypatch.setattr(
        worker_module,
        "get_user_from_ids_with_cache",
        lambda _ids, user_map: user_map,
    )
    department_a = SimpleNamespace(id=101, org_level="dept", name="部门A", path="/101", status="active")
    monkeypatch.setattr(worker_module, "_get_dimension_department_map", lambda _departments: {101: department_a})

    file_record = SimpleNamespace(
        id=12,
        tenant_id=1,
        user_id=3,
        user_name="老用户",
        original_knowledge_id=None,
        create_time=None,
        file_name="旧文件.pdf",
        file_type=1,
        split_rule=None,
        file_subcategory_code=None,
        file_encoding=None,
    )
    space = SimpleNamespace(id=30, tenant_id=1, name="部门A知识库")

    records, _ = worker_module._build_knowledge_space_content_records(
        [(file_record, space)],
        {},
        space_scope_map={30: SimpleNamespace(level="department")},
        space_department_map={30: department_a},
        original_space_scope_map={30: SimpleNamespace(level="department")},
        original_space_department_map={30: department_a},
        # Any value works here (department-level resolution doesn't consult it) — it only
        # needs to cover user_id=3 so the missing-id branch doesn't hit a real DB session.
        primary_department_map={3: department_a},
        category_label_cache={1: ({}, {})},
    )

    assert records[0].original_upload_department_name == "部门A"


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
    assert stat._mappings["favorite_count"] == {"type": "long"}
    assert not {
        "space_department_id",
        "space_department_name",
        "primary_department_id",
        "primary_department_name",
        "uploader_department_infos",
    }.intersection(stat._mappings)


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
    ("level", "scope_fields", "expected_source"),
    [
        ("public", {}, "company"),
        ("department", {}, "binding"),
        ("team_ks", {}, "binding"),
        ("team", {"created_by": 8}, "creator"),
        ("personal", {"owner_id": 9}, "owner"),
    ],
)
def test_content_ownership_source_follows_space_level(
    level,
    scope_fields,
    expected_source,
):
    worker_module = _import_worker_mid_table()
    departments = {
        "company": SimpleNamespace(id=1),
        "binding": SimpleNamespace(id=2),
        "creator": SimpleNamespace(id=3),
        "owner": SimpleNamespace(id=4),
    }
    primary_departments = {
        8: departments["creator"],
        9: departments["owner"],
    }

    result = worker_module._resolve_belonging_start_department(
        scope=SimpleNamespace(level=level, **scope_fields),
        space_department=departments["binding"],
        primary_department_map=primary_departments,
        company_departments=[departments["company"]],
    )

    assert result is departments[expected_source]


def test_public_content_ownership_requires_unique_company():
    worker_module = _import_worker_mid_table()

    result = worker_module._resolve_belonging_start_department(
        scope=SimpleNamespace(level="public"),
        space_department=None,
        primary_department_map={},
        company_departments=[SimpleNamespace(id=1), SimpleNamespace(id=2)],
    )

    assert result is None


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
    )

    assert record.belonging_company_name is None
    assert record.belonging_department_name is None
    assert "belonging_company_name" not in record.model_dump()


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
    from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import (
        OrganizationNameSnapshot,
    )

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
        belonging_organization=OrganizationNameSnapshot(
            company_name="首钢",
            department_name="质量管理处",
        ),
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

    assert first.es_id == second.es_id
    assert first.es_id.startswith("download_daily:11:2026-08-03:")
    assert first.record_type == "download_daily"
    assert first.download_count == 2
    assert first.timestamp == 1785686400
    assert first.belonging_department_name == "质量管理处"
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

    assert len(inserted) == 1
    assert inserted[0].es_id.startswith("download_daily:11:2026-08-03:")
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


def test_full_file_projection_does_not_rebuild_or_clean_daily_records(monkeypatch):
    worker_module = _import_worker_mid_table()
    stat_cls = worker_module.KnowledgeSpaceContentStat
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection_sync",
        lambda: _FakeSyncIndexClient(),
    )
    monkeypatch.setattr(stat_cls, "renew_lock_sync", lambda _owner: True)
    monkeypatch.setattr(
        stat_cls,
        "delete_stale_file_records_sync",
        lambda self, _sync_run_id: 2,
    )
    monkeypatch.setattr(
        stat_cls,
        "delete_space_records_sync",
        lambda self, _space_ids: 1,
    )
    monkeypatch.setattr(
        stat_cls,
        "queue_status_sync",
        lambda: {
            "pending_count": 0,
            "processing_count": 0,
            "oldest_pending_age_ms": 0,
        },
    )
    monkeypatch.setattr(
        worker_module,
        "_get_success_space_file_rows",
        lambda _page, _page_size: [],
    )
    monkeypatch.setattr(worker_module, "_get_favorite_space_ids", lambda: [])
    monkeypatch.setattr(
        worker_module,
        "rebuild_knowledge_space_content_download_projection",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("daily history must not be rebuilt")
        ),
    )

    result = worker_module.rebuild_knowledge_space_content_file_projection("owner-a")

    assert result["synced"] == 0
    assert result["deleted_stale"] == 2
    assert result["deleted_favorite"] == 1
    assert not {
        "synced_download_daily",
        "deleted_stale_download_daily",
        "preview_daily",
        "favorite_daily",
    }.intersection(result)


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
        "bisheng.knowledge.rag.shared_space_storage.resolve_space_shared_routing",
        lambda *_args, **_kwargs: None,
    )
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
        knowledge_imp.KnowledgeSpaceAutoTagService,
        "apply_after_upload_parse",
        classmethod(lambda cls, **_kwargs: 0),
    )
    monkeypatch.setattr(
        knowledge_imp,
        "persist_parse_result_with_fulltext_intent",
        lambda _file: None,
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

    assert file_record.status == KnowledgeFileStatus.SUCCESS.value
    assert enqueued == [41]
    assert telemetry_events[0]["event_data"].status == "success"
