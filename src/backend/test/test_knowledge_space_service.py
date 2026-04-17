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
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
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

            @staticmethod
            def process_one_file(*args, **kwargs):
                return None

            @staticmethod
            def get_file_share_url(*args, **kwargs):
                return ('original', 'preview')

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

            def get_preview_cache_key(self, *args, **kwargs):
                return 'preview-cache-key'

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
    async def _get_user_group_ids(_user_id: int):
        return []

    return SimpleNamespace(
        user_id=user_id,
        user_name=user_name,
        is_admin=lambda: False,
        get_user_group_ids=_get_user_group_ids,
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


def _make_member(
        *,
        user_id: int = 8,
        user_role: UserRoleEnum = UserRoleEnum.MEMBER,
        status: MembershipStatusEnum = MembershipStatusEnum.ACTIVE,
        space_id: int = 1,
) -> SpaceChannelMember:
    return SpaceChannelMember(
        id=user_id,
        business_id=str(space_id),
        business_type=BusinessTypeEnum.SPACE,
        user_id=user_id,
        user_role=user_role,
        status=status,
    )


class _FakeReadTuplesFGA:
    def __init__(self, tuples_by_object=None):
        self.tuples_by_object = tuples_by_object or {}

    async def read_tuples(self, user=None, relation=None, object=None):
        if object is not None:
            return self.tuples_by_object.get(object, [])
        if user is not None:
            out = []
            for tuples in self.tuples_by_object.values():
                out.extend([t for t in tuples if t.get('user') == user])
            return out
        return []


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
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService._require_permission_id',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService._list_space_child_resources',
            new_callable=AsyncMock,
            return_value=[('folder', 201), ('knowledge_file', 202)],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.asyncio.to_thread',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_delete_knowledge',
            new_callable=AsyncMock,
        ) as mock_delete, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService._cleanup_resource_tuples',
            new_callable=AsyncMock,
        ) as mock_cleanup, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeAuditTelemetryService.audit_delete_knowledge_space',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeAuditTelemetryService.telemetry_delete_knowledge',
        ):
            await service.delete_space(1)

        assert mock_check.await_args.kwargs['relation'] == 'can_delete'
        mock_delete.assert_awaited_once_with(knowledge_id=1)
        mock_cleanup.assert_awaited_once_with([('folder', 201), ('knowledge_file', 202), ('knowledge_space', 1)])


class TestManagePermissionBoundaries:

    @pytest.mark.asyncio
    async def test_get_space_members_requires_manage_permission(self, service):
        with patch.object(
            service, '_require_manage_permission', new_callable=AsyncMock,
        ) as mock_require_manage, patch.object(
            service, '_require_write_permission', new_callable=AsyncMock,
        ) as mock_require_write, patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.find_space_members_paginated',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.count_space_members_with_keyword',
            new_callable=AsyncMock,
            return_value=0,
        ):
            resp = await service.get_space_members(1, page=1, page_size=20)

        assert resp.total == 0
        mock_require_manage.assert_awaited_once_with(1)
        mock_require_write.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_space_uses_manage_permission_when_auth_type_is_present(self, service):
        existing_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        updated_space = _make_space(auth_type=AuthTypeEnum.APPROVAL)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=existing_space,
        ), patch.object(
            service, '_require_manage_permission', new_callable=AsyncMock,
        ) as mock_require_manage, patch.object(
            service, '_require_write_permission', new_callable=AsyncMock,
        ) as mock_require_write, patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space',
            new_callable=AsyncMock,
            return_value=updated_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_members_by_space',
            new_callable=AsyncMock,
            return_value=[],
        ):
            await service.update_knowledge_space(1, auth_type=AuthTypeEnum.APPROVAL)

        mock_require_manage.assert_awaited_once_with(1)
        mock_require_write.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_space_without_auth_type_stays_on_write_permission(self, service):
        existing_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        updated_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=existing_space,
        ), patch.object(
            service, '_require_manage_permission', new_callable=AsyncMock,
        ) as mock_require_manage, patch.object(
            service, '_require_write_permission', new_callable=AsyncMock,
        ) as mock_require_write, patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space',
            new_callable=AsyncMock,
            return_value=updated_space,
        ):
            await service.update_knowledge_space(1, name='Renamed Space')

        mock_require_write.assert_awaited_once_with(1)
        mock_require_manage.assert_not_awaited()


class TestSpaceOwnershipValidation:

    @pytest.mark.asyncio
    async def test_delete_folder_rejects_cross_space_folder(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        foreign_folder = _make_file(
            file_id=21,
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
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=foreign_file,
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
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=foreign_file,
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


class TestTupleLifecycle:

    @pytest.mark.asyncio
    async def test_add_folder_initializes_folder_owner_and_parent_tuples(self, service):
        added_folder = _make_file(file_id=71, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')

        with patch.object(
            service, '_require_write_permission', new_callable=AsyncMock,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.count_folder_by_name',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aadd_file',
            new_callable=AsyncMock,
            return_value=added_folder,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.batch_write_tuples',
            new_callable=AsyncMock,
        ) as mock_batch_write, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
            new_callable=AsyncMock,
        ) as mock_write_owner, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            result = await service.add_folder(1, 'folder')

        assert result.id == 71
        parent_tuple = mock_batch_write.await_args.args[0][0]
        assert parent_tuple.user == 'knowledge_space:1'
        assert parent_tuple.relation == 'parent'
        assert parent_tuple.object == 'folder:71'
        mock_write_owner.assert_awaited_once_with(service.login_user.user_id, 'folder', '71')

    @pytest.mark.asyncio
    async def test_add_file_initializes_file_owner_and_parent_tuples(self, service):
        space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        added_file = _make_file(
            file_id=81,
            knowledge_id=1,
            file_type=FileType.FILE.value,
            file_name='doc.txt',
        )
        added_file.status = 5
        added_file.file_size = 1

        with patch.object(
            service, '_require_write_permission', new_callable=AsyncMock,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.UserRoleDao.aget_user_roles',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file',
            return_value=added_file,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.batch_write_tuples',
            new_callable=AsyncMock,
        ) as mock_batch_write, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
            new_callable=AsyncMock,
        ) as mock_write_owner, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            result = await service.add_file(1, ['/tmp/doc.txt'])

        assert result[0].id == 81
        parent_tuple = mock_batch_write.await_args.args[0][0]
        assert parent_tuple.user == 'knowledge_space:1'
        assert parent_tuple.relation == 'parent'
        assert parent_tuple.object == 'knowledge_file:81'
        mock_write_owner.assert_awaited_once_with(service.login_user.user_id, 'knowledge_file', '81')

    @pytest.mark.asyncio
    async def test_delete_file_cleans_knowledge_file_tuples(self, service):
        file_record = _make_file(file_id=82, knowledge_id=1)

        with patch.object(
            service, '_require_file_relation', new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.delete_resource_tuples',
            new_callable=AsyncMock,
        ) as mock_delete_tuples, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            await service.delete_file(82)

        mock_delete_tuples.assert_awaited_once_with('knowledge_file', '82')

    @pytest.mark.asyncio
    async def test_delete_folder_cleans_descendant_resource_tuples(self, service):
        folder = _make_file(file_id=91, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')
        child_folder = _make_file(file_id=92, knowledge_id=1, file_type=FileType.DIR.value, file_name='nested')
        child_file = _make_file(file_id=93, knowledge_id=1, file_type=FileType.FILE.value, file_name='doc.txt')

        with patch.object(
            service, '_require_folder_relation', new_callable=AsyncMock,
            return_value=folder,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_children_by_prefix',
            new_callable=AsyncMock,
            return_value=[child_folder, child_file],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.delete_resource_tuples',
            new_callable=AsyncMock,
        ) as mock_delete_tuples, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            await service.delete_folder(1, 91)

        deleted_resources = [(call.args[0], call.args[1]) for call in mock_delete_tuples.await_args_list]
        assert deleted_resources == [
            ('folder', '91'),
            ('folder', '92'),
            ('knowledge_file', '93'),
        ]

    @pytest.mark.asyncio
    async def test_rename_folder_uses_folder_can_edit(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        folder = _make_file(file_id=94, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')

        query_mock = AsyncMock(return_value=folder)
        check_mock = AsyncMock(return_value=True)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            query_mock,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            check_mock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.count_folder_by_name',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_update',
            new_callable=AsyncMock,
            return_value=folder,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            await service.rename_folder(94, 'renamed-folder')

        assert check_mock.await_args.kwargs['relation'] == 'can_edit'
        assert check_mock.await_args.kwargs['object_type'] == 'folder'
        assert check_mock.await_args.kwargs['object_id'] == '94'

    @pytest.mark.asyncio
    async def test_delete_file_uses_knowledge_file_can_delete(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        file_record = _make_file(file_id=95, knowledge_id=1)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_check, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.delete_resource_tuples',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            await service.delete_file(95)

        assert mock_check.await_args.kwargs['relation'] == 'can_delete'
        assert mock_check.await_args.kwargs['object_type'] == 'knowledge_file'
        assert mock_check.await_args.kwargs['object_id'] == '95'

    @pytest.mark.asyncio
    async def test_get_file_preview_uses_knowledge_file_can_read(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        file_record = _make_file(file_id=96, knowledge_id=1)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_check, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.get_file_share_url',
            return_value=('original', 'preview'),
        ):
            result = await service.get_file_preview(96)

        assert result['original_url'] == 'original'
        assert mock_check.await_args.kwargs['relation'] == 'can_read'
        assert mock_check.await_args.kwargs['object_type'] == 'knowledge_file'
        assert mock_check.await_args.kwargs['object_id'] == '96'

    @pytest.mark.asyncio
    async def test_public_subscribe_writes_viewer_tuple(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_count_user_space_subscriptions',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_insert_member',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            result = await service.subscribe_space(1)

        assert result['status'] == 'subscribed'
        grant = mock_authorize.await_args.kwargs['grants'][0]
        assert grant.relation == 'viewer'
        assert grant.subject_id == service.login_user.user_id

    @pytest.mark.asyncio
    async def test_public_to_approval_syncs_active_member_tuples(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        approval_space = _make_space(auth_type=AuthTypeEnum.APPROVAL)
        active_member = _make_member(user_id=9)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch.object(
            service, '_require_manage_permission', new_callable=AsyncMock,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space',
            new_callable=AsyncMock,
            return_value=approval_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_members_by_space',
            new_callable=AsyncMock,
            return_value=[active_member],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            await service.update_knowledge_space(1, auth_type=AuthTypeEnum.APPROVAL)

        grant = mock_authorize.await_args.kwargs['grants'][0]
        assert grant.relation == 'viewer'
        assert grant.subject_id == 9

    @pytest.mark.asyncio
    async def test_approval_to_public_activates_pending_members_and_syncs_tuples(self, service):
        approval_space = _make_space(auth_type=AuthTypeEnum.APPROVAL)
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        pending_member = _make_member(user_id=12, status=MembershipStatusEnum.PENDING)
        active_member = _make_member(user_id=12)

        get_members_mock = AsyncMock(side_effect=[[pending_member], [active_member]])

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=approval_space,
        ), patch.object(
            service, '_require_manage_permission', new_callable=AsyncMock,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_members_by_space',
            new_callable=AsyncMock,
            side_effect=get_members_mock.side_effect,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.update',
            new_callable=AsyncMock,
        ) as mock_update_member, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_delete_rejected_members',
            new_callable=AsyncMock,
        ) as mock_delete_rejected, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            await service.update_knowledge_space(1, auth_type=AuthTypeEnum.PUBLIC)

        assert pending_member.status == MembershipStatusEnum.ACTIVE
        mock_update_member.assert_awaited_once()
        mock_delete_rejected.assert_awaited_once_with(1)
        grant = mock_authorize.await_args.kwargs['grants'][0]
        assert grant.relation == 'viewer'
        assert grant.subject_id == 12

    @pytest.mark.asyncio
    async def test_unsubscribe_space_blocks_creator(self, service):
        owned_space = _make_space(user_id=service.login_user.user_id)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=owned_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=_make_member(user_id=service.login_user.user_id, user_role=UserRoleEnum.CREATOR),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.delete_space_member',
            new_callable=AsyncMock,
        ) as mock_delete_member:
            with pytest.raises(SpacePermissionDeniedError):
                await service.unsubscribe_space(1)

        mock_delete_member.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unsubscribe_space_revokes_active_member_tuple(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC, user_id=99)
        active_member = _make_member(user_id=service.login_user.user_id)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=active_member,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.delete_space_member',
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService._revoke_user_child_resource_tuples',
            new_callable=AsyncMock,
        ) as mock_revoke_child, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            result = await service.unsubscribe_space(1)

        assert result is True
        revoke = mock_authorize.await_args.kwargs['revokes'][0]
        assert revoke.relation == 'viewer'
        assert revoke.subject_id == service.login_user.user_id
        mock_revoke_child.assert_awaited_once_with(1, service.login_user.user_id)

    @pytest.mark.asyncio
    async def test_remove_member_revokes_child_resource_tuples(self, service):
        target_member = _make_member(user_id=88)

        with patch.object(
            service, '_require_manage_permission', new_callable=AsyncMock,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_active_member_role',
            new_callable=AsyncMock,
            return_value=UserRoleEnum.CREATOR,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=target_member,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.delete_space_member',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService._revoke_user_child_resource_tuples',
            new_callable=AsyncMock,
        ) as mock_revoke_child, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ):
            result = await service.remove_member(SimpleNamespace(space_id=1, user_id=88))

        assert result is True
        mock_revoke_child.assert_awaited_once_with(1, 88)


class TestFineGrainedPermissionRuntime:

    @pytest.mark.asyncio
    async def test_effective_permissions_use_bound_model_permissions(self, service):
        file_record = _make_file(file_id=120, knowledge_id=1)
        private_space = _make_space(space_id=1, auth_type=AuthTypeEnum.PRIVATE)
        fake_fga = _FakeReadTuplesFGA({
            'knowledge_file:120': [],
            'knowledge_space:1': [
                {'user': 'user:7', 'relation': 'viewer', 'object': 'knowledge_space:1'},
            ],
        })

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=private_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_get_current_user_subject_strings', new_callable=AsyncMock,
            return_value={'user:7'},
        ), patch.object(
            service, '_get_relation_bindings', new_callable=AsyncMock,
            return_value=[{
                'resource_type': 'knowledge_space',
                'resource_id': '1',
                'subject_type': 'user',
                'subject_id': 7,
                'relation': 'viewer',
                'model_id': 'custom_viewer',
                'include_children': None,
            }],
        ), patch.object(
            service, '_get_binding_department_paths', new_callable=AsyncMock,
            return_value={},
        ), patch.object(
            service, '_get_relation_models_map', new_callable=AsyncMock,
            return_value={
                'custom_viewer': {
                    'id': 'custom_viewer',
                    'relation': 'viewer',
                    'permissions': ['view_file'],
                    'is_system': False,
                },
            },
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService._get_fga',
            return_value=fake_fga,
        ):
            permission_ids = await service._get_effective_permission_ids(
                'knowledge_file',
                120,
                space_id=1,
            )

        assert permission_ids == {'view_file'}

    @pytest.mark.asyncio
    async def test_batch_download_denied_without_download_file_permission(self, service):
        file_record = _make_file(file_id=121, knowledge_id=1)
        public_space = _make_space(space_id=1, auth_type=AuthTypeEnum.PUBLIC)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ), patch.object(
            service, '_get_effective_permission_ids', new_callable=AsyncMock,
            return_value={'view_file'},
        ):
            with pytest.raises(SpacePermissionDeniedError):
                await service.batch_download(1, [121], [])

    @pytest.mark.asyncio
    async def test_delete_file_denied_without_delete_file_permission(self, service):
        file_record = _make_file(file_id=122, knowledge_id=1)
        public_space = _make_space(space_id=1, auth_type=AuthTypeEnum.PUBLIC)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ), patch.object(
            service, '_get_effective_permission_ids', new_callable=AsyncMock,
            return_value={'view_file', 'rename_file'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ) as mock_delete_batch:
            with pytest.raises(SpacePermissionDeniedError):
                await service.delete_file(122)

        mock_delete_batch.assert_not_awaited()
