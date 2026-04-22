import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.common.errcode.knowledge_space import DepartmentKnowledgeSpaceExistsError
from bisheng.knowledge.domain.models.knowledge import (
    AuthTypeEnum,
    Knowledge,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    DepartmentKnowledgeSpaceBatchCreateReq,
    DepartmentKnowledgeSpaceBatchItem,
)


def _install_service_stubs() -> None:
    if 'bisheng.api' not in sys.modules:
        api_module = ModuleType('bisheng.api')
        api_module.__path__ = []
        sys.modules['bisheng.api'] = api_module
    if 'bisheng.api.v1' not in sys.modules:
        v1_module = ModuleType('bisheng.api.v1')
        v1_module.__path__ = []
        sys.modules['bisheng.api.v1'] = v1_module
    if 'bisheng.api.v1.schemas' not in sys.modules:
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

            async def process_retry_files(self, *args, **kwargs):
                return ([], set())

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
    _install_service_stubs()
    module = importlib.import_module(
        'bisheng.knowledge.domain.services.department_knowledge_space_service'
    )
    return module.DepartmentKnowledgeSpaceService


def _make_login_user(*, is_admin: bool = True):
    return SimpleNamespace(
        user_id=1,
        user_name='admin',
        tenant_id=1,
        is_admin=lambda: is_admin,
    )


def _make_department(*, dept_id: int = 10, name: str = '财务部'):
    return SimpleNamespace(
        id=dept_id,
        dept_id=f'BS@{dept_id}',
        name=name,
        status='active',
    )


@pytest.mark.asyncio
async def test_batch_create_spaces_creates_binding_and_returns_infos():
    DepartmentKnowledgeSpaceService = _load_service_class()
    req = DepartmentKnowledgeSpaceBatchCreateReq(
        items=[DepartmentKnowledgeSpaceBatchItem(department_id=10)]
    )
    login_user = _make_login_user()
    department = _make_department()
    created_space = SimpleNamespace(id=101)
    created_info = SimpleNamespace(
        id=101,
        space_kind='department',
        department_id=10,
        department_name='财务部',
    )

    with patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentDao.aget_by_ids',
        new_callable=AsyncMock,
        return_value=[department],
    ), patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_department_ids',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentKnowledgeSpaceDao.acreate',
        new_callable=AsyncMock,
    ) as mock_binding_create, patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentService.aget_admins',
        new_callable=AsyncMock,
        return_value=[{'user_id': 2, 'user_name': 'dept-admin'}],
    ), patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentKnowledgeSpaceService._grant_default_department_admins',
        new_callable=AsyncMock,
    ) as mock_grant_admins, patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.KnowledgeSpaceService.create_knowledge_space',
        new_callable=AsyncMock,
        return_value=created_space,
    ), patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.KnowledgeSpaceService.get_space_info',
        new_callable=AsyncMock,
        return_value=created_info,
    ):
        result = await DepartmentKnowledgeSpaceService.batch_create_spaces(
            request=SimpleNamespace(),
            login_user=login_user,
            req=req,
        )

    assert result == [created_info]
    mock_binding_create.assert_awaited_once_with(
        tenant_id=1,
        department_id=10,
        space_id=101,
        created_by=1,
    )
    mock_grant_admins.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_create_spaces_rejects_duplicate_department_binding():
    DepartmentKnowledgeSpaceService = _load_service_class()
    req = DepartmentKnowledgeSpaceBatchCreateReq(
        items=[DepartmentKnowledgeSpaceBatchItem(department_id=10)]
    )
    login_user = _make_login_user()
    department = _make_department()
    existing_binding = SimpleNamespace(department_id=10)

    with patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentDao.aget_by_ids',
        new_callable=AsyncMock,
        return_value=[department],
    ), patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_department_ids',
        new_callable=AsyncMock,
        return_value=[existing_binding],
    ):
        with pytest.raises(DepartmentKnowledgeSpaceExistsError):
            await DepartmentKnowledgeSpaceService.batch_create_spaces(
                request=SimpleNamespace(),
                login_user=login_user,
                req=req,
            )


@pytest.mark.asyncio
async def test_batch_create_spaces_requires_super_admin():
    DepartmentKnowledgeSpaceService = _load_service_class()
    req = DepartmentKnowledgeSpaceBatchCreateReq(
        items=[DepartmentKnowledgeSpaceBatchItem(department_id=10)]
    )

    with pytest.raises(Exception):
        await DepartmentKnowledgeSpaceService.batch_create_spaces(
            request=SimpleNamespace(),
            login_user=_make_login_user(is_admin=False),
            req=req,
        )


@pytest.mark.asyncio
async def test_grant_default_department_admins_promotes_manual_member_consistently():
    DepartmentKnowledgeSpaceService = _load_service_class()
    existing_member = SpaceChannelMember(
        business_id='101',
        business_type=BusinessTypeEnum.SPACE,
        user_id=2,
        user_role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.ACTIVE,
        membership_source='manual',
    )

    with patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.SpaceChannelMemberDao.async_find_member',
        new_callable=AsyncMock,
        return_value=existing_member,
    ), patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.SpaceChannelMemberDao.update',
        new_callable=AsyncMock,
    ) as mock_update, patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.KnowledgeSpaceService._grant_space_membership_tuple',
        new_callable=AsyncMock,
    ) as mock_grant_tuple:
        await DepartmentKnowledgeSpaceService._grant_default_department_admins(
            request=SimpleNamespace(),
            login_user=_make_login_user(),
            space_id=101,
            admin_user_ids=[2],
        )

    assert existing_member.user_role == UserRoleEnum.ADMIN
    assert existing_member.membership_source == 'department_admin'
    assert existing_member.department_admin_promoted_from_role == UserRoleEnum.MEMBER.value
    mock_update.assert_awaited_once_with(existing_member)
    mock_grant_tuple.assert_awaited_once_with(101, existing_member)


@pytest.mark.asyncio
async def test_sync_removed_admin_restores_promoted_manual_member_role():
    DepartmentKnowledgeSpaceService = _load_service_class()
    existing_member = SpaceChannelMember(
        business_id='101',
        business_type=BusinessTypeEnum.SPACE,
        user_id=2,
        user_role=UserRoleEnum.ADMIN,
        status=MembershipStatusEnum.ACTIVE,
        membership_source='department_admin',
        department_admin_promoted_from_role=UserRoleEnum.MEMBER.value,
    )
    space_service = SimpleNamespace(
        _revoke_space_membership_tuple=AsyncMock(),
        _grant_space_membership_tuple=AsyncMock(),
    )

    with patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.SpaceChannelMemberDao.async_find_member',
        new_callable=AsyncMock,
        return_value=existing_member,
    ), patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.SpaceChannelMemberDao.update',
        new_callable=AsyncMock,
    ) as mock_update:
        await DepartmentKnowledgeSpaceService._sync_removed_admin(
            space_service=space_service,
            space_id=101,
            user_id=2,
        )

    assert existing_member.user_role == UserRoleEnum.MEMBER
    assert existing_member.membership_source == 'manual'
    assert existing_member.department_admin_promoted_from_role is None
    mock_update.assert_awaited_once_with(existing_member)
    space_service._revoke_space_membership_tuple.assert_awaited_once_with(101, 2, UserRoleEnum.ADMIN)
    space_service._grant_space_membership_tuple.assert_awaited_once_with(101, existing_member)


@pytest.mark.asyncio
async def test_get_all_department_spaces_returns_decorated_spaces():
    DepartmentKnowledgeSpaceService = _load_service_class()
    department = _make_department()
    space = Knowledge(
        id=101,
        user_id=1,
        name='财务部的知识空间',
        type=KnowledgeTypeEnum.SPACE.value,
        description='desc',
        model='embedding-1',
        state=KnowledgeState.PUBLISHED.value,
        is_released=True,
        auth_type=AuthTypeEnum.APPROVAL,
    )

    with patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_all',
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(space_id=101, department_id=10)],
    ), patch(
        'bisheng.knowledge.domain.models.knowledge.KnowledgeDao.async_get_spaces_by_ids',
        new_callable=AsyncMock,
        return_value=[space],
    ), patch(
        'bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentDao.aget_by_ids',
        new_callable=AsyncMock,
        return_value=[department],
    ), patch(
        'bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_department_ids_by_space_ids',
        new_callable=AsyncMock,
        return_value={101: 10},
    ):
        result = await DepartmentKnowledgeSpaceService.get_all_department_spaces(
            request=SimpleNamespace(),
            login_user=_make_login_user(),
            order_by='name',
        )

    assert len(result) == 1
    assert result[0].space_kind == 'department'
    assert result[0].department_id == 10
    assert result[0].department_name == '财务部'
