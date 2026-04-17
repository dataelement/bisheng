import importlib
import sys
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import (
    SpaceFileNotFoundError,
    SpaceFolderNotFoundError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.knowledge.domain.models.knowledge import (
    AuthTypeEnum,
    Knowledge,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile


def _install_schema_stubs() -> None:
    if 'bisheng.api' not in sys.modules:
        api_module = ModuleType('bisheng.api')
        api_module.__path__ = []
        sys.modules['bisheng.api'] = api_module
    if 'bisheng.api.v1' not in sys.modules:
        v1_module = ModuleType('bisheng.api.v1')
        v1_module.__path__ = []
        sys.modules['bisheng.api.v1'] = v1_module
    if 'bisheng.api.v1.schemas' in sys.modules:
        schemas_module = sys.modules['bisheng.api.v1.schemas']
    else:
        schemas_module = ModuleType('bisheng.api.v1.schemas')

        class _DummySchema:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

            def model_dump(self):
                return self.kwargs

        schemas_module.KnowledgeFileOne = _DummySchema
        schemas_module.FileProcessBase = _DummySchema
        schemas_module.ExcelRule = _DummySchema
        sys.modules['bisheng.api.v1.schemas'] = schemas_module

    if 'bisheng.api.services' not in sys.modules:
        services_module = ModuleType('bisheng.api.services')
        services_module.__path__ = []
        sys.modules['bisheng.api.services'] = services_module
    if 'bisheng.api.services.audit_log' not in sys.modules:
        audit_log_module = ModuleType('bisheng.api.services.audit_log')

        class _DummyAuditLogService:
            @staticmethod
            async def create_knowledge_space(*args, **kwargs):
                return None

            @staticmethod
            async def delete_knowledge_space(*args, **kwargs):
                return None

            @staticmethod
            def create_knowledge(*args, **kwargs):
                return None

            @staticmethod
            def delete_knowledge(*args, **kwargs):
                return None

            @staticmethod
            def upload_knowledge_file(*args, **kwargs):
                return None

            @staticmethod
            def delete_knowledge_file(*args, **kwargs):
                return None

        audit_log_module.AuditLogService = _DummyAuditLogService
        sys.modules['bisheng.api.services.audit_log'] = audit_log_module

    if 'bisheng.knowledge.domain.services.knowledge_service' not in sys.modules:
        knowledge_service_module = ModuleType('bisheng.knowledge.domain.services.knowledge_service')

        class _DummyKnowledgeService:
            @staticmethod
            def delete_knowledge_file_in_vector(*args, **kwargs):
                return None

            @staticmethod
            def delete_knowledge_file_in_minio(*args, **kwargs):
                return None

        knowledge_service_module.KnowledgeService = _DummyKnowledgeService
        sys.modules['bisheng.knowledge.domain.services.knowledge_service'] = knowledge_service_module

    if 'bisheng.knowledge.domain.services.knowledge_audit_telemetry_service' not in sys.modules:
        telemetry_module = ModuleType('bisheng.knowledge.domain.services.knowledge_audit_telemetry_service')

        class _DummyKnowledgeAuditTelemetryService:
            @staticmethod
            async def audit_create_knowledge_space(*args, **kwargs):
                return None

            @staticmethod
            async def audit_delete_knowledge_space(*args, **kwargs):
                return None

            @staticmethod
            def telemetry_delete_knowledge(*args, **kwargs):
                return None

        telemetry_module.KnowledgeAuditTelemetryService = _DummyKnowledgeAuditTelemetryService
        sys.modules['bisheng.knowledge.domain.services.knowledge_audit_telemetry_service'] = telemetry_module

    if 'bisheng.knowledge.domain.services.knowledge_utils' not in sys.modules:
        knowledge_utils_module = ModuleType('bisheng.knowledge.domain.services.knowledge_utils')

        class _DummyKnowledgeUtils:
            async def update_folder_update_time(self, *args, **kwargs):
                return None

        knowledge_utils_module.KnowledgeUtils = _DummyKnowledgeUtils
        sys.modules['bisheng.knowledge.domain.services.knowledge_utils'] = knowledge_utils_module

    if 'bisheng.worker' not in sys.modules:
        worker_module = ModuleType('bisheng.worker')

        class _DummyCeleryTask:
            @staticmethod
            def delay(*args, **kwargs):
                return None

        worker_module.rebuild_knowledge_celery = _DummyCeleryTask()
        worker_module.__path__ = []
        sys.modules['bisheng.worker'] = worker_module

    if 'bisheng.worker.knowledge' not in sys.modules:
        worker_knowledge_module = ModuleType('bisheng.worker.knowledge')
        worker_knowledge_module.__path__ = []
        sys.modules['bisheng.worker.knowledge'] = worker_knowledge_module

    if 'bisheng.worker.knowledge.file_worker' not in sys.modules:
        file_worker_module = ModuleType('bisheng.worker.knowledge.file_worker')

        class _DummyFileWorkerTask:
            @staticmethod
            def delay(*args, **kwargs):
                return None

        file_worker_module.delete_knowledge_file_celery = _DummyFileWorkerTask()
        file_worker_module.parse_knowledge_file_celery = _DummyFileWorkerTask()
        sys.modules['bisheng.worker.knowledge.file_worker'] = file_worker_module
        sys.modules['bisheng.worker.knowledge'].file_worker = file_worker_module


def _load_service_class():
    _install_schema_stubs()
    module = importlib.import_module('bisheng.knowledge.domain.services.knowledge_space_service')
    return module.KnowledgeSpaceService


def _make_login_user(user_id: int = 7, user_name: str = 'tester') -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name=user_name,
        is_admin=lambda: False,
    )


def _make_space(
        *,
        space_id: int = 1,
        user_id: int = 1,
        auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
        state: int = KnowledgeState.PUBLISHED.value,
) -> Knowledge:
    return Knowledge(
        id=space_id,
        user_id=user_id,
        name='Knowledge Space',
        type=KnowledgeTypeEnum.SPACE.value,
        description='desc',
        model='model-1',
        state=state,
        is_released=False,
        auth_type=auth_type,
    )


def _make_file(
        *,
        file_id: int = 11,
        knowledge_id: int = 1,
        file_type: int = FileType.FILE.value,
        file_name: str = 'doc.txt',
        file_level_path: str = '',
        level: int = 0,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        knowledge_id=knowledge_id,
        file_name=file_name,
        file_type=file_type,
        file_level_path=file_level_path,
        level=level,
        object_name='minio/object',
    )


@pytest.fixture
def service():
    return _load_service_class()(MagicMock(), _make_login_user())


class TestGetSpaceInfo:

    @pytest.mark.asyncio
    async def test_raises_not_found_when_space_missing(self, service):
        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(SpaceNotFoundError):
                await service.get_space_info(1)

    @pytest.mark.asyncio
    async def test_requires_read_permission_for_private_space(self, service):
        private_space = _make_space(auth_type=AuthTypeEnum.PRIVATE)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=private_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_check:
            with pytest.raises(SpacePermissionDeniedError):
                await service.get_space_info(1)

        assert mock_check.await_args.kwargs['relation'] == 'can_read'


class TestDeleteSpace:

    @pytest.mark.asyncio
    async def test_uses_can_delete_permission_instead_of_creator_id(self, service):
        other_users_space = _make_space(user_id=999)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=other_users_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_check, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.asyncio.to_thread',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_delete_knowledge',
            new_callable=AsyncMock,
        ) as mock_delete, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.delete_resource_tuples',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeAuditTelemetryService.audit_delete_knowledge_space',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeAuditTelemetryService.telemetry_delete_knowledge',
        ):
            await service.delete_space(1)

        assert mock_check.await_args.kwargs['relation'] == 'can_delete'
        mock_delete.assert_awaited_once_with(knowledge_id=1)


class TestSpaceOwnershipValidation:

    @pytest.mark.asyncio
    async def test_delete_folder_rejects_cross_space_folder(self, service):
        foreign_folder = _make_file(
            file_id=21,
            knowledge_id=2,
            file_type=FileType.DIR.value,
            file_name='folder',
        )

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=foreign_folder,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ) as mock_delete_batch:
            with pytest.raises(SpaceFolderNotFoundError):
                await service.delete_folder(1, 21)

        mock_delete_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_folder_file_parent_rejects_cross_space_file(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        foreign_file = _make_file(file_id=31, knowledge_id=2, level=1, file_level_path='/5')

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=foreign_file,
        ):
            with pytest.raises(SpaceFileNotFoundError):
                await service.get_folder_file_parent(1, 31)

    @pytest.mark.asyncio
    async def test_batch_delete_rejects_cross_space_file_ids(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        foreign_file = _make_file(file_id=41, knowledge_id=2)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids',
            new_callable=AsyncMock,
            return_value=[foreign_file],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ) as mock_delete_batch:
            with pytest.raises(SpaceFileNotFoundError):
                await service.batch_delete(1, [41], [])

        mock_delete_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_batch_download_rejects_cross_space_file_ids(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        foreign_file = _make_file(file_id=51, knowledge_id=2)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids',
            new_callable=AsyncMock,
            return_value=[foreign_file],
        ):
            with pytest.raises(SpaceFileNotFoundError):
                await service.batch_download(1, [51], [])

    @pytest.mark.asyncio
    async def test_batch_download_rejects_cross_space_folder_ids(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        foreign_folder = _make_file(
            file_id=61,
            knowledge_id=2,
            file_type=FileType.DIR.value,
            file_name='folder',
        )

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=foreign_folder,
        ):
            with pytest.raises(SpaceFolderNotFoundError):
                await service.batch_download(1, [], [61])
