import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _FakeAsyncIndexClient:
    def __init__(self):
        self.index_calls = []
        self.indices = SimpleNamespace(exists=AsyncMock(return_value=True))

    async def index(self, **kwargs):
        self.index_calls.append(kwargs)
        return {"result": "created"}


class _FakeSyncIndexClient:
    def __init__(self):
        self.deleted_queries = []
        self.refreshed_indices = []
        self.indices = SimpleNamespace(exists=lambda **kwargs: True, refresh=self.refresh_index)

    def refresh_index(self, **kwargs):
        self.refreshed_indices.append(kwargs)
        return {"_shards": {"successful": 1}}

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

    previous_worker_main = sys.modules.get("bisheng.worker.main", _MISSING)
    try:
        sys.modules["bisheng.worker.main"] = SimpleNamespace(bisheng_celery=_DummyCelery())
        module_path = Path(__file__).parents[1] / "bisheng" / "worker" / "telemetry" / "mid_table.py"
        spec = importlib.util.spec_from_file_location("test_pending_mid_table_under_test", module_path)
        worker_module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(worker_module)
        return worker_module
    finally:
        if previous_worker_main is _MISSING:
            sys.modules.pop("bisheng.worker.main", None)
        else:
            sys.modules["bisheng.worker.main"] = previous_worker_main


@pytest.mark.asyncio
async def test_knowledge_space_content_log_preview_success_builds_preview_record(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    fake_client = _FakeAsyncIndexClient()

    async def fake_get_es_connection():
        return fake_client

    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection", fake_get_es_connection)
    monkeypatch.setattr(module.KnowledgeSpaceContentStat, "_get_user_departments", AsyncMock(return_value=[]))
    monkeypatch.setattr(module, "generate_uuid", lambda: "event-1")

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

    assert fake_client.index_calls
    call = fake_client.index_calls[0]
    assert call["index"] == "mid_knowledge_space_content_stat"
    assert call["id"] == "preview_event-1"
    assert call["document"]["record_type"] == "preview"
    assert call["document"]["event_id"] == "event-1"
    assert call["document"]["space_id"] == 3
    assert call["document"]["file_id"] == 11
    assert call["document"]["viewer_user_id"] == 9
    assert call["document"]["action_result"] == "success"


@pytest.mark.asyncio
async def test_knowledge_space_content_log_preview_success_enqueues_retry_on_es_failure(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    class _FailingAsyncIndexClient(_FakeAsyncIndexClient):
        async def index(self, **kwargs):
            raise RuntimeError("es unavailable")

    async def fake_get_es_connection():
        return _FailingAsyncIndexClient()

    retry_records = []

    async def fake_enqueue_preview_record(record):
        retry_records.append(record)

    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection", fake_get_es_connection)
    monkeypatch.setattr(module.KnowledgeSpaceContentStat, "_get_user_departments", AsyncMock(return_value=[]))
    monkeypatch.setattr(module.KnowledgeSpaceContentStat, "enqueue_preview_record_async", fake_enqueue_preview_record)
    monkeypatch.setattr(module, "generate_uuid", lambda: "event-retry")

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

    assert [record.es_id for record in retry_records] == ["preview_event-retry"]


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


def test_knowledge_space_content_enqueue_file_stat_sync_dedupes_schedule(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    fake_redis = _FakeRedisSetClient()
    fake_task = _FakeCeleryTask()
    fake_worker_package = ModuleType("bisheng.worker")
    fake_worker_package.__path__ = []
    fake_telemetry_package = ModuleType("bisheng.worker.telemetry")
    fake_telemetry_package.__path__ = []
    fake_worker_module = ModuleType("bisheng.worker.telemetry.mid_table")
    fake_worker_module.sync_pending_knowledge_space_content_stat = fake_task

    monkeypatch.setattr(module, "get_redis_client_sync", lambda: fake_redis, raising=False)
    monkeypatch.setitem(sys.modules, "bisheng.worker", fake_worker_package)
    monkeypatch.setitem(sys.modules, "bisheng.worker.telemetry", fake_telemetry_package)
    monkeypatch.setitem(sys.modules, "bisheng.worker.telemetry.mid_table", fake_worker_module)

    module.KnowledgeSpaceContentStat.enqueue_file_stat_sync([11, "11", 12, None])
    module.KnowledgeSpaceContentStat.enqueue_file_stat_sync([12])

    assert fake_redis.sets[module.KnowledgeSpaceContentStat.FILE_PENDING_KEY] == {"11", "12"}
    assert fake_task.apply_async_calls == [{"countdown": 5}]


def test_knowledge_space_content_pop_pending_file_ids_caps_batch_size(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    fake_redis = _FakeRedisSetClient()
    fake_redis.sets[module.KnowledgeSpaceContentStat.FILE_PENDING_KEY] = {str(idx) for idx in range(600)}
    monkeypatch.setattr(module, "get_redis_client_sync", lambda: fake_redis, raising=False)

    file_ids = module.KnowledgeSpaceContentStat.pop_pending_file_ids_sync()

    assert len(file_ids) == 500
    assert len(fake_redis.sets[module.KnowledgeSpaceContentStat.FILE_PENDING_KEY]) == 100


def test_sync_pending_knowledge_space_content_stat_uses_mysql_current_state(monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus

    worker_module = _import_worker_mid_table()
    stat_cls = worker_module.KnowledgeSpaceContentStat

    success_file = SimpleNamespace(
        id=21,
        user_id=7,
        user_name="上传人",
        create_time=None,
        knowledge_id=3,
        file_name="成功.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
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
    )
    space = SimpleNamespace(id=3, name="空间", type=3)
    upserted = []
    deleted = []
    acked_file_ids = []

    monkeypatch.setattr(stat_cls, "clear_scheduled_sync", lambda: None, raising=False)
    monkeypatch.setattr(stat_cls, "acquire_lock_sync", lambda: True, raising=False)
    monkeypatch.setattr(stat_cls, "release_lock_sync", lambda: None, raising=False)
    monkeypatch.setattr(
        stat_cls,
        "peek_pending_file_ids_sync",
        lambda batch_size=500: [21, 22, 404],
        raising=False,
    )
    monkeypatch.setattr(stat_cls, "ack_pending_file_ids_sync", lambda file_ids: acked_file_ids.extend(file_ids))
    monkeypatch.setattr(stat_cls, "peek_pending_preview_payloads_sync", lambda batch_size=500: [], raising=False)
    monkeypatch.setattr(stat_cls, "peek_pending_space_rename_ids_sync", lambda: [], raising=False)
    monkeypatch.setattr(stat_cls, "peek_pending_space_delete_ids_sync", lambda: [], raising=False)
    monkeypatch.setattr(stat_cls, "has_pending_sync", lambda: False, raising=False)
    monkeypatch.setattr(stat_cls, "insert_records_sync", lambda self, records: upserted.extend(records))
    monkeypatch.setattr(
        stat_cls, "delete_file_records_sync", lambda self, file_ids: deleted.extend(file_ids), raising=False
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: _FakeSyncIndexClient()
    )
    monkeypatch.setattr(
        worker_module,
        "_get_knowledge_space_content_rows_by_file_ids",
        lambda file_ids: [(success_file, space), (waiting_file, space)],
        raising=False,
    )
    monkeypatch.setattr(worker_module, "get_user_from_ids_with_cache", lambda user_ids, user_map: user_map)

    worker_module.sync_pending_knowledge_space_content_stat.run()

    assert [record.es_id for record in upserted] == ["file_21"]
    assert deleted == [22, 404]
    assert acked_file_ids == [21, 22, 404]


def test_sync_pending_knowledge_space_content_stat_keeps_file_ids_when_upsert_fails(monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus

    worker_module = _import_worker_mid_table()
    stat_cls = worker_module.KnowledgeSpaceContentStat

    success_file = SimpleNamespace(
        id=21,
        user_id=7,
        user_name="上传人",
        create_time=None,
        knowledge_id=3,
        file_name="成功.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
    )
    space = SimpleNamespace(id=3, name="空间", type=3)
    acked_file_ids = []

    monkeypatch.setattr(stat_cls, "clear_scheduled_sync", lambda: None, raising=False)
    monkeypatch.setattr(stat_cls, "acquire_lock_sync", lambda: True, raising=False)
    monkeypatch.setattr(stat_cls, "release_lock_sync", lambda: None, raising=False)
    monkeypatch.setattr(stat_cls, "peek_pending_file_ids_sync", lambda batch_size=500: [21], raising=False)
    monkeypatch.setattr(stat_cls, "ack_pending_file_ids_sync", lambda file_ids: acked_file_ids.extend(file_ids))
    monkeypatch.setattr(stat_cls, "has_pending_sync", lambda: False, raising=False)
    monkeypatch.setattr(
        stat_cls,
        "insert_records_sync",
        lambda self, records: (_ for _ in ()).throw(RuntimeError("es down")),
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: _FakeSyncIndexClient()
    )
    monkeypatch.setattr(
        worker_module,
        "_get_knowledge_space_content_rows_by_file_ids",
        lambda file_ids: [(success_file, space)],
        raising=False,
    )
    monkeypatch.setattr(worker_module, "get_user_from_ids_with_cache", lambda user_ids, user_map: user_map)

    worker_module.sync_pending_knowledge_space_content_stat.run()

    assert acked_file_ids == []


def test_sync_pending_knowledge_space_content_stat_processes_preview_payloads(monkeypatch):
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentRecord

    worker_module = _import_worker_mid_table()
    stat_cls = worker_module.KnowledgeSpaceContentStat

    record = KnowledgeSpaceContentRecord(
        es_id="preview_event-1",
        record_type="preview",
        timestamp=1,
        user_id=9,
        user_name="查看人",
        user_group_infos=[],
        user_role_infos=[],
        user_department_infos=[],
        space_id=3,
        space_name="空间",
        file_id=21,
        file_name="成功.pdf",
        file_type=1,
        uploader_user_id=7,
        uploader_user_name="上传人",
        uploader_department_infos=[],
        event_id="event-1",
        viewer_user_id=9,
        viewer_user_name="查看人",
        action_result="success",
    )
    payload = stat_cls._serialize_preview_record(record)
    upserted = []
    acked_payloads = []

    monkeypatch.setattr(stat_cls, "clear_scheduled_sync", lambda: None, raising=False)
    monkeypatch.setattr(stat_cls, "acquire_lock_sync", lambda: True, raising=False)
    monkeypatch.setattr(stat_cls, "release_lock_sync", lambda: None, raising=False)
    monkeypatch.setattr(stat_cls, "peek_pending_file_ids_sync", lambda batch_size=500: [], raising=False)
    monkeypatch.setattr(stat_cls, "peek_pending_preview_payloads_sync", lambda batch_size=500: [payload], raising=False)
    monkeypatch.setattr(
        stat_cls,
        "ack_pending_preview_payloads_sync",
        lambda payloads: acked_payloads.extend(payloads),
    )
    monkeypatch.setattr(stat_cls, "peek_pending_space_rename_ids_sync", lambda: [], raising=False)
    monkeypatch.setattr(stat_cls, "peek_pending_space_delete_ids_sync", lambda: [], raising=False)
    monkeypatch.setattr(stat_cls, "has_pending_sync", lambda: False, raising=False)
    monkeypatch.setattr(stat_cls, "insert_records_sync", lambda self, records: upserted.extend(records))
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: _FakeSyncIndexClient()
    )

    worker_module.sync_pending_knowledge_space_content_stat.run()

    assert [one.es_id for one in upserted] == ["preview_event-1"]
    assert acked_payloads == [payload]


def test_sync_pending_knowledge_space_content_stat_handles_space_rename_and_delete(monkeypatch):
    worker_module = _import_worker_mid_table()
    stat_cls = worker_module.KnowledgeSpaceContentStat

    file_record = SimpleNamespace(
        id=31,
        user_id=8,
        user_name="上传人",
        create_time=None,
        knowledge_id=5,
        file_name="文件.pdf",
        file_type=1,
        status=2,
    )
    renamed_space = SimpleNamespace(id=5, name="新空间", type=3)
    upserted = []
    deleted_spaces = []
    acked_rename_ids = []
    acked_delete_ids = []

    monkeypatch.setattr(stat_cls, "clear_scheduled_sync", lambda: None, raising=False)
    monkeypatch.setattr(stat_cls, "acquire_lock_sync", lambda: True, raising=False)
    monkeypatch.setattr(stat_cls, "release_lock_sync", lambda: None, raising=False)
    monkeypatch.setattr(stat_cls, "peek_pending_file_ids_sync", lambda batch_size=500: [], raising=False)
    monkeypatch.setattr(stat_cls, "peek_pending_preview_payloads_sync", lambda batch_size=500: [], raising=False)
    monkeypatch.setattr(stat_cls, "peek_pending_space_rename_ids_sync", lambda: [5], raising=False)
    monkeypatch.setattr(
        stat_cls,
        "ack_pending_space_rename_ids_sync",
        lambda space_ids: acked_rename_ids.extend(space_ids),
    )
    monkeypatch.setattr(stat_cls, "peek_pending_space_delete_ids_sync", lambda: [6], raising=False)
    monkeypatch.setattr(
        stat_cls,
        "ack_pending_space_delete_ids_sync",
        lambda space_ids: acked_delete_ids.extend(space_ids),
    )
    monkeypatch.setattr(stat_cls, "has_pending_sync", lambda: False, raising=False)
    monkeypatch.setattr(stat_cls, "insert_records_sync", lambda self, records: upserted.extend(records))
    monkeypatch.setattr(
        stat_cls,
        "delete_space_file_records_sync",
        lambda self, space_ids: deleted_spaces.extend(space_ids),
        raising=False,
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: _FakeSyncIndexClient()
    )
    monkeypatch.setattr(
        worker_module,
        "_get_success_space_file_rows_by_space_id",
        lambda space_id, page, page_size: [(file_record, renamed_space)] if page == 1 else [],
        raising=False,
    )
    monkeypatch.setattr(worker_module, "get_user_from_ids_with_cache", lambda user_ids, user_map: user_map)

    worker_module.sync_pending_knowledge_space_content_stat.run()

    assert [(record.es_id, record.space_name) for record in upserted] == [("file_31", "新空间")]
    assert deleted_spaces == [6]
    assert acked_rename_ids == [5]
    assert acked_delete_ids == [6]


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
        knowledge_imp.settings,
        "get_knowledge",
        lambda: SimpleNamespace(version_management=None),
    )
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
