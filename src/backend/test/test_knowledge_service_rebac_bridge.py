import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

        class _DummyKnowledgeUtils:
            pass

        knowledge_imp_module.KnowledgeUtils = _DummyKnowledgeUtils
        knowledge_imp_module.delete_knowledge_file_vectors = lambda *args, **kwargs: None
        knowledge_imp_module.process_file_task = lambda *args, **kwargs: None
        sys.modules['bisheng.api.services.knowledge_imp'] = knowledge_imp_module
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

        class _DummySchema:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

            def model_dump(self):
                return self.kwargs

        schemas_module.FileChunk = _DummySchema
        schemas_module.FileProcessBase = _DummySchema
        schemas_module.KnowledgeFileOne = _DummySchema
        schemas_module.KnowledgeFileProcess = _DummySchema
        schemas_module.UpdatePreviewFileChunk = _DummySchema
        schemas_module.ExcelRule = _DummySchema
        schemas_module.KnowledgeFileReProcess = _DummySchema
        sys.modules['bisheng.api.v1.schemas'] = schemas_module


def _load_service_class():
    _install_service_stubs()
    module = importlib.import_module('bisheng.knowledge.domain.services.knowledge_service')
    return module.KnowledgeService


@pytest.mark.asyncio
async def test_get_knowledge_lists_from_knowledge_library_object_type():
    KnowledgeService = _load_service_class()
    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        rebac_list_accessible=AsyncMock(return_value=['1']),
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_service.KnowledgeDao.aget_knowledge_ids_created_by',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_service.KnowledgeDao.aget_user_knowledge',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_service.KnowledgeDao.acount_user_knowledge',
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_service.KnowledgeService.aconvert_knowledge_read',
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


def test_create_knowledge_hook_writes_knowledge_library_owner_tuple():
    KnowledgeService = _load_service_class()
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(id=11)

    with patch(
        'bisheng.permission.domain.services.owner_service.OwnerService.write_owner_tuple_sync',
    ) as mock_write_owner, patch(
        'bisheng.knowledge.domain.services.knowledge_service.KnowledgeAuditTelemetryService.audit_create_knowledge',
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_service.KnowledgeAuditTelemetryService.telemetry_new_knowledge',
    ):
        assert KnowledgeService.create_knowledge_hook(MagicMock(), login_user, knowledge) is True

    mock_write_owner.assert_called_once_with(7, 'knowledge_library', '11')


def test_delete_knowledge_hook_deletes_knowledge_library_tuples():
    KnowledgeService = _load_service_class()
    login_user = SimpleNamespace(user_id=7)
    knowledge = SimpleNamespace(id=13)

    with patch(
        'bisheng.permission.domain.services.owner_service.OwnerService.delete_resource_tuples_sync',
    ) as mock_delete_tuples, patch(
        'bisheng.knowledge.domain.services.knowledge_service.KnowledgeAuditTelemetryService.audit_delete_knowledge',
    ):
        KnowledgeService.delete_knowledge_hook(MagicMock(), login_user, knowledge)

    mock_delete_tuples.assert_called_once_with('knowledge_library', '13')
