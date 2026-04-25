import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from bisheng.database.models.role_access import AccessType


def _install_endpoint_stubs() -> None:
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
        knowledge_imp_module.KnowledgeUtils = type('KnowledgeUtils', (), {})
        knowledge_imp_module.delete_knowledge_file_vectors = lambda *args, **kwargs: None
        knowledge_imp_module.process_file_task = lambda *args, **kwargs: None
        knowledge_imp_module.add_qa = lambda *args, **kwargs: None
        knowledge_imp_module.list_qa_by_knowledge_id = AsyncMock(return_value=([], 0))
        knowledge_imp_module.qa_status_change = lambda *args, **kwargs: None
        knowledge_imp_module.delete_vector_data = lambda *args, **kwargs: None
        knowledge_imp_module.recommend_question = lambda *args, **kwargs: []
        sys.modules['bisheng.api.services.knowledge_imp'] = knowledge_imp_module
        sys.modules['bisheng.api.services'].knowledge_imp = knowledge_imp_module
    if 'bisheng.api.services.audit_log' not in sys.modules:
        audit_log_module = ModuleType('bisheng.api.services.audit_log')

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

        audit_log_module.AuditLogService = _DummyAuditLogService
        sys.modules['bisheng.api.services.audit_log'] = audit_log_module

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

        class _DummyKnowledgeFileResp:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        schema_knowledge_module.KnowledgeFileResp = _DummyKnowledgeFileResp
        sys.modules['bisheng.api.v1.schema.knowledge'] = schema_knowledge_module
    if 'bisheng.api.v1.schemas' not in sys.modules:
        schemas_module = ModuleType('bisheng.api.v1.schemas')
        sys.modules['bisheng.api.v1.schemas'] = schemas_module
    schemas_module = sys.modules['bisheng.api.v1.schemas']

    class _DummySchema(BaseModel):
        pass

    schemas_module.FileChunk = _DummySchema
    schemas_module.FileProcessBase = _DummySchema
    schemas_module.KnowledgeFileOne = _DummySchema
    schemas_module.KnowledgeFileProcess = _DummySchema
    schemas_module.UpdatePreviewFileChunk = _DummySchema
    schemas_module.ExcelRule = _DummySchema
    schemas_module.UploadFileResponse = _DummySchema
    schemas_module.UpdateKnowledgeReq = _DummySchema
    schemas_module.KnowledgeFileReProcess = _DummySchema

    if 'bisheng.common.services' not in sys.modules:
        common_services_module = ModuleType('bisheng.common.services')
        common_services_module.telemetry_service = SimpleNamespace(log_event_sync=lambda *args, **kwargs: None)
        sys.modules['bisheng.common.services'] = common_services_module

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

    if 'bisheng.knowledge.api.dependencies' not in sys.modules:
        dependencies_module = ModuleType('bisheng.knowledge.api.dependencies')
        dependencies_module.get_knowledge_service = lambda: None
        dependencies_module.get_knowledge_file_service = lambda: None
        sys.modules['bisheng.knowledge.api.dependencies'] = dependencies_module

    if 'bisheng.role.domain.services.quota_service' not in sys.modules:
        quota_module = ModuleType('bisheng.role.domain.services.quota_service')
        quota_module.require_quota = lambda *args, **kwargs: (lambda fn: fn)
        quota_module.QuotaResourceType = SimpleNamespace(KNOWLEDGE_SPACE_FILE='knowledge_space_file')
        sys.modules['bisheng.role.domain.services.quota_service'] = quota_module

    if 'bisheng.worker' not in sys.modules:
        worker_module = ModuleType('bisheng.worker')
        worker_module.__path__ = []
        sys.modules['bisheng.worker'] = worker_module
    if 'bisheng.worker.knowledge' not in sys.modules:
        worker_knowledge_module = ModuleType('bisheng.worker.knowledge')
        worker_knowledge_module.__path__ = []
        sys.modules['bisheng.worker.knowledge'] = worker_knowledge_module
    if 'bisheng.worker.knowledge.qa' not in sys.modules:
        worker_qa_module = ModuleType('bisheng.worker.knowledge.qa')
        worker_qa_module.insert_qa_celery = SimpleNamespace(delay=lambda *args, **kwargs: None)
        sys.modules['bisheng.worker.knowledge.qa'] = worker_qa_module

    if 'bisheng.llm.domain' not in sys.modules:
        llm_domain_module = ModuleType('bisheng.llm.domain')
        llm_domain_module.LLMService = SimpleNamespace(get_workbench_llm=lambda *args, **kwargs: None)
        sys.modules['bisheng.llm.domain'] = llm_domain_module
    if 'bisheng.llm.domain.models' not in sys.modules:
        llm_models_module = ModuleType('bisheng.llm.domain.models')
        llm_models_module.LLMDao = SimpleNamespace(get_model_by_id=lambda *args, **kwargs: None)
        sys.modules['bisheng.llm.domain.models'] = llm_models_module
    if 'bisheng.llm.domain.const' not in sys.modules:
        llm_const_module = ModuleType('bisheng.llm.domain.const')
        llm_const_module.LLMModelType = SimpleNamespace(EMBEDDING=SimpleNamespace(value='embedding'))
        sys.modules['bisheng.llm.domain.const'] = llm_const_module


def _load_endpoint_module():
    _install_endpoint_stubs()
    return importlib.import_module('bisheng.knowledge.api.endpoints.knowledge')


@pytest.mark.asyncio
async def test_copy_knowledge_uses_permission_service_read_async_bridge():
    module = _load_endpoint_module()
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(id=11, user_id=8, state=1)

    with patch.object(module.UserPayload, 'assert_effective_web_menu_contains', new_callable=AsyncMock), patch(
        'bisheng.knowledge.api.endpoints.knowledge.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=knowledge,
    ), patch.object(
        module.KnowledgeService.permission_service,
        'ensure_knowledge_read_async',
        new_callable=AsyncMock,
    ) as mock_ensure_read, patch(
        'bisheng.knowledge.api.endpoints.knowledge.KnowledgeFileDao.async_count_file_by_filters',
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        'bisheng.knowledge.api.endpoints.knowledge.KnowledgeService.copy_knowledge',
        new_callable=AsyncMock,
        return_value='copied',
    ):
        await module.copy_knowledge(
            request=MagicMock(),
            background_tasks=MagicMock(),
            login_user=login_user,
            knowledge_id=11,
            knowledge_name='copy',
        )

    mock_ensure_read.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=8,
        knowledge_id=11,
    )


@pytest.mark.asyncio
async def test_copy_qa_knowledge_uses_permission_service_read_async_bridge():
    module = _load_endpoint_module()
    login_user = SimpleNamespace(user_id=7)
    qa_knowledge = SimpleNamespace(
        id=12,
        user_id=9,
        type=module.KnowledgeTypeEnum.QA.value,
        state=module.KnowledgeState.PUBLISHED.value,
    )

    with patch.object(module.UserPayload, 'assert_effective_web_menu_contains', new_callable=AsyncMock), patch(
        'bisheng.knowledge.api.endpoints.knowledge.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=qa_knowledge,
    ), patch.object(
        module.KnowledgeService.permission_service,
        'ensure_knowledge_read_async',
        new_callable=AsyncMock,
    ) as mock_ensure_read, patch(
        'bisheng.knowledge.api.endpoints.knowledge.QAKnoweldgeDao.async_count_by_id',
        new_callable=AsyncMock,
        return_value=1,
    ), patch(
        'bisheng.knowledge.api.endpoints.knowledge.KnowledgeService.copy_qa_knowledge',
        new_callable=AsyncMock,
        return_value='copied',
    ):
        await module.copy_qa_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_id=12,
            knowledge_name='copy',
        )

    mock_ensure_read.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=9,
        knowledge_id=12,
    )


@pytest.mark.asyncio
async def test_get_QA_list_uses_async_qa_permission_bridge():
    module = _load_endpoint_module()
    login_user = SimpleNamespace(user_id=7)
    db_knowledge = SimpleNamespace(id=13, user_id=10)

    with patch(
        'bisheng.knowledge.api.endpoints.knowledge.KnowledgeService.ajudge_qa_knowledge_write',
        new_callable=AsyncMock,
        return_value=db_knowledge,
    ) as mock_judge, patch(
        'bisheng.knowledge.api.endpoints.knowledge.knowledge_imp.list_qa_by_knowledge_id',
        new_callable=AsyncMock,
        return_value=([], 0),
    ), patch(
        'bisheng.knowledge.api.endpoints.knowledge.UserDao.get_user_by_ids',
        return_value=[],
    ), patch.object(
        module.KnowledgeService.permission_service,
        'check_access_async',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_check_access:
        await module.get_QA_list(
            qa_knowledge_id=13,
            page_size=10,
            page_num=1,
            question=None,
            answer=None,
            keyword=None,
            status=None,
            login_user=login_user,
        )

    mock_judge.assert_awaited_once_with(login_user, 13)
    mock_check_access.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=10,
        knowledge_id=13,
        access_type=AccessType.KNOWLEDGE_WRITE,
    )


@pytest.mark.asyncio
async def test_get_filelist_uses_async_knowledge_files_service_bridge():
    module = _load_endpoint_module()
    login_user = SimpleNamespace(user_id=7)
    request = MagicMock()

    with patch.object(
        module.KnowledgeService,
        'aget_knowledge_files',
        new_callable=AsyncMock,
        return_value=([], 0, True),
    ) as mock_aget_files, patch.object(
        module.KnowledgeService,
        'get_knowledge_files',
        side_effect=AssertionError('sync file_list bridge should not be used'),
    ):
        result = await module.get_filelist(
            request=request,
            login_user=login_user,
            file_name='',
            file_ids=None,
            knowledge_id=50,
            page_size=100,
            page_num=1,
            status=[2],
        )

    mock_aget_files.assert_awaited_once_with(
        request,
        login_user,
        50,
        '',
        [2],
        1,
        100,
        None,
    )
    assert result.data['total'] == 0


def test_qa_add_uses_judge_qa_knowledge_write():
    module = _load_endpoint_module()
    login_user = SimpleNamespace(user_id=7)
    payload = SimpleNamespace(knowledge_id=14, id=None, questions=['q'], user_id=None)
    db_knowledge = SimpleNamespace(id=14, user_id=10, type=module.KnowledgeTypeEnum.QA.value)

    with patch(
        'bisheng.knowledge.api.endpoints.knowledge.KnowledgeService.judge_qa_knowledge_write',
        return_value=db_knowledge,
    ) as mock_judge, patch(
        'bisheng.knowledge.api.endpoints.knowledge.QAKnoweldgeDao.get_qa_knowledge_by_name',
        return_value=None,
    ), patch(
        'bisheng.knowledge.api.endpoints.knowledge.add_qa',
    ):
        module.qa_add(QACreate=payload, login_user=login_user)

    mock_judge.assert_called_once_with(login_user, 14)


def test_qa_delete_uses_judge_qa_knowledge_write():
    module = _load_endpoint_module()
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(id=15, user_id=11, type=module.KnowledgeTypeEnum.QA.value)
    qa_item = SimpleNamespace(knowledge_id=15)

    with patch(
        'bisheng.knowledge.api.endpoints.knowledge.QAKnoweldgeDao.select_list',
        return_value=[qa_item],
    ), patch(
        'bisheng.knowledge.api.endpoints.knowledge.KnowledgeService.judge_qa_knowledge_write',
        return_value=knowledge,
    ) as mock_judge, patch(
        'bisheng.knowledge.api.endpoints.knowledge.knowledge_imp.delete_vector_data',
    ), patch(
        'bisheng.knowledge.api.endpoints.knowledge.QAKnoweldgeDao.delete_batch',
    ), patch(
        'bisheng.knowledge.api.endpoints.knowledge.telemetry_service.log_event_sync',
    ):
        module.qa_delete(ids=[1], login_user=login_user)

    mock_judge.assert_called_once_with(login_user, 15)


def test_switch_model_uses_permission_service_write_sync_bridge():
    module = _load_endpoint_module()
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(id=16, user_id=12, model='2', name='old', description='old', state=0)
    req_data = SimpleNamespace(knowledge_id=16, model_id=2, model_type='embedding', knowledge_name='new', description='desc')
    model_info = SimpleNamespace(model_type='embedding')

    with patch(
        'bisheng.knowledge.api.endpoints.knowledge.LLMDao.get_model_by_id',
        return_value=model_info,
    ), patch(
        'bisheng.knowledge.api.endpoints.knowledge.KnowledgeDao.query_by_id',
        return_value=knowledge,
    ), patch.object(
        module.KnowledgeService.permission_service,
        'ensure_knowledge_write_sync',
    ) as mock_ensure_write, patch(
        'bisheng.knowledge.api.endpoints.knowledge.KnowledgeDao.update_one',
        return_value=knowledge,
    ):
        module.update_knowledge_model(login_user=login_user, req_data=req_data)

    mock_ensure_write.assert_called_once_with(
        login_user=login_user,
        owner_user_id=12,
        knowledge_id=16,
    )
