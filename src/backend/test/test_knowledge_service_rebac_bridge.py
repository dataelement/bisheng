import asyncio
import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.database.models.role_access import AccessType
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum


def _install_service_stubs() -> None:
    if 'bisheng.api' not in sys.modules:
        api_module = ModuleType('bisheng.api')
        api_module.__path__ = []
        sys.modules['bisheng.api'] = api_module
    if 'bisheng.api.services' not in sys.modules:
        services_module = ModuleType('bisheng.api.services')
        services_module.__path__ = []
        sys.modules['bisheng.api.services'] = services_module
    if 'bisheng.api.services.knowledge_imp' not in sys.modules:
        knowledge_imp_module = ModuleType('bisheng.api.services.knowledge_imp')
        sys.modules['bisheng.api.services.knowledge_imp'] = knowledge_imp_module
    knowledge_imp_module = sys.modules['bisheng.api.services.knowledge_imp']

    class _DummyKnowledgeUtils:
        pass

    knowledge_imp_module.KnowledgeUtils = getattr(knowledge_imp_module, 'KnowledgeUtils', _DummyKnowledgeUtils)
    knowledge_imp_module.delete_knowledge_file_vectors = getattr(
        knowledge_imp_module, 'delete_knowledge_file_vectors', lambda *args, **kwargs: None,
    )
    knowledge_imp_module.process_file_task = getattr(
        knowledge_imp_module, 'process_file_task', lambda *args, **kwargs: None,
    )
    if 'bisheng.api.services.audit_log' not in sys.modules:
        audit_log_module = ModuleType('bisheng.api.services.audit_log')
        sys.modules['bisheng.api.services.audit_log'] = audit_log_module
    audit_log_module = sys.modules['bisheng.api.services.audit_log']

    class _DummyAuditLogService:
        @staticmethod
        async def create_knowledge(*args, **kwargs):
            return None

        @staticmethod
        async def delete_knowledge(*args, **kwargs):
            return None

        @staticmethod
        def create_knowledge_file(*args, **kwargs):
            return None

        @staticmethod
        def delete_knowledge_file(*args, **kwargs):
            return None

    audit_log_module.AuditLogService = getattr(audit_log_module, 'AuditLogService', _DummyAuditLogService)

    if 'bisheng.api.v1' not in sys.modules:
        v1_module = ModuleType('bisheng.api.v1')
        v1_module.__path__ = []
        sys.modules['bisheng.api.v1'] = v1_module
    if 'bisheng.api.v1.schema' not in sys.modules:
        schema_module = ModuleType('bisheng.api.v1.schema')
        schema_module.__path__ = []
        sys.modules['bisheng.api.v1.schema'] = schema_module
    if 'bisheng.api.v1.schema.knowledge' not in sys.modules:
        schema_knowledge_module = ModuleType('bisheng.api.v1.schema.knowledge')
        sys.modules['bisheng.api.v1.schema.knowledge'] = schema_knowledge_module
    schema_knowledge_module = sys.modules['bisheng.api.v1.schema.knowledge']

    class _DummyKnowledgeFileResp:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    schema_knowledge_module.KnowledgeFileResp = getattr(
        schema_knowledge_module, 'KnowledgeFileResp', _DummyKnowledgeFileResp,
    )

    if 'bisheng.api.v1.schemas' not in sys.modules:
        schemas_module = ModuleType('bisheng.api.v1.schemas')
        sys.modules['bisheng.api.v1.schemas'] = schemas_module
    schemas_module = sys.modules['bisheng.api.v1.schemas']

    class _DummySchema:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def model_dump(self):
            return self.kwargs

    for attr in (
        'FileChunk',
        'FileProcessBase',
        'KnowledgeFileOne',
        'KnowledgeFileProcess',
        'UpdatePreviewFileChunk',
        'ExcelRule',
        'KnowledgeFileReProcess',
    ):
        setattr(schemas_module, attr, _DummySchema)

    if 'bisheng.database.models.tag' not in sys.modules:
        tag_module = ModuleType('bisheng.database.models.tag')
        sys.modules['bisheng.database.models.tag'] = tag_module
    tag_module = sys.modules['bisheng.database.models.tag']
    tag_module.TagDao = getattr(tag_module, 'TagDao', SimpleNamespace())
    tag_module.TagBusinessTypeEnum = getattr(
        tag_module,
        'TagBusinessTypeEnum',
        SimpleNamespace(KNOWLEDGE='knowledge', KNOWLEDGE_FILE='knowledge_file'),
    )
    tag_module.Tag = getattr(tag_module, 'Tag', SimpleNamespace)

    if 'bisheng.worker' not in sys.modules:
        worker_module = ModuleType('bisheng.worker')
        worker_module.__path__ = []
        sys.modules['bisheng.worker'] = worker_module

    if 'bisheng.worker.knowledge' not in sys.modules:
        worker_knowledge_module = ModuleType('bisheng.worker.knowledge')
        worker_knowledge_module.__path__ = []
        sys.modules['bisheng.worker.knowledge'] = worker_knowledge_module

    if 'bisheng.worker.knowledge.file_worker' not in sys.modules:
        file_worker_module = ModuleType('bisheng.worker.knowledge.file_worker')
        sys.modules['bisheng.worker.knowledge.file_worker'] = file_worker_module
    file_worker_module = sys.modules['bisheng.worker.knowledge.file_worker']

    class _DummyFileWorkerTask:
        @staticmethod
        def delay(*args, **kwargs):
            return None

        @staticmethod
        def apply_async(*args, **kwargs):
            return None

    if not hasattr(file_worker_module, 'delete_knowledge_file_celery'):
        file_worker_module.delete_knowledge_file_celery = _DummyFileWorkerTask()
    elif not hasattr(file_worker_module.delete_knowledge_file_celery, 'apply_async'):
        file_worker_module.delete_knowledge_file_celery.apply_async = lambda *args, **kwargs: None
    if not hasattr(file_worker_module, 'parse_knowledge_file_celery'):
        file_worker_module.parse_knowledge_file_celery = _DummyFileWorkerTask()
    elif not hasattr(file_worker_module.parse_knowledge_file_celery, 'apply_async'):
        file_worker_module.parse_knowledge_file_celery.apply_async = lambda *args, **kwargs: None
    sys.modules['bisheng.worker.knowledge'].file_worker = file_worker_module


def _load_service_module():
    _install_service_stubs()
    services_package = importlib.import_module('bisheng.knowledge.domain.services')
    sys.modules.pop('bisheng.knowledge.domain.services.knowledge_service', None)
    module = importlib.import_module('bisheng.knowledge.domain.services.knowledge_service')
    setattr(services_package, 'knowledge_service', module)
    return module


def _load_service_class():
    return _load_service_module().KnowledgeService


@pytest.mark.asyncio
async def test_get_knowledge_lists_from_knowledge_library_object_type():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        rebac_list_accessible=AsyncMock(return_value=['1']),
    )

    with patch.object(
        service_module.KnowledgeDao,
        'aget_knowledge_ids_created_by',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        KnowledgeService.permission_service,
        'filter_knowledge_ids_by_permission_async',
        new_callable=AsyncMock,
        return_value=[1],
    ) as mock_filter_ids, patch.object(
        service_module.KnowledgeDao,
        'aget_user_knowledge',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        service_module.KnowledgeDao,
        'acount_user_knowledge',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        service_module.KnowledgeService,
        'aconvert_knowledge_read',
        new_callable=AsyncMock,
        return_value=[],
    ):
        result, total = await KnowledgeService.get_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
        )

    assert result == []
    assert total == 0
    login_user.rebac_list_accessible.assert_awaited_once_with('can_read', 'knowledge_library')
    mock_filter_ids.assert_awaited_once_with(
        login_user,
        [1],
        'use_kb',
    )


@pytest.mark.asyncio
async def test_get_knowledge_merges_creator_owned_ids_into_use_kb_filter_candidates():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        rebac_list_accessible=AsyncMock(return_value=['1']),
    )

    with patch.object(
        service_module.KnowledgeDao,
        'aget_knowledge_ids_created_by',
        new_callable=AsyncMock,
        return_value=[9],
    ), patch.object(
        KnowledgeService.permission_service,
        'filter_knowledge_ids_by_permission_async',
        new_callable=AsyncMock,
        return_value=[1, 9],
    ) as mock_filter_ids, patch.object(
        service_module.KnowledgeDao,
        'aget_user_knowledge',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        service_module.KnowledgeDao,
        'acount_user_knowledge',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        service_module.KnowledgeService,
        'aconvert_knowledge_read',
        new_callable=AsyncMock,
        return_value=[],
    ):
        await KnowledgeService.get_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
        )

    filter_args = mock_filter_ids.await_args.args
    assert filter_args[0] is login_user
    assert set(filter_args[1]) == {1, 9}
    assert filter_args[2] == 'use_kb'


@pytest.mark.asyncio
async def test_get_knowledge_supports_view_permission_filter_override():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        rebac_list_accessible=AsyncMock(return_value=['1']),
    )

    with patch.object(
        service_module.KnowledgeDao,
        'aget_knowledge_ids_created_by',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        KnowledgeService.permission_service,
        'filter_knowledge_ids_by_permission_async',
        new_callable=AsyncMock,
        return_value=[1],
    ) as mock_filter_ids, patch.object(
        service_module.KnowledgeDao,
        'aget_user_knowledge',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        service_module.KnowledgeDao,
        'acount_user_knowledge',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        service_module.KnowledgeService,
        'aconvert_knowledge_read',
        new_callable=AsyncMock,
        return_value=[],
    ):
        await KnowledgeService.get_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            permission_id='view_kb',
        )

    filter_args = mock_filter_ids.await_args.args
    assert filter_args[0] is login_user
    assert filter_args[1] == [1]
    assert filter_args[2] == 'view_kb'


@pytest.mark.asyncio
async def test_aconvert_knowledge_read_uses_permission_service_async_bridge_for_copiable():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(
        id=81,
        user_id=15,
        model_dump=lambda: {'id': 81, 'name': 'kb', 'description': '', 'type': 0, 'user_id': 15},
    )

    with patch.object(
        service_module.UserDao,
        'get_user_by_ids',
        return_value=[SimpleNamespace(user_id=15, user_name='owner')],
    ), patch.object(
        KnowledgeService.permission_service,
        'check_access_async',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_check_access:
        result = await KnowledgeService.aconvert_knowledge_read(login_user, [knowledge])

    assert len(result) == 1
    assert result[0].copiable is True
    mock_check_access.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=15,
        knowledge_id=81,
        access_type=AccessType.KNOWLEDGE_WRITE,
    )


def test_create_knowledge_hook_writes_knowledge_library_owner_tuple():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(id=11)

    with patch(
        'bisheng.permission.domain.services.owner_service.OwnerService.write_owner_tuple_sync',
    ) as mock_write_owner, patch.object(
        service_module.KnowledgeAuditTelemetryService,
        'audit_create_knowledge',
        create=True,
    ), patch.object(
        service_module.KnowledgeAuditTelemetryService,
        'telemetry_new_knowledge',
        create=True,
    ):
        assert KnowledgeService.create_knowledge_hook(MagicMock(), login_user, knowledge) is True

    mock_write_owner.assert_called_once_with(7, 'knowledge_library', '11')


def test_delete_knowledge_hook_deletes_knowledge_library_tuples():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(id=13)

    with patch(
        'bisheng.permission.domain.services.owner_service.OwnerService.delete_resource_tuples_sync',
    ) as mock_delete_tuples, patch.object(
        service_module.KnowledgeAuditTelemetryService,
        'audit_delete_knowledge',
        create=True,
    ):
        KnowledgeService.delete_knowledge_hook(MagicMock(), login_user, knowledge)

    mock_delete_tuples.assert_called_once_with('knowledge_library', '13')


def test_get_knowledge_info_uses_permission_service_sync_bridge():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(is_admin=lambda: False, user_id=7)
    knowledge = SimpleNamespace(id=31, user_id=9, model_dump=lambda: {})

    with patch.object(
        service_module.KnowledgeDao,
        'get_list_by_ids',
        return_value=[knowledge],
    ), patch.object(
        KnowledgeService.permission_service,
        'check_access_sync',
        return_value=True,
    ) as mock_check_access, patch.object(
        service_module.KnowledgeService,
        'convert_knowledge_read',
        return_value=['ok'],
    ) as mock_convert:
        result = KnowledgeService.get_knowledge_info(
            request=MagicMock(),
            login_user=login_user,
            knowledge_id=[31],
        )

    assert result == ['ok']
    mock_check_access.assert_called_once_with(
        login_user=login_user,
        owner_user_id=9,
        knowledge_id=31,
        access_type=AccessType.KNOWLEDGE,
    )
    mock_convert.assert_called_once_with(login_user, [knowledge])


def test_judge_knowledge_access_uses_permission_service_sync_bridge():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(id=32, user_id=10)

    with patch.object(
        service_module.KnowledgeDao,
        'query_by_id',
        return_value=knowledge,
    ), patch.object(
        KnowledgeService.permission_service,
        'ensure_access_sync',
    ) as mock_ensure_access:
        result = KnowledgeService.judge_knowledge_access(
            login_user=login_user,
            knowledge_id=32,
            access_type=AccessType.KNOWLEDGE_WRITE,
        )

    assert result is knowledge
    mock_ensure_access.assert_called_once_with(
        login_user=login_user,
        owner_user_id=10,
        knowledge_id=32,
        access_type=AccessType.KNOWLEDGE_WRITE,
    )


def test_update_knowledge_uses_permission_service_write_sync_bridge():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(user_id=7)
    db_knowledge = SimpleNamespace(
        id=41,
        user_id=12,
        name='old',
        description='old-desc',
        model_dump=lambda: {
            'id': 41,
            'name': 'new',
            'description': 'new-desc',
            'type': 0,
            'user_id': 12,
        },
    )
    req = SimpleNamespace(knowledge_id=41, name='new', description='new-desc')

    with patch.object(
        service_module.KnowledgeDao,
        'query_by_id',
        return_value=db_knowledge,
    ), patch.object(
        KnowledgeService.permission_service,
        'ensure_knowledge_write_sync',
    ) as mock_ensure_write, patch.object(
        service_module.KnowledgeDao,
        'get_knowledge_by_name',
        return_value=None,
    ), patch.object(
        service_module.KnowledgeDao,
        'update_one',
        return_value=db_knowledge,
    ), patch.object(
        service_module.UserDao,
        'get_user',
        return_value=SimpleNamespace(user_name='owner'),
    ):
        KnowledgeService.update_knowledge(MagicMock(), login_user, req)

    mock_ensure_write.assert_called_once_with(
        login_user=login_user,
        owner_user_id=12,
        knowledge_id=41,
    )


def test_delete_knowledge_file_uses_permission_service_write_sync_bridge():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(user_id=7, user_name='tester')
    db_file = SimpleNamespace(id=91, knowledge_id=51)
    knowledge = SimpleNamespace(id=51, user_id=13)

    with patch.object(
        service_module.KnowledgeFileDao,
        'select_list',
        return_value=[db_file],
    ), patch.object(
        service_module.KnowledgeDao,
        'query_by_id',
        return_value=knowledge,
    ), patch.object(
        KnowledgeService.permission_service,
        'ensure_knowledge_write_sync',
    ) as mock_ensure_write, patch.object(
        service_module,
        'delete_knowledge_file_vectors',
    ), patch.object(
        service_module.KnowledgeFileDao,
        'delete_batch',
    ), patch.object(
        service_module.KnowledgeAuditTelemetryService,
        'telemetry_delete_knowledge_file',
        create=True,
    ), patch.object(
        service_module.KnowledgeService,
        'delete_knowledge_file_hook',
    ):
        KnowledgeService.delete_knowledge_file(MagicMock(), login_user, [91])

    mock_ensure_write.assert_called_once_with(
        login_user=login_user,
        owner_user_id=13,
        knowledge_id=51,
    )


@pytest.mark.asyncio
async def test_get_readable_knowledge_uses_permission_service_bridge():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    knowledge = SimpleNamespace(id=21, user_id=8)
    login_user = SimpleNamespace(user_id=7)

    with patch.object(
        service_module.KnowledgeDao,
        'aquery_by_id',
        new_callable=AsyncMock,
        return_value=knowledge,
    ), patch.object(
        KnowledgeService.permission_service,
        'ensure_knowledge_read_async',
        new_callable=AsyncMock,
    ) as mock_ensure_read:
        result = await KnowledgeService._get_readable_knowledge(
            login_user=login_user,
            knowledge_id=21,
        )

    assert result is knowledge
    mock_ensure_read.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=8,
        knowledge_id=21,
    )


@pytest.mark.asyncio
async def test_get_writable_knowledge_uses_permission_service_bridge():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    knowledge = SimpleNamespace(id=22, user_id=9)
    login_user = SimpleNamespace(user_id=7)

    with patch.object(
        service_module.KnowledgeDao,
        'aquery_by_id',
        new_callable=AsyncMock,
        return_value=knowledge,
    ), patch.object(
        KnowledgeService.permission_service,
        'ensure_knowledge_write_async',
        new_callable=AsyncMock,
    ) as mock_ensure_write:
        result = await KnowledgeService._get_writable_knowledge(
            login_user=login_user,
            knowledge_id=22,
        )

    assert result is knowledge
    mock_ensure_write.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=9,
        knowledge_id=22,
    )


@pytest.mark.asyncio
async def test_retry_files_uses_permission_service_write_async_bridge():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(id=51, user_id=13)
    db_file = SimpleNamespace(id=91, knowledge_id=51)

    with patch.object(
        service_module.KnowledgeFileDao,
        'aget_file_by_ids',
        new_callable=AsyncMock,
        return_value=[db_file],
    ), patch.object(
        service_module.KnowledgeDao,
        'aquery_by_id',
        new_callable=AsyncMock,
        return_value=knowledge,
    ), patch.object(
        KnowledgeService.permission_service,
        'ensure_knowledge_write_async',
        new_callable=AsyncMock,
    ) as mock_ensure_write, patch.object(
        service_module.KnowledgeService,
        'process_retry_files',
        new_callable=AsyncMock,
        return_value=([], []),
        create=True,
    ), patch.object(
        service_module.KnowledgeService,
        'upload_knowledge_file_hook',
    ):
        await KnowledgeService.retry_files(
            request=MagicMock(),
            login_user=login_user,
            req_data={'file_objs': [{'id': 91}]},
        )

    mock_ensure_write.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=13,
        knowledge_id=51,
    )


def test_judge_qa_knowledge_write_uses_permission_service_write_sync_bridge():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(user_id=7)
    qa_knowledge = SimpleNamespace(id=61, user_id=14, type=KnowledgeTypeEnum.QA.value)

    with patch.object(
        service_module.KnowledgeDao,
        'query_by_id',
        return_value=qa_knowledge,
    ), patch.object(
        KnowledgeService.permission_service,
        'ensure_knowledge_write_sync',
    ) as mock_ensure_write:
        result = KnowledgeService.judge_qa_knowledge_write(login_user, 61)

    assert result is qa_knowledge
    mock_ensure_write.assert_called_once_with(
        login_user=login_user,
        owner_user_id=14,
        knowledge_id=61,
    )


def test_batch_download_files_uses_permission_service_read_async_bridge():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(id=71, user_id=15, name='kb-download')
    db_file = SimpleNamespace(id=101, knowledge_id=71, object_name='minio/object', file_name='doc.txt')
    fake_minio = SimpleNamespace(get_share_link_sync=lambda object_name: f'url:{object_name}')

    with patch.object(
        service_module.KnowledgeDao,
        'aquery_by_id',
        new_callable=AsyncMock,
        return_value=knowledge,
    ), patch.object(
        KnowledgeService.permission_service,
        'ensure_knowledge_read_async',
        new_callable=AsyncMock,
    ) as mock_ensure_read, patch.object(
        service_module.KnowledgeFileDao,
        'select_list',
        return_value=[db_file],
    ), patch.object(
        service_module,
        'get_minio_storage_sync',
        return_value=fake_minio,
    ):
        result = asyncio.run(KnowledgeService.batch_download_files(login_user, 71, [101]))

    assert result == 'url:minio/object'
    mock_ensure_read.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=15,
        knowledge_id=71,
    )


@pytest.mark.asyncio
async def test_aget_knowledge_files_uses_permission_service_read_async_bridge():
    service_module = _load_service_module()
    KnowledgeService = service_module.KnowledgeService
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(id=81, user_id=16, index_name='kb-index')

    with patch.object(
        service_module.KnowledgeDao,
        'aquery_by_id',
        new_callable=AsyncMock,
        return_value=knowledge,
    ), patch.object(
        KnowledgeService.permission_service,
        'ensure_knowledge_read_async',
        new_callable=AsyncMock,
    ) as mock_ensure_read, patch.object(
        service_module.KnowledgeFileDao,
        'aget_file_by_filters',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        service_module.KnowledgeFileDao,
        'acount_file_by_filters',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        service_module.TagDao,
        'get_tags_by_resource',
        return_value={},
        create=True,
    ), patch.object(
        KnowledgeService,
        'get_knowledge_files_title',
        return_value={},
    ), patch.object(
        KnowledgeService.permission_service,
        'check_access_async',
        new_callable=AsyncMock,
        return_value=False,
    ) as mock_check_write:
        data, total, writeable = await KnowledgeService.aget_knowledge_files(
            request=MagicMock(),
            login_user=login_user,
            knowledge_id=81,
            file_name='',
            status=[2],
            page=1,
            page_size=100,
            file_ids=None,
        )

    mock_ensure_read.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=16,
        knowledge_id=81,
    )
    mock_check_write.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=16,
        knowledge_id=81,
        access_type=AccessType.KNOWLEDGE_WRITE,
    )
    assert data == []
    assert total == 0
    assert writeable is False
