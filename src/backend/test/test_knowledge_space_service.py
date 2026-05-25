import asyncio
import inspect
import importlib
import sys
from datetime import datetime, timedelta
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from bisheng.common.errcode.knowledge_space import (
    SpaceFileDuplicateError,
    SpaceFileSizeLimitError,
    SpaceFileNotFoundError,
    SpaceFolderNotFoundError,
    SpaceInvalidScopeOwnerError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.common.errcode.llm import WorkbenchEmbeddingError
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
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalFavoriteCreateReq,
    ShougangPortalFileSearchReq,
    ShougangPortalHomeReq,
    ShougangPortalSpaceInfoItemResp,
    SpaceSubscriptionStatusEnum,
)
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.database.models.user_group import UserGroupDao


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

        class _DummyWSModel(BaseModel):
            model_id: int | None = None
            model_name: str | None = None

        schemas_module.KnowledgeFileOne = _DummySchema
        schemas_module.FileProcessBase = _DummySchema
        schemas_module.ExcelRule = _DummySchema
        schemas_module.WSModel = _DummyWSModel
        sys.modules['bisheng.api.v1.schemas'] = schemas_module

    if 'bisheng.api.v1.schema' not in sys.modules:
        schema_pkg = ModuleType('bisheng.api.v1.schema')
        schema_pkg.__path__ = []
        sys.modules['bisheng.api.v1.schema'] = schema_pkg
    if 'bisheng.api.v1.schema.chat_schema' not in sys.modules:
        chat_schema_module = ModuleType('bisheng.api.v1.schema.chat_schema')

        class _DummyUseKnowledgeBaseParam(BaseModel):
            id: int | None = None

        chat_schema_module.UseKnowledgeBaseParam = _DummyUseKnowledgeBaseParam
        sys.modules['bisheng.api.v1.schema.chat_schema'] = chat_schema_module

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
        def create_knowledge_base(*args, **kwargs):
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

            # Version management audit methods (added in P2-T2)
            @staticmethod
            def audit_link_file_version(*args, **kwargs):
                return None

            @staticmethod
            def audit_set_primary_version(*args, **kwargs):
                return None

            @staticmethod
            def audit_delete_file_version(*args, **kwargs):
                return None

            @staticmethod
            def audit_dismiss_similar_file(*args, **kwargs):
                return None

        telemetry_module.KnowledgeAuditTelemetryService = _DummyKnowledgeAuditTelemetryService
        sys.modules['bisheng.knowledge.domain.services.knowledge_audit_telemetry_service'] = telemetry_module
        # Register as attribute on the parent package so pytest monkeypatch can resolve
        # dotted-path strings like "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service.X"
        import bisheng.knowledge.domain.services as _svc_pkg
        _svc_pkg.knowledge_audit_telemetry_service = telemetry_module

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

    if 'bisheng.llm.domain' not in sys.modules:
        llm_domain_module = ModuleType('bisheng.llm.domain')

        class _DummyLLMService:
            @staticmethod
            async def get_workbench_llm(*args, **kwargs):
                return None

        llm_domain_module.LLMService = _DummyLLMService
        sys.modules['bisheng.llm.domain'] = llm_domain_module

    workstation_services_pkg = ModuleType('bisheng.workstation.domain.services')
    workstation_services_pkg.__path__ = []
    workstation_service_module = ModuleType('bisheng.workstation.domain.services.workstation_service')

    class _DummyWorkStationService:
        pass

    workstation_service_module.WorkStationService = _DummyWorkStationService
    workstation_services_pkg.WorkStationService = _DummyWorkStationService
    sys.modules['bisheng.workstation.domain.services'] = workstation_services_pkg
    sys.modules['bisheng.workstation.domain.services.workstation_service'] = workstation_service_module

    if 'bisheng.worker' not in sys.modules:
        worker_module = ModuleType('bisheng.worker')
        worker_module.__path__ = []
        sys.modules['bisheng.worker'] = worker_module
    worker_module = sys.modules['bisheng.worker']

    class _DummyCeleryTask:
        @staticmethod
        def delay(*args, **kwargs):
            return None

    worker_module.rebuild_knowledge_celery = _DummyCeleryTask()

    if 'bisheng.worker.knowledge' not in sys.modules:
        worker_knowledge_module = ModuleType('bisheng.worker.knowledge')
        worker_knowledge_module.__path__ = []
        sys.modules['bisheng.worker.knowledge'] = worker_knowledge_module

    class _DummyFileWorkerTask:
        @staticmethod
        def delay(*args, **kwargs):
            return None

    if 'bisheng.worker.knowledge.file_worker' not in sys.modules:
        file_worker_module = ModuleType('bisheng.worker.knowledge.file_worker')

        def _dummy_copy_normal(*args, **kwargs):
            return None

        file_worker_module.delete_knowledge_file_celery = _DummyFileWorkerTask()
        file_worker_module.parse_knowledge_file_celery = _DummyFileWorkerTask()
        file_worker_module.copy_normal = _dummy_copy_normal
        sys.modules['bisheng.worker.knowledge.file_worker'] = file_worker_module
        sys.modules['bisheng.worker.knowledge'].file_worker = file_worker_module

    if 'bisheng.worker.knowledge.rebuild_knowledge_worker' not in sys.modules:
        rebuild_worker_module = ModuleType('bisheng.worker.knowledge.rebuild_knowledge_worker')
        rebuild_worker_module.rebuild_knowledge_file_chunk = _DummyFileWorkerTask()
        sys.modules['bisheng.worker.knowledge.rebuild_knowledge_worker'] = rebuild_worker_module
        sys.modules['bisheng.worker.knowledge'].rebuild_knowledge_worker = rebuild_worker_module


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
        tenant_id=1,
        is_admin=lambda: False,
        get_user_group_ids=_get_user_group_ids,
    )


def _make_space(
        *,
        space_id: int = 1,
        user_id: int = 1,
        auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
        state: int = KnowledgeState.PUBLISHED.value,
        is_released: bool = False,
) -> Knowledge:
    return Knowledge(
        id=space_id,
        user_id=user_id,
        name='Knowledge Space',
        type=KnowledgeTypeEnum.SPACE.value,
        description='desc',
        model='model-1',
        state=state,
        is_released=is_released,
        auth_type=auth_type,
    )


@pytest.mark.asyncio
async def test_create_options_allow_team_space_without_user_groups():
    KnowledgeSpaceService = _load_service_class()
    login_user = _make_login_user(user_id=7)
    svc = KnowledgeSpaceService(request=SimpleNamespace(), login_user=login_user)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.GroupDao.aget_visible_groups',
        new_callable=AsyncMock,
        return_value=([SimpleNamespace(id=5, group_name='公开组')], 1),
    ) as mock_visible_groups, patch.object(
        UserGroupDao,
        'aget_user_group',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        UserGroupDao,
        'aget_user_admin_group',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_user_admin_departments',
        new_callable=AsyncMock,
        return_value=[],
    ):
        options = await svc.get_create_options()

    assert options.can_create_team is True
    mock_visible_groups.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_user_groups_excludes_visible_public_groups_for_non_members():
    KnowledgeSpaceService = _load_service_class()
    login_user = _make_login_user(user_id=7)
    svc = KnowledgeSpaceService(request=SimpleNamespace(), login_user=login_user)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.GroupDao.aget_visible_groups',
        new_callable=AsyncMock,
        return_value=([SimpleNamespace(id=5, group_name='公开组')], 1),
    ) as mock_visible_groups, patch.object(
        UserGroupDao,
        'aget_user_group',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        UserGroupDao,
        'aget_user_admin_group',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.GroupDao.aget_group_by_ids',
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(id=5, group_name='公开组')],
    ):
        options = await svc.get_create_user_groups()

    assert options.data == []
    assert options.total == 0
    mock_visible_groups.assert_not_awaited()


@pytest.mark.asyncio
async def test_team_space_create_accepts_no_user_group_for_any_user():
    KnowledgeSpaceService = _load_service_class()
    login_user = _make_login_user(user_id=7)
    svc = KnowledgeSpaceService(request=SimpleNamespace(), login_user=login_user)
    svc._ensure_space_name_unique_in_scope = AsyncMock(return_value=None)
    svc._is_auto_tag_feature_visible = AsyncMock(return_value=False)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_spaces_by_user',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        UserGroupDao,
        'aget_user_group',
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_member_groups, patch.object(
        UserGroupDao,
        'aget_user_admin_group',
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_admin_groups, patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.LLMService.get_workbench_llm',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(embedding_model=SimpleNamespace(id='embedding-1')),
    ):
        level, owner_type, owner_id = await svc.validate_knowledge_space_create(
            name='团队空间',
            space_level=KnowledgeSpaceLevelEnum.TEAM,
        )

    assert level == KnowledgeSpaceLevelEnum.TEAM
    assert owner_type == KnowledgeSpaceOwnerTypeEnum.USER
    assert owner_id == 7
    mock_member_groups.assert_not_awaited()
    mock_admin_groups.assert_not_awaited()


@pytest.mark.asyncio
async def test_team_space_create_rejects_legacy_user_group_id():
    KnowledgeSpaceService = _load_service_class()
    login_user = _make_login_user(user_id=7)
    svc = KnowledgeSpaceService(request=SimpleNamespace(), login_user=login_user)
    svc._ensure_space_name_unique_in_scope = AsyncMock(return_value=None)
    svc._is_auto_tag_feature_visible = AsyncMock(return_value=False)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_spaces_by_user',
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.LLMService.get_workbench_llm',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(embedding_model=SimpleNamespace(id='embedding-1')),
    ):
        with pytest.raises(SpaceInvalidScopeOwnerError):
            await svc.validate_knowledge_space_create(
                name='团队空间',
                space_level=KnowledgeSpaceLevelEnum.TEAM,
                user_group_id=5,
            )


@pytest.mark.asyncio
async def test_create_user_groups_include_member_and_admin_groups():
    KnowledgeSpaceService = _load_service_class()
    login_user = _make_login_user(user_id=7)
    svc = KnowledgeSpaceService(request=SimpleNamespace(), login_user=login_user)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.GroupDao.aget_visible_groups',
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_visible_groups, patch.object(
        UserGroupDao,
        'aget_user_group',
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(group_id=5)],
    ), patch.object(
        UserGroupDao,
        'aget_user_admin_group',
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(group_id=6)],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.GroupDao.aget_group_by_ids',
        new_callable=AsyncMock,
        return_value=[
            SimpleNamespace(id=6, group_name='管理组'),
            SimpleNamespace(id=5, group_name='成员组'),
        ],
    ):
        options = await svc.get_create_user_groups()

    assert [item.id for item in options.data] == [5, 6]
    mock_visible_groups.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_team_space_writes_user_scope_without_default_group_grant():
    KnowledgeSpaceService = _load_service_class()
    login_user = _make_login_user(user_id=7)
    svc = KnowledgeSpaceService(request=SimpleNamespace(), login_user=login_user)
    svc._ensure_space_name_unique_in_scope = AsyncMock(return_value=None)
    svc._is_auto_tag_feature_visible = AsyncMock(return_value=False)
    created_space = _make_space(space_id=11, user_id=7)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_spaces_by_user',
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.LLMService.get_workbench_llm',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(embedding_model=SimpleNamespace(id='embedding-1')),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.create_knowledge_base',
        return_value=created_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_insert_member',
        new_callable=AsyncMock,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
        new_callable=AsyncMock,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.acreate',
        new_callable=AsyncMock,
    ) as mock_create_scope, patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
        new_callable=AsyncMock,
    ) as mock_authorize, patch(
        'bisheng.tenant.domain.services.resource_share_service.ResourceShareService.share_on_create',
        new_callable=AsyncMock,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeAuditTelemetryService.audit_create_knowledge_space',
        new_callable=AsyncMock,
    ):
        result = await svc.create_knowledge_space(
            name='团队空间',
            space_level=KnowledgeSpaceLevelEnum.TEAM,
        )

    assert result.id == 11
    mock_create_scope.assert_awaited_once()
    assert mock_create_scope.await_args.kwargs['space_id'] == 11
    assert mock_create_scope.await_args.kwargs['level'] == KnowledgeSpaceLevelEnum.TEAM
    assert mock_create_scope.await_args.kwargs['owner_type'] == KnowledgeSpaceOwnerTypeEnum.USER
    assert mock_create_scope.await_args.kwargs['owner_id'] == 7
    mock_authorize.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_shougang_portal_file_search_uses_batch_file_query(service):
    spaces = [
        _make_space(space_id=12, user_id=7),
        _make_space(space_id=18, user_id=7),
    ]
    spaces[0].name = '轧线技术案例库'
    spaces[1].name = '冷轧技术手册'
    files = [
        _make_file(file_id=1580, knowledge_id=12, file_name='热轧1580产线精轧机振动纹治理实践.pdf'),
        _make_file(file_id=1801, knowledge_id=18, file_name='冷轧板面缺陷处理.pdf'),
    ]

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
        new_callable=AsyncMock,
        return_value=spaces,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_space_filters',
        new_callable=AsyncMock,
        return_value=files,
    ) as mock_batch_files, patch.object(
        service,
        '_filter_visible_child_items',
        new_callable=AsyncMock,
        side_effect=lambda items, **_: items,
    ), patch.object(
        service,
        '_handle_file_folder_extra_info',
        new_callable=AsyncMock,
        return_value=[
            {
                **files[0].model_dump(),
                'tags': [{'id': 101, 'name': '热轧'}],
            },
            {
                **files[1].model_dump(),
                'tags': [{'id': 205, 'name': '板面缺陷'}],
            },
        ],
    ), patch.object(
        service,
        'search_space_children',
        new_callable=AsyncMock,
        side_effect=AssertionError('shougang portal search should use batch file query'),
    ):
        result = await service.search_shougang_portal_files(
            ShougangPortalFileSearchReq(
                space_ids=[12, 18],
                page=1,
                page_size=10,
                sort='updated_at',
            )
        )

    mock_batch_files.assert_awaited_once()
    assert mock_batch_files.await_args.kwargs['knowledge_ids'] == [12, 18]
    assert result['total'] == 2
    assert [item['space_id'] for item in result['data']] == [12, 18]


@pytest.mark.asyncio
async def test_shougang_portal_home_uses_batch_tag_and_file_queries(service):
    spaces = [
        _make_space(space_id=12, user_id=7),
        _make_space(space_id=18, user_id=7),
    ]
    spaces[0].name = '轧线技术案例库'
    spaces[1].name = '冷轧技术手册'
    files = [
        _make_file(file_id=1580, knowledge_id=12, file_name='热轧1580产线精轧机振动纹治理实践.pdf'),
        _make_file(file_id=1801, knowledge_id=18, file_name='冷轧板面缺陷处理.pdf'),
    ]

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
        new_callable=AsyncMock,
        return_value=spaces,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aget_tags_by_business_ids',
        new_callable=AsyncMock,
        return_value={
            '12': [SimpleNamespace(id=101, name='最新精选')],
            '18': [SimpleNamespace(id=102, name='典型案例')],
        },
    ) as mock_batch_tags, patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aget_resources_by_tags',
        new_callable=AsyncMock,
        return_value=[
            SimpleNamespace(tag_id=101, resource_id='1580'),
            SimpleNamespace(tag_id=102, resource_id='1801'),
        ],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_space_filters',
        new_callable=AsyncMock,
        return_value=files,
    ) as mock_batch_files, patch.object(
        service,
        '_filter_visible_child_items',
        new_callable=AsyncMock,
        side_effect=lambda items, **_: items,
    ), patch.object(
        service,
        '_handle_file_folder_extra_info',
        new_callable=AsyncMock,
        return_value=[
            {
                **files[0].model_dump(),
                'tags': [{'id': 101, 'name': '最新精选'}],
            },
            {
                **files[1].model_dump(),
                'tags': [{'id': 102, 'name': '典型案例'}],
            },
        ],
    ), patch.object(
        service,
        'search_space_children',
        new_callable=AsyncMock,
        side_effect=AssertionError('home aggregation should use batch file query'),
    ):
        result = await service.get_shougang_portal_home(
            ShougangPortalHomeReq(
                space_ids=[12, 18],
                sections=[
                    {'tag': '最新精选', 'page_size': 4},
                    {'tag': '典型案例', 'page_size': 4},
                ],
                hot_tags_limit=8,
            )
        )

    mock_batch_tags.assert_awaited_once()
    mock_batch_files.assert_awaited_once()
    assert mock_batch_files.await_args.kwargs['knowledge_ids'] == [12, 18]
    assert mock_batch_files.await_args.kwargs['file_ids'] == [1580, 1801]
    assert result['sections']['最新精选'][0]['space_id'] == 12
    assert result['sections']['典型案例'][0]['space_id'] == 18
    assert result['tags'] == ['最新精选', '典型案例']


@pytest.mark.asyncio
async def test_shougang_portal_personal_spaces_filters_to_writable_personal_spaces(service):
    personal_space = SimpleNamespace(
        id=7,
        name='个人沉淀库',
        description='个人知识空间',
        file_num=3,
        update_time='2026-05-15T09:30:00',
        space_level=KnowledgeSpaceLevelEnum.PERSONAL,
    )
    department_space = SimpleNamespace(
        id=8,
        name='部门知识空间',
        description='部门知识空间',
        file_num=1,
        update_time='2026-05-15T09:30:00',
        space_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
    )

    with patch.object(
        service,
        'get_grouped_spaces',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(personal_spaces=[personal_space, department_space]),
    ), patch.object(
        service,
        '_get_effective_permission_ids',
        new_callable=AsyncMock,
        side_effect=[{'view_space', 'upload_file'}, {'view_space'}],
    ):
        result = await service.get_shougang_portal_personal_spaces()

    assert result['total'] == 1
    assert result['data'][0]['id'] == 7
    assert result['data'][0]['file_count'] == 3


@pytest.mark.asyncio
async def test_shougang_portal_favorite_rejects_duplicate_by_name_or_md5(service):
    source_space = _make_space(space_id=12, user_id=99)
    target_space = _make_space(space_id=7, user_id=service.login_user.user_id)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    source_file.md5 = 'same-md5'

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        side_effect=[source_space, target_space],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
    ), patch.object(
        service,
        '_get_space_level',
        new_callable=AsyncMock,
        return_value=KnowledgeSpaceLevelEnum.PERSONAL,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.get_repeat_file',
        new_callable=AsyncMock,
        return_value=_make_file(file_id=99, knowledge_id=7, file_name='迁移指南.pdf'),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.file_worker.copy_normal',
        return_value=_make_file(file_id=100, knowledge_id=7, file_name='迁移指南.pdf'),
        create=True,
    ) as mock_copy:
        with pytest.raises(SpaceFileDuplicateError):
            await service.create_shougang_portal_favorite(
                ShougangPortalFavoriteCreateReq(
                    source_space_id=12,
                    source_file_id=1580,
                    target_space_id=7,
                )
            )

    mock_copy.assert_not_called()


@pytest.mark.asyncio
async def test_shougang_portal_favorite_copies_file_to_personal_space(service):
    source_space = _make_space(space_id=12, user_id=99)
    target_space = _make_space(space_id=7, user_id=service.login_user.user_id)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    source_file.md5 = 'md5-1580'
    copied_file = _make_file(file_id=100, knowledge_id=7, file_name='迁移指南.pdf')

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        side_effect=[source_space, target_space],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
    ) as mock_require_permission, patch.object(
        service,
        '_get_space_level',
        new_callable=AsyncMock,
        return_value=KnowledgeSpaceLevelEnum.PERSONAL,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.get_repeat_file',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.asyncio.to_thread',
        new_callable=AsyncMock,
        return_value=copied_file,
    ) as mock_to_thread, patch.object(
        service,
        '_initialize_child_resource_permissions',
        new_callable=AsyncMock,
    ) as mock_init_permissions, patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
        new_callable=AsyncMock,
    ) as mock_update_time:
        result = await service.create_shougang_portal_favorite(
            ShougangPortalFavoriteCreateReq(
                source_space_id=12,
                source_file_id=1580,
                target_space_id=7,
            )
        )

    assert result.file_id == 100
    assert result.space_id == 7
    assert result.title == '迁移指南'
    assert mock_require_permission.await_args_list[0].args == ('knowledge_file', 1580, 'view_file')
    assert mock_require_permission.await_args_list[1].args == ('knowledge_space', 7, 'upload_file')
    mock_to_thread.assert_awaited_once()
    copy_args = mock_to_thread.await_args.args
    assert copy_args[0].__self__ is service
    assert copy_args[0].__name__ == '_copy_shougang_portal_favorite_file'
    assert copy_args[1:4] == (source_file, source_space, target_space)
    assert copy_args[4]['shougang_portal_favorite']['source_file_id'] == 1580
    mock_init_permissions.assert_awaited_once_with('knowledge_file', 100, 'knowledge_space', 7)
    mock_update_time.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_shougang_portal_favorite_copy_thread_has_event_loop(service):
    source_space = _make_space(space_id=12, user_id=99)
    target_space = _make_space(space_id=7, user_id=service.login_user.user_id)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    copied_file = _make_file(file_id=100, knowledge_id=7, file_name='迁移指南.pdf')

    def _copy_requires_event_loop(*_args, **_kwargs):
        asyncio.get_event_loop()
        return copied_file

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.file_worker.copy_normal',
        side_effect=_copy_requires_event_loop,
    ):
        result = await asyncio.to_thread(
            service._copy_shougang_portal_favorite_file,
            source_file,
            source_space,
            target_space,
            {'shougang_portal_favorite': {'source_file_id': 1580}},
        )

    assert result.id == 100


@pytest.mark.asyncio
async def test_shougang_portal_share_link_hashes_password_and_invite_code(service):
    source_space = _make_space(space_id=12, user_id=99)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    saved_links = []

    async def _save_share_link(share_link):
        share_link.share_token = 'share-token-1580'
        saved_links.append(share_link)
        return share_link

    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='invite_code',
        visibility='public',
        allow_download=False,
        password='secret-password',
        expire_seconds=3600,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
    ) as mock_require_permission, patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        side_effect=_save_share_link,
    ):
        result = await service.create_shougang_portal_share_link(req)

    assert result.share_token == 'share-token-1580'
    assert result.link.endswith('/share/document/share-token-1580')
    assert len(result.invite_code) == 6
    mock_require_permission.assert_awaited_once_with('knowledge_file', 1580, 'share_file', space_id=12)
    meta_data = saved_links[0].meta_data
    assert meta_data['space_id'] == 12
    assert meta_data['file_id'] == 1580
    assert meta_data['share_type'] == 'invite_code'
    assert meta_data['permissions'] == {'view': True, 'download': False, 'upload': False}
    assert meta_data['password_hash'] != 'secret-password'
    assert meta_data['invite_code_hash'] != result.invite_code
    assert 'secret-password' not in str(meta_data)
    assert result.invite_code not in str(meta_data)


@pytest.mark.asyncio
async def test_shougang_portal_share_link_allows_file_uploader_when_share_permission_missing(service):
    source_space = _make_space(space_id=12, user_id=99)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    source_file.user_id = service.login_user.user_id
    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='public',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
        side_effect=SpacePermissionDeniedError(),
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(share_token='share-token-1580'),
    ):
        result = await service.create_shougang_portal_share_link(req)

    assert result.share_token == 'share-token-1580'


@pytest.mark.asyncio
async def test_shougang_portal_share_link_allows_file_uploader_with_string_login_user_id(service):
    service.login_user.user_id = str(service.login_user.user_id)
    source_space = _make_space(space_id=12, user_id=99)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    source_file.user_id = 7
    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='public',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
        side_effect=SpacePermissionDeniedError(),
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(share_token='share-token-1580'),
    ):
        result = await service.create_shougang_portal_share_link(req)

    assert result.share_token == 'share-token-1580'


@pytest.mark.asyncio
async def test_shougang_portal_share_link_allows_space_creator_when_share_permission_missing(service):
    source_space = _make_space(space_id=12, user_id=service.login_user.user_id)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    source_file.user_id = 99
    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='public',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
        side_effect=SpacePermissionDeniedError(),
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(share_token='share-token-1580'),
    ):
        result = await service.create_shougang_portal_share_link(req)

    assert result.share_token == 'share-token-1580'


@pytest.mark.asyncio
async def test_shougang_portal_share_link_allows_space_creator_with_string_login_user_id(service):
    service.login_user.user_id = str(service.login_user.user_id)
    source_space = _make_space(space_id=12, user_id=7)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    source_file.user_id = 99
    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='public',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
        side_effect=SpacePermissionDeniedError(),
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(share_token='share-token-1580'),
    ):
        result = await service.create_shougang_portal_share_link(req)

    assert result.share_token == 'share-token-1580'


@pytest.mark.asyncio
async def test_shougang_portal_share_link_allows_space_admin_when_share_permission_missing(service):
    source_space = _make_space(space_id=12, user_id=99)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    source_file.user_id = 99
    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='public',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
        side_effect=SpacePermissionDeniedError(),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
        new_callable=AsyncMock,
        return_value=_make_member(
            user_id=service.login_user.user_id,
            user_role=UserRoleEnum.ADMIN,
            space_id=12,
        ),
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(share_token='share-token-1580'),
    ):
        result = await service.create_shougang_portal_share_link(req)

    assert result.share_token == 'share-token-1580'


@pytest.mark.asyncio
async def test_shougang_portal_share_link_rejects_unrelated_user_when_share_permission_missing(service):
    source_space = _make_space(space_id=12, user_id=99)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    source_file.user_id = 99
    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='public',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
        side_effect=SpacePermissionDeniedError(),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
        new_callable=AsyncMock,
        return_value=None,
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
    ) as mock_save:
        with pytest.raises(SpacePermissionDeniedError):
            await service.create_shougang_portal_share_link(req)

    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_stores_department_id(service):
    source_space = _make_space(space_id=12, user_id=99)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    saved_links = []

    async def _save_share_link(share_link):
        share_link.share_token = 'share-token-1580'
        saved_links.append(share_link)
        return share_link

    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='department',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(department_id=33),
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        side_effect=_save_share_link,
    ):
        await service.create_shougang_portal_share_link(req)

    assert saved_links[0].meta_data['department_id'] == 33


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_uses_scope_owner_when_binding_missing(service):
    source_space = _make_space(space_id=12, user_id=99)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    saved_links = []

    async def _save_share_link(share_link):
        share_link.share_token = 'share-token-1580'
        saved_links.append(share_link)
        return share_link

    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='department',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(
            level=KnowledgeSpaceLevelEnum.DEPARTMENT,
            owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
            owner_id=44,
        ),
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        side_effect=_save_share_link,
    ):
        await service.create_shougang_portal_share_link(req)

    assert saved_links[0].meta_data['department_id'] == 44


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_uses_login_user_department_for_personal_space(service):
    source_space = _make_space(space_id=12, user_id=service.login_user.user_id)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    saved_links = []

    async def _save_share_link(share_link):
        share_link.share_token = 'share-token-1580'
        saved_links.append(share_link)
        return share_link

    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='department',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_space_department, patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(
            level=KnowledgeSpaceLevelEnum.PERSONAL,
            owner_type=KnowledgeSpaceOwnerTypeEnum.USER,
            owner_id=service.login_user.user_id,
        ),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_primary_department',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(department_id=66),
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        side_effect=_save_share_link,
    ):
        await service.create_shougang_portal_share_link(req)

    mock_space_department.assert_not_awaited()
    assert saved_links[0].meta_data['department_id'] == 66


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_uses_login_user_department_when_personal_scope_missing(service):
    source_space = _make_space(space_id=12, user_id=service.login_user.user_id)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    saved_links = []

    async def _save_share_link(share_link):
        share_link.share_token = 'share-token-1580'
        saved_links.append(share_link)
        return share_link

    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='department',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_space_department, patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_primary_department',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(department_id=66),
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        side_effect=_save_share_link,
    ):
        await service.create_shougang_portal_share_link(req)

    mock_space_department.assert_awaited_once_with(12)
    assert saved_links[0].meta_data['department_id'] == 66


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_falls_back_to_login_user_department_when_space_department_missing(
        service,
):
    source_space = _make_space(space_id=12, user_id=99)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    saved_links = []

    async def _save_share_link(share_link):
        share_link.share_token = 'share-token-1580'
        saved_links.append(share_link)
        return share_link

    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='department',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_space_department, patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_primary_department',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(department_id=66),
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        side_effect=_save_share_link,
    ):
        await service.create_shougang_portal_share_link(req)

    mock_space_department.assert_awaited_once_with(12)
    assert saved_links[0].meta_data['department_id'] == 66


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_requires_user_department_for_personal_space(service):
    source_space = _make_space(space_id=12, user_id=service.login_user.user_id)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='department',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(
            level=KnowledgeSpaceLevelEnum.PERSONAL,
            owner_type=KnowledgeSpaceOwnerTypeEnum.USER,
            owner_id=service.login_user.user_id,
        ),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_primary_department',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
    ) as mock_save:
        with pytest.raises(SpacePermissionDeniedError):
            await service.create_shougang_portal_share_link(req)

    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_requires_user_department_when_space_department_missing(service):
    source_space = _make_space(space_id=12, user_id=99)
    source_file = _make_file(file_id=1580, knowledge_id=12, file_name='迁移指南.pdf')
    req = SimpleNamespace(
        space_id=12,
        file_id=1580,
        share_type='link',
        visibility='department',
        allow_download=True,
        password='',
        expire_seconds=0,
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=source_space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        return_value=source_file,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_primary_department',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        service,
        '_require_permission_id',
        new_callable=AsyncMock,
    ), patch.object(
        service,
        '_save_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(share_token='share-token-1580'),
    ):
        with pytest.raises(SpacePermissionDeniedError):
            await service.create_shougang_portal_share_link(req)


@pytest.mark.asyncio
async def test_shougang_portal_share_link_verify_rejects_wrong_invite_code(service):
    share_link = SimpleNamespace(
        share_token='share-token-1580',
        resource_type='knowledge_space_file',
        status='active',
        create_time=datetime.now(),
        expire_time=3600,
        meta_data={
            'space_id': 12,
            'file_id': 1580,
            'file_name': '迁移指南.pdf',
            'share_type': 'invite_code',
            'visibility': 'public',
            'permissions': {'view': True, 'download': False, 'upload': False},
            'password_hash': '',
            'invite_code_hash': service._hash_shougang_portal_share_secret('ABC123'),
        },
    )

    with patch.object(
        service,
        '_get_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=share_link,
    ):
        with pytest.raises(SpacePermissionDeniedError):
            await service.verify_shougang_portal_share_link(
                'share-token-1580',
                SimpleNamespace(invite_code='BAD999', password=''),
            )


@pytest.mark.asyncio
async def test_shougang_portal_share_link_verify_returns_access_payload(service):
    share_link = SimpleNamespace(
        share_token='share-token-1580',
        resource_type='knowledge_space_file',
        status='active',
        create_time=datetime.now() - timedelta(seconds=30),
        expire_time=3600,
        meta_data={
            'space_id': 12,
            'file_id': 1580,
            'file_name': '迁移指南.pdf',
            'share_type': 'link',
            'visibility': 'public',
            'permissions': {'view': True, 'download': False, 'upload': False},
            'password_hash': service._hash_shougang_portal_share_secret('secret-password'),
            'invite_code_hash': '',
        },
    )

    with patch.object(
        service,
        '_get_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=share_link,
    ):
        result = await service.verify_shougang_portal_share_link(
            'share-token-1580',
            SimpleNamespace(password='secret-password', invite_code=''),
        )

    assert result.space_id == 12
    assert result.file_id == 1580
    assert result.allow_download is False


def _make_department_share_link(*, create_user_id: str = '99') -> SimpleNamespace:
    return SimpleNamespace(
        share_token='share-token-1580',
        resource_type='knowledge_space_file',
        status='active',
        create_time=datetime.now(),
        expire_time=3600,
        create_user_id=create_user_id,
        meta_data={
            'space_id': 12,
            'file_id': 1580,
            'file_name': '迁移指南.pdf',
            'share_type': 'link',
            'visibility': 'department',
            'department_id': 33,
            'permissions': {'view': True, 'download': True, 'upload': False},
            'password_hash': '',
            'invite_code_hash': '',
        },
    )


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_allows_child_department_member(service):
    share_link = _make_department_share_link()

    with patch.object(
        service,
        '_get_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=share_link,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(department_id=33),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(id=33, path='/1/33/'),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_subtree_ids',
        new_callable=AsyncMock,
        return_value=[33, 44],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(department_id=44)],
    ), patch(
        'bisheng.approval.domain.services.approval_service.ApprovalService.get_department_space_reviewer_user_ids',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_user_admin_departments',
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await service.verify_shougang_portal_share_link(
            'share-token-1580',
            SimpleNamespace(password='', invite_code=''),
        )

    assert result.space_id == 12
    assert result.allow_download is True


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_allows_creator_without_department_member(service):
    share_link = _make_department_share_link(create_user_id=str(service.login_user.user_id))

    with patch.object(
        service,
        '_get_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=share_link,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.approval.domain.services.approval_service.ApprovalService.get_department_space_reviewer_user_ids',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_user_admin_departments',
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await service.verify_shougang_portal_share_link(
            'share-token-1580',
            SimpleNamespace(password='', invite_code=''),
        )

    assert result.file_id == 1580


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_allows_reviewer(service):
    share_link = _make_department_share_link()

    with patch.object(
        service,
        '_get_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=share_link,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(department_id=33),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(id=33, path='/1/33/'),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_subtree_ids',
        new_callable=AsyncMock,
        return_value=[33],
    ), patch(
        'bisheng.approval.domain.services.approval_service.ApprovalService.get_department_space_reviewer_user_ids',
        new_callable=AsyncMock,
        return_value=[service.login_user.user_id],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_user_admin_departments',
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await service.verify_shougang_portal_share_link(
            'share-token-1580',
            SimpleNamespace(password='', invite_code=''),
        )

    assert result.share_token == 'share-token-1580'


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_allows_department_admin(service):
    share_link = _make_department_share_link()

    with patch.object(
        service,
        '_get_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=share_link,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(department_id=33),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(id=33, path='/1/33/'),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_subtree_ids',
        new_callable=AsyncMock,
        return_value=[33],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_user_admin_departments',
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(id=33, path='/1/33/')],
    ), patch(
        'bisheng.approval.domain.services.approval_service.ApprovalService.get_department_space_reviewer_user_ids',
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await service.verify_shougang_portal_share_link(
            'share-token-1580',
            SimpleNamespace(password='', invite_code=''),
        )

    assert result.share_token == 'share-token-1580'


@pytest.mark.asyncio
async def test_shougang_portal_department_share_link_rejects_other_department_user(service):
    share_link = _make_department_share_link()

    with patch.object(
        service,
        '_get_shougang_portal_share_link',
        new_callable=AsyncMock,
        return_value=share_link,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(department_id=33),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(id=33, path='/1/33/'),
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_subtree_ids',
        new_callable=AsyncMock,
        return_value=[33, 44],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(department_id=55)],
    ), patch(
        'bisheng.approval.domain.services.approval_service.ApprovalService.get_department_space_reviewer_user_ids',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_user_admin_departments',
        new_callable=AsyncMock,
        return_value=[],
    ):
        with pytest.raises(SpacePermissionDeniedError):
            await service.verify_shougang_portal_share_link(
                'share-token-1580',
                SimpleNamespace(password='', invite_code=''),
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
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value=set(),
        ) as mock_effective:
            with pytest.raises(SpacePermissionDeniedError):
                await service.get_space_info(1)

        mock_effective.assert_awaited_once_with('knowledge_space', 1)

    @pytest.mark.asyncio
    async def test_released_approval_space_allows_square_preview_without_rebac(self, service):
        approval_space = _make_space(
            auth_type=AuthTypeEnum.APPROVAL,
            is_released=True,
        )

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=approval_space,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value=set(),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_count_space_members',
            new_callable=AsyncMock,
            return_value=3,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock,
            return_value={1: 5},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.UserDao.aget_user',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(user_name='owner'),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_space_info(1)

        assert result.subscription_status == SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED
        assert result.is_followed is False

    @pytest.mark.asyncio
    async def test_released_public_space_allows_square_preview_without_rebac(self, service):
        public_space = _make_space(
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=True,
        )

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value=set(),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_count_space_members',
            new_callable=AsyncMock,
            return_value=3,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock,
            return_value={1: 5},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.UserDao.aget_user',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(user_name='owner'),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_space_info(1)

        assert result.subscription_status == SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED
        assert result.is_followed is False

    @pytest.mark.asyncio
    async def test_minimal_view_space_bound_model_marks_space_info_subscribed(self, service):
        private_space = _make_space(auth_type=AuthTypeEnum.PRIVATE, user_id=99)
        fake_fga = _FakeReadTuplesFGA({
            'knowledge_space:1': [
                {'user': 'user:7', 'relation': 'viewer', 'object': 'knowledge_space:1'},
            ],
        })

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=private_space,
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
                'model_id': 'custom_view_space',
                'include_children': None,
            }],
        ), patch.object(
            service, '_get_binding_department_paths', new_callable=AsyncMock,
            return_value={},
        ), patch.object(
            service, '_get_relation_models_map', new_callable=AsyncMock,
            return_value={
                'custom_view_space': {
                    'id': 'custom_view_space',
                    'relation': 'viewer',
                    'permissions': ['view_space'],
                    'is_system': False,
                },
            },
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService._get_fga',
            return_value=fake_fga,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_count_space_members',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock,
            return_value={1: 0},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.UserDao.aget_user',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(user_name='space-owner'),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='can_read',
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_space_info(1)

        assert result.id == 1
        assert result.user_role == UserRoleEnum.MEMBER
        assert result.subscription_status == SpaceSubscriptionStatusEnum.SUBSCRIBED
        assert result.is_followed is True

    @pytest.mark.asyncio
    async def test_maps_direct_owner_grant_to_admin_and_marks_subscribed(self, service):
        private_space = _make_space(auth_type=AuthTypeEnum.PRIVATE, user_id=99)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=private_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_count_space_members',
            new_callable=AsyncMock,
            return_value=3,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock,
            return_value={1: 5},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.UserDao.aget_user',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(user_name='other-user'),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='owner',
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_space_info(1)

        assert result.user_role == UserRoleEnum.ADMIN
        assert result.subscription_status == SpaceSubscriptionStatusEnum.SUBSCRIBED
        assert result.is_followed is True

    @pytest.mark.asyncio
    async def test_shougang_portal_space_infos_batch_loads_space_details(self, service):
        visible_space = _make_space(space_id=1, user_id=99, auth_type=AuthTypeEnum.PRIVATE)
        denied_space = _make_space(space_id=3, user_id=88, auth_type=AuthTypeEnum.PRIVATE)
        member = _make_member(user_id=service.login_user.user_id, user_role=UserRoleEnum.MEMBER, space_id=1)

        async def _effective_permission_ids(_object_type: str, object_id: int, **_kwargs):
            return {'view_space'} if object_id == 1 else set()

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
            new_callable=AsyncMock,
            return_value=[visible_space, denied_space],
        ) as mock_get_spaces, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
        ) as mock_query_one, patch.object(
            service,
            '_get_effective_permission_ids',
            new_callable=AsyncMock,
            side_effect=_effective_permission_ids,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock,
            return_value={1: 4},
        ) as mock_count_files, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_count_members_batch',
            new_callable=AsyncMock,
            return_value={'1': 9},
        ) as mock_count_members, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_all_members_for_spaces',
            new_callable=AsyncMock,
            return_value=[member],
        ) as mock_get_members, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.UserDao.aget_user_by_ids',
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(user_id=99, user_name='space-owner')],
        ) as mock_get_users, patch.object(
            service,
            '_can_unsubscribe_space',
            new_callable=AsyncMock,
            return_value=False,
        ), patch.object(
            service,
            '_decorate_department_metadata',
            new_callable=AsyncMock,
            side_effect=lambda spaces: spaces,
        ):
            result = await service.get_shougang_portal_space_infos([1, 2, 3])

        mock_get_spaces.assert_awaited_once_with([1, 2, 3], order_by='update_time')
        mock_query_one.assert_not_awaited()
        mock_count_files.assert_awaited_once_with([1])
        mock_count_members.assert_awaited_once_with(['1'])
        mock_get_members.assert_awaited_once_with(service.login_user.user_id, ['1'])
        mock_get_users.assert_awaited_once_with([99])
        assert all(isinstance(item, ShougangPortalSpaceInfoItemResp) for item in result)
        assert result[0].id == 1
        assert result[0].data["id"] == 1
        assert result[0].data["name"] == "Knowledge Space"
        assert result[0].data["file_num"] == 4
        assert result[0].data["follower_num"] == 9
        assert result[0].data["user_name"] == "space-owner"
        assert result[0].error is None
        assert result[1].id == 2
        assert result[1].data == {}
        assert result[1].error.code == 18000
        assert result[2].id == 3
        assert result[2].data == {}
        assert result[2].error.code == 18040

    @pytest.mark.asyncio
    async def test_super_admin_read_shortcut_does_not_mark_space_subscribed(self, service):
        service.login_user.is_admin = lambda: True
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC, user_id=99, is_released=True)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_count_space_members',
            new_callable=AsyncMock,
            return_value=3,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock,
            return_value={1: 5},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.UserDao.aget_user',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(user_name='other-user'),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='owner',
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_space_info(1)

        assert result.user_role == UserRoleEnum.ADMIN
        assert result.subscription_status == SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED
        assert result.is_followed is False


class TestCreateSpace:

    @pytest.mark.asyncio
    async def test_create_rejects_duplicate_personal_space_name_in_same_scope(self, service):
        duplicate_space = _make_space(
            space_id=22,
            user_id=service.login_user.user_id,
        )
        created_space = _make_space(
            space_id=23,
            user_id=service.login_user.user_id,
        )

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_spaces_by_user',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.LLMService.get_workbench_llm',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(embedding_model=SimpleNamespace(id='embedding-1')),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_space_by_scope_name',
            new_callable=AsyncMock,
            return_value=duplicate_space,
            create=True,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.create_knowledge_base',
            return_value=created_space,
        ) as mock_create_knowledge_base, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_insert_member',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.acreate',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.tenant.domain.services.resource_share_service.ResourceShareService.share_on_create',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeAuditTelemetryService.audit_create_knowledge_space',
            new_callable=AsyncMock,
        ):
            with pytest.raises(Exception) as exc_info:
                await service.create_knowledge_space(name='重复空间')

        assert exc_info.value.__class__.__name__ == 'SpaceNameDuplicateError'
        mock_create_knowledge_base.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_allows_space_name_when_scope_has_no_duplicate(self, service):
        created_space = _make_space(
            space_id=23,
            user_id=service.login_user.user_id,
        )

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_spaces_by_user',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.LLMService.get_workbench_llm',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(embedding_model=SimpleNamespace(id='embedding-1')),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_space_by_scope_name',
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_get_by_scope_name, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.create_knowledge_base',
            return_value=created_space,
        ) as mock_create_knowledge_base, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_insert_member',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.acreate',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.tenant.domain.services.resource_share_service.ResourceShareService.share_on_create',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeAuditTelemetryService.audit_create_knowledge_space',
            new_callable=AsyncMock,
        ):
            result = await service.create_knowledge_space(name='同名但不同范围可用')

        assert result.id == 23
        mock_create_knowledge_base.assert_called_once()
        mock_get_by_scope_name.assert_awaited_once_with(
            tenant_id=service.login_user.tenant_id,
            level=KnowledgeSpaceLevelEnum.PERSONAL,
            owner_type=KnowledgeSpaceOwnerTypeEnum.USER,
            owner_id=service.login_user.user_id,
            name='同名但不同范围可用',
            exclude_id=None,
        )

    @pytest.mark.asyncio
    async def test_create_limit_count_excludes_department_spaces(self, service):
        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_spaces_by_user',
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_count, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.LLMService.get_workbench_llm',
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(WorkbenchEmbeddingError):
                await service.create_knowledge_space(name='Space')

        mock_count.assert_awaited_once_with(
            service.login_user.user_id,
            exclude_department_spaces=True,
        )


class TestDeleteSpace:

    @pytest.mark.asyncio
    async def test_uses_can_delete_permission_instead_of_creator_id(self, service):
        other_users_space = _make_space(user_id=999)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=other_users_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService._require_permission_id',
            new_callable=AsyncMock,
        ) as mock_require_permission_id, patch(
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

        mock_require_permission_id.assert_awaited_once_with('knowledge_space', 1, 'delete_space')
        mock_delete.assert_awaited_once_with(knowledge_id=1)
        mock_cleanup.assert_awaited_once_with([('folder', 201), ('knowledge_file', 202), ('knowledge_space', 1)])

    @pytest.mark.asyncio
    async def test_delete_space_enqueues_content_stat_cleanup(self, service):
        space = _make_space(space_id=1, user_id=999)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch.object(
            service, '_list_space_child_resources', new_callable=AsyncMock, return_value=[],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.asyncio.to_thread',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_delete_knowledge',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceTagLibraryDao.adelete_private_for_knowledge',
            new_callable=AsyncMock,
        ), patch.object(
            service, '_cleanup_resource_tuples', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.clean_space_member',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeAuditTelemetryService.audit_delete_knowledge_space',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeAuditTelemetryService.telemetry_delete_knowledge',
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceContentStat.enqueue_space_delete_stat_async',
            new_callable=AsyncMock,
        ) as mock_enqueue:
            await service.delete_space(1)

        mock_enqueue.assert_awaited_once_with(1)


class TestSpaceListings:

    @pytest.mark.asyncio
    async def test_get_my_created_spaces_excludes_department_bound_spaces(self, service):
        department_member = _make_member(
            user_id=service.login_user.user_id,
            user_role=UserRoleEnum.CREATOR,
            space_id=101,
        )
        normal_member = _make_member(
            user_id=service.login_user.user_id,
            user_role=UserRoleEnum.CREATOR,
            space_id=102,
        )

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_created_members',
            new_callable=AsyncMock,
            return_value=[department_member, normal_member],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_department_ids_by_space_ids',
            new_callable=AsyncMock,
            return_value={101: 10},
        ), patch.object(
            service, '_format_member_spaces',
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_format:
            await service.get_my_created_spaces()

        mock_format.assert_awaited_once_with([normal_member], 'update_time')

    @pytest.mark.asyncio
    async def test_get_my_followed_spaces_includes_direct_read_grants_without_membership(self, service):
        granted_space = _make_space(space_id=2, user_id=99, auth_type=AuthTypeEnum.PRIVATE)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_followed_members',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.list_accessible_ids',
            new_callable=AsyncMock,
            return_value=['2'],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
            new_callable=AsyncMock,
            return_value=[granted_space],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='owner',
        ), patch.object(
            service, '_get_effective_permission_ids', new_callable=AsyncMock,
            return_value={'view_space'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_my_followed_spaces()

        assert len(result) == 1
        assert result[0].id == 2
        assert result[0].user_role == UserRoleEnum.ADMIN
        assert result[0].subscription_status == SpaceSubscriptionStatusEnum.SUBSCRIBED
        assert result[0].is_followed is True

    @pytest.mark.asyncio
    async def test_get_my_followed_spaces_excludes_direct_grant_without_view_space(self, service):
        granted_space = _make_space(space_id=2, user_id=99, auth_type=AuthTypeEnum.PRIVATE)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_followed_members',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.list_accessible_ids',
            new_callable=AsyncMock,
            return_value=['2'],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
            new_callable=AsyncMock,
            return_value=[granted_space],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='can_read',
        ), patch.object(
            service, '_get_effective_permission_ids', new_callable=AsyncMock,
            return_value=set(),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_my_followed_spaces()

        assert result == []

    @pytest.mark.asyncio
    async def test_format_accessible_spaces_excludes_membership_without_required_permission_id(self, service):
        member_space = _make_space(space_id=2, user_id=99, auth_type=AuthTypeEnum.PRIVATE)
        member = _make_member(
            user_id=service.login_user.user_id,
            user_role=UserRoleEnum.MEMBER,
            space_id=2,
        )

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
            new_callable=AsyncMock,
            return_value=[member_space],
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value=set(),
        ) as mock_permission_ids:
            result = await service._format_accessible_spaces(
                [2],
                [member],
                required_permission_id='view_space',
            )

        assert result == []
        mock_permission_ids.assert_awaited_once_with('knowledge_space', 2)

    @pytest.mark.asyncio
    async def test_get_my_followed_spaces_excludes_spaces_created_by_current_user(self, service):
        owned_space = _make_space(space_id=4, user_id=service.login_user.user_id, auth_type=AuthTypeEnum.PRIVATE)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_followed_members',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.list_accessible_ids',
            new_callable=AsyncMock,
            return_value=['4'],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
            new_callable=AsyncMock,
            return_value=[owned_space],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_my_followed_spaces()

        assert result == []

    @pytest.mark.asyncio
    async def test_get_my_managed_spaces_includes_direct_manage_grants_without_membership(self, service):
        granted_space = _make_space(space_id=3, user_id=88, auth_type=AuthTypeEnum.PRIVATE)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_managed_members',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.list_accessible_ids',
            new_callable=AsyncMock,
            return_value=['3'],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids',
            new_callable=AsyncMock,
            return_value=[granted_space],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='can_manage',
        ), patch.object(
            service, '_get_effective_permission_ids', new_callable=AsyncMock,
            return_value={'manage_space_relation'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_my_managed_spaces()

        assert len(result) == 1
        assert result[0].id == 3
        assert result[0].user_role == UserRoleEnum.ADMIN
        assert result[0].subscription_status == SpaceSubscriptionStatusEnum.SUBSCRIBED


class TestKnowledgeSquareListing:

    @pytest.mark.asyncio
    async def test_marks_direct_can_read_grant_as_subscribed(self, service):
        public_space = _make_space(space_id=2, user_id=99, auth_type=AuthTypeEnum.PUBLIC, is_released=True)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_public_spaces_paginated',
            new_callable=AsyncMock,
            return_value=[(public_space, None, None, 7)],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_public_spaces',
            new_callable=AsyncMock,
            return_value=1,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.list_accessible_ids',
            new_callable=AsyncMock,
            return_value=['2'],
        ), patch.object(
            service,
            '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.UserDao.aget_user_by_ids',
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(user_id=99, user_name='owner', avatar='avatar.png')],
        ), patch(
            'bisheng.user.domain.services.user.UserService.get_avatar_share_link',
            new_callable=AsyncMock,
            return_value='avatar-link',
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock,
            return_value={2: 3},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_knowledge_square(page=1, page_size=20)

        assert result['total'] == 1
        assert len(result['data']) == 1
        assert result['data'][0].id == 2
        assert result['data'][0].subscription_status == SpaceSubscriptionStatusEnum.SUBSCRIBED
        assert result['data'][0].is_followed is True
        assert result['data'][0].is_pending is False

    @pytest.mark.asyncio
    async def test_does_not_mark_subscribed_without_view_space_permission_id(self, service):
        public_space = _make_space(space_id=2, user_id=99, auth_type=AuthTypeEnum.PUBLIC, is_released=True)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_public_spaces_paginated',
            new_callable=AsyncMock,
            return_value=[(public_space, None, None, 7)],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_public_spaces',
            new_callable=AsyncMock,
            return_value=1,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.list_accessible_ids',
            new_callable=AsyncMock,
            return_value=['2'],
        ), patch.object(
            service,
            '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value=set(),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.UserDao.aget_user_by_ids',
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(user_id=99, user_name='owner', avatar='avatar.png')],
        ), patch(
            'bisheng.user.domain.services.user.UserService.get_avatar_share_link',
            new_callable=AsyncMock,
            return_value='avatar-link',
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock,
            return_value={2: 3},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_knowledge_square(page=1, page_size=20)

        assert result['data'][0].subscription_status == SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED
        assert result['data'][0].is_followed is False

    @pytest.mark.asyncio
    async def test_super_admin_shortcut_does_not_mark_square_item_as_subscribed(self, service):
        service.login_user.is_admin = lambda: True
        public_space = _make_space(space_id=2, user_id=99, auth_type=AuthTypeEnum.PUBLIC, is_released=True)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_public_spaces_paginated',
            new_callable=AsyncMock,
            return_value=[(public_space, None, None, 7)],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_public_spaces',
            new_callable=AsyncMock,
            return_value=1,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.list_accessible_ids',
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_accessible_ids, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.UserDao.aget_user_by_ids',
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(user_id=99, user_name='owner', avatar='avatar.png')],
        ), patch(
            'bisheng.user.domain.services.user.UserService.get_avatar_share_link',
            new_callable=AsyncMock,
            return_value='avatar-link',
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch',
            new_callable=AsyncMock,
            return_value={2: 3},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await service.get_knowledge_square(page=1, page_size=20)

        assert result['data'][0].subscription_status == SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED
        assert result['data'][0].is_followed is False
        mock_accessible_ids.assert_not_awaited()


class TestManagePermissionBoundaries:

    @pytest.mark.asyncio
    async def test_get_space_members_requires_manage_permission(self, service):
        with patch.object(
            service, '_require_manage_permission', new_callable=AsyncMock,
        ) as mock_require_manage, patch.object(
            service, '_require_write_permission', new_callable=AsyncMock,
        ) as mock_require_write, patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ) as mock_require_permission_id, patch(
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
        mock_require_permission_id.assert_awaited_once_with('knowledge_space', 1, 'manage_space_relation')
        mock_require_manage.assert_not_awaited()
        mock_require_write.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_space_uses_edit_permission_when_auth_type_is_present(self, service):
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
        ) as mock_require_permission_id, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space',
            new_callable=AsyncMock,
            return_value=updated_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_members_by_space',
            new_callable=AsyncMock,
            return_value=[],
        ):
            await service.update_knowledge_space(1, auth_type=AuthTypeEnum.APPROVAL)

        mock_require_permission_id.assert_awaited_once_with('knowledge_space', 1, 'edit_space')
        mock_require_manage.assert_not_awaited()
        mock_require_write.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_space_without_auth_type_stays_on_write_permission(self, service):
        existing_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        updated_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        scope = SimpleNamespace(
            tenant_id=service.login_user.tenant_id,
            level=KnowledgeSpaceLevelEnum.PERSONAL,
            owner_type=KnowledgeSpaceOwnerTypeEnum.USER,
            owner_id=service.login_user.user_id,
        )

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
        ) as mock_require_permission_id, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id',
            new_callable=AsyncMock,
            return_value=scope,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_space_by_scope_name',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space',
            new_callable=AsyncMock,
            return_value=updated_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceContentStat.enqueue_space_rename_stat_async',
            new_callable=AsyncMock,
        ) as mock_enqueue:
            await service.update_knowledge_space(1, name='Renamed Space')

        mock_require_permission_id.assert_awaited_once_with('knowledge_space', 1, 'edit_space')
        mock_require_write.assert_not_awaited()
        mock_require_manage.assert_not_awaited()
        mock_enqueue.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_update_space_rejects_duplicate_name_in_same_scope(self, service):
        existing_space = _make_space(
            space_id=1,
            user_id=service.login_user.user_id,
        )
        existing_space.name = '原空间'
        duplicate_space = _make_space(
            space_id=2,
            user_id=service.login_user.user_id,
        )
        duplicate_space.name = '重复空间'
        scope = SimpleNamespace(
            tenant_id=service.login_user.tenant_id,
            level=KnowledgeSpaceLevelEnum.PERSONAL,
            owner_type=KnowledgeSpaceOwnerTypeEnum.USER,
            owner_id=service.login_user.user_id,
        )

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=existing_space,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id',
            new_callable=AsyncMock,
            return_value=scope,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_space_by_scope_name',
            new_callable=AsyncMock,
            return_value=duplicate_space,
            create=True,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space',
            new_callable=AsyncMock,
        ) as mock_update_space:
            with pytest.raises(Exception) as exc_info:
                await service.update_knowledge_space(1, name='重复空间')

        assert exc_info.value.__class__.__name__ == 'SpaceNameDuplicateError'
        mock_update_space.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_space_keeps_same_name_without_duplicate_lookup(self, service):
        existing_space = _make_space(
            space_id=1,
            user_id=service.login_user.user_id,
        )
        existing_space.name = '原空间'

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=existing_space,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_space_by_scope_name',
            new_callable=AsyncMock,
        ) as mock_get_by_scope_name, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space',
            new_callable=AsyncMock,
            return_value=existing_space,
        ) as mock_update_space:
            await service.update_knowledge_space(1, name='原空间')

        mock_get_by_scope_name.assert_not_awaited()
        mock_update_space.assert_awaited_once()


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
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space'},
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
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space'},
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
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space'},
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
    async def test_batch_delete_enqueues_direct_file_stat_cleanup(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        file_record = _make_file(file_id=42, knowledge_id=1)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch.object(
            service, '_require_read_permission', new_callable=AsyncMock,
        ), patch.object(
            service, '_get_file_for_action', new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ), patch.object(
            service, '_cleanup_resource_tuples', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceContentStat.enqueue_file_stat_async',
            new_callable=AsyncMock,
        ) as mock_enqueue:
            await service.batch_delete(1, [42], [])

        mock_enqueue.assert_awaited_once_with([42])

    @pytest.mark.asyncio
    async def test_batch_download_rejects_cross_space_file_ids(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        foreign_file = _make_file(file_id=51, knowledge_id=2)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space'},
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
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space'},
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
        ) as mock_require_permission_id, patch(
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
        mock_require_permission_id.assert_awaited_once_with('knowledge_space', 1, 'create_folder')
        parent_tuple = mock_batch_write.await_args.args[0][0]
        assert parent_tuple.user == 'knowledge_space:1'
        assert parent_tuple.relation == 'parent'
        assert parent_tuple.object == 'folder:71'
        mock_write_owner.assert_awaited_once_with(
            service.login_user.user_id,
            'folder',
            '71',
            enforce_fga_success=True,
        )

    @pytest.mark.asyncio
    async def test_add_folder_rolls_back_record_when_permission_initialization_fails(self, service):
        added_folder = _make_file(file_id=73, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')

        with patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.count_folder_by_name',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aadd_file',
            new_callable=AsyncMock,
            return_value=added_folder,
        ), patch.object(
            service,
            '_initialize_child_resource_permissions',
            new_callable=AsyncMock,
            side_effect=RuntimeError('permission init failed'),
        ), patch.object(
            service, '_cleanup_resource_tuples', new_callable=AsyncMock,
        ) as mock_cleanup_tuples, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ) as mock_delete_files, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ) as mock_update_space:
            with pytest.raises(RuntimeError, match='permission init failed'):
                await service.add_folder(1, 'folder')

        mock_cleanup_tuples.assert_awaited_once_with([('folder', 73)])
        mock_delete_files.assert_awaited_once_with([73])
        mock_update_space.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_subfolder_uses_parent_folder_create_permission(self, service):
        parent_folder = _make_file(
            file_id=70,
            knowledge_id=1,
            file_type=FileType.DIR.value,
            file_name='parent',
        )
        added_folder = _make_file(
            file_id=72,
            knowledge_id=1,
            file_type=FileType.DIR.value,
            file_name='child',
            file_level_path='/70',
            level=1,
        )

        with patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ) as mock_require_permission_id, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=parent_folder,
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
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            result = await service.add_folder(1, 'child', parent_id=70)

        assert result.id == 72
        mock_require_permission_id.assert_awaited_once_with('folder', 70, 'create_folder', space_id=1)
        parent_tuple = mock_batch_write.await_args.args[0][0]
        assert parent_tuple.user == 'folder:70'
        assert parent_tuple.relation == 'parent'
        assert parent_tuple.object == 'folder:72'

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
        ) as mock_require_permission_id, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.approval.domain.services.approval_service.ApprovalService.should_require_department_space_approval',
            new_callable=AsyncMock,
            return_value=False,
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
        mock_require_permission_id.assert_any_await('knowledge_space', 1, 'upload_file')
        parent_tuple = mock_batch_write.await_args.args[0][0]
        assert parent_tuple.user == 'knowledge_space:1'
        assert parent_tuple.relation == 'parent'
        assert parent_tuple.object == 'knowledge_file:81'
        mock_write_owner.assert_awaited_once_with(
            service.login_user.user_id,
            'knowledge_file',
            '81',
            enforce_fga_success=True,
        )

    @pytest.mark.asyncio
    async def test_add_file_rolls_back_created_record_when_upload_limit_exceeded(self, service):
        space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        added_file = _make_file(file_id=86, knowledge_id=1, file_name='large.txt')
        added_file.status = 5
        added_file.file_size = 6

        with patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size',
            new_callable=AsyncMock,
            return_value=5,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes',
            new_callable=AsyncMock,
            return_value=10,
        ), patch(
            'bisheng.approval.domain.services.approval_service.ApprovalService.should_require_department_space_approval',
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file',
            return_value=added_file,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.batch_write_tuples',
            new_callable=AsyncMock,
        ) as mock_batch_write, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
            new_callable=AsyncMock,
        ) as mock_write_owner, patch.object(
            service, '_cleanup_resource_tuples', new_callable=AsyncMock,
        ) as mock_cleanup_tuples, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ) as mock_delete_files, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.file_worker.parse_knowledge_file_celery.delay',
        ) as mock_parse, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ) as mock_update_space:
            with pytest.raises(SpaceFileSizeLimitError):
                await service.add_file(1, ['/tmp/large.txt'])

        mock_batch_write.assert_not_awaited()
        mock_write_owner.assert_not_awaited()
        mock_cleanup_tuples.assert_awaited_once_with([('knowledge_file', 86)])
        mock_delete_files.assert_awaited_once_with([86])
        mock_parse.assert_not_called()
        mock_update_space.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_file_blocks_and_rolls_back_when_tenant_storage_quota_exceeded(self, service):
        """Tenant-level storage cap must trip 19403 (independent of user-role cap).

        Bug 1 fix: previously add_file only compared the *user's* total upload
        against limit_bytes. With the same user upload size below the user-role
        cap but the target tenant chain near exhaustion, writes leaked through.
        """
        from bisheng.common.errcode.tenant_quota import TenantStorageQuotaExceededError

        space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        space.tenant_id = 7
        added_file = _make_file(file_id=91, knowledge_id=1, file_name='big.txt')
        added_file.status = 5
        added_file.file_size = 6

        with patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes',
            new_callable=AsyncMock,
            return_value=None,  # user-role unlimited; only tenant cap should bite
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_tenant_storage_remaining_bytes',
            new_callable=AsyncMock,
            return_value=5,  # 5 bytes remaining on the tenant chain
        ) as mock_remaining, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_tenant_storage_used_bytes',
            new_callable=AsyncMock,
            return_value=10,
        ) as mock_used, patch(
            'bisheng.approval.domain.services.approval_service.ApprovalService.should_require_department_space_approval',
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file',
            return_value=added_file,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.batch_write_tuples',
            new_callable=AsyncMock,
        ) as mock_batch_write, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
            new_callable=AsyncMock,
        ), patch.object(
            service, '_cleanup_resource_tuples', new_callable=AsyncMock,
        ) as mock_cleanup_tuples, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ) as mock_delete_files, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.file_worker.parse_knowledge_file_celery.delay',
        ) as mock_parse, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            with pytest.raises(TenantStorageQuotaExceededError) as exc_info:
                await service.add_file(1, ['/tmp/big.txt'])

        # Targeted the destination space's tenant_id, not login_user.tenant_id
        mock_remaining.assert_awaited_once_with(7)
        mock_used.assert_awaited_once_with(7)
        # Defense-in-depth: error code is 19403 with reason='tenant_limit'
        assert exc_info.value.Code == 19403
        assert exc_info.value.kwargs.get('reason') == 'tenant_limit'
        # Cleanup ran (rollback): the partially-written row was removed
        mock_cleanup_tuples.assert_awaited_once_with([('knowledge_file', 91)])
        mock_delete_files.assert_awaited_once_with([91])
        mock_parse.assert_not_called()
        mock_batch_write.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_file_admin_still_blocked_by_tenant_storage_quota(self, service):
        """Super admin upload must still be capped by the *target tenant*.

        Pre-fix: get_knowledge_space_upload_limit_bytes returned None for
        admins, and tenant-cap was only enforced inside that helper, so admins
        could write past a child tenant's storage_gb.
        """
        from bisheng.common.errcode.tenant_quota import TenantStorageQuotaExceededError

        admin_user = _make_login_user(user_id=1)
        admin_user.is_admin = lambda: True
        service.login_user = admin_user
        space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        space.tenant_id = 9

        # Tenant chain already exhausted → helper raises directly (mirrors
        # _apply_tenant_chain_cap behaviour).
        with patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_tenant_storage_remaining_bytes',
            new_callable=AsyncMock,
            side_effect=TenantStorageQuotaExceededError(
                msg='exhausted',
                used_gb=2,
                quota_gb=2,
                tenant_name='child-1',
                tenant_id=9,
                reason='tenant_limit',
            ),
        ) as mock_remaining, patch(
            'bisheng.approval.domain.services.approval_service.ApprovalService.should_require_department_space_approval',
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file',
        ) as mock_process:
            with pytest.raises(TenantStorageQuotaExceededError):
                await service.add_file(1, ['/tmp/anything.txt'])

        mock_remaining.assert_awaited_once_with(9)
        # Quota check fires before any file is processed.
        mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_file_requires_parent_tuple_write_success(self, service):
        space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        added_file = _make_file(file_id=84, knowledge_id=1, file_name='doc.txt')
        added_file.status = 5
        added_file.file_size = 1

        with patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.approval.domain.services.approval_service.ApprovalService.should_require_department_space_approval',
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file',
            return_value=added_file,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.batch_write_tuples',
            new_callable=AsyncMock,
            side_effect=RuntimeError('fga write failed'),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
            new_callable=AsyncMock,
        ) as mock_write_owner, patch.object(
            service, '_cleanup_resource_tuples', new_callable=AsyncMock,
        ) as mock_cleanup_tuples, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ) as mock_delete_files, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.file_worker.parse_knowledge_file_celery.delay',
        ) as mock_parse, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ) as mock_update_space:
            with pytest.raises(RuntimeError, match='fga write failed'):
                await service.add_file(1, ['/tmp/doc.txt'])

        mock_write_owner.assert_not_awaited()
        mock_cleanup_tuples.assert_awaited_once_with([('knowledge_file', 84)])
        mock_delete_files.assert_awaited_once_with([84])
        mock_parse.assert_not_called()
        mock_update_space.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_file_requires_owner_tuple_write_success(self, service):
        space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        added_file = _make_file(file_id=85, knowledge_id=1, file_name='doc.txt')
        added_file.status = 5
        added_file.file_size = 1

        with patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.approval.domain.services.approval_service.ApprovalService.should_require_department_space_approval',
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file',
            return_value=added_file,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.batch_write_tuples',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
            new_callable=AsyncMock,
            side_effect=RuntimeError('owner write failed'),
        ), patch.object(
            service, '_cleanup_resource_tuples', new_callable=AsyncMock,
        ) as mock_cleanup_tuples, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ) as mock_delete_files, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.file_worker.parse_knowledge_file_celery.delay',
        ) as mock_parse, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ) as mock_update_space:
            with pytest.raises(RuntimeError, match='owner write failed'):
                await service.add_file(1, ['/tmp/doc.txt'])

        mock_cleanup_tuples.assert_awaited_once_with([('knowledge_file', 85)])
        mock_delete_files.assert_awaited_once_with([85])
        mock_parse.assert_not_called()
        mock_update_space.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_file_uses_parent_folder_upload_permission(self, service):
        with patch.object(
            service,
            '_require_permission_id',
            new_callable=AsyncMock,
            side_effect=SpacePermissionDeniedError(),
        ) as mock_require_permission_id, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
        ) as mock_query_space:
            with pytest.raises(SpacePermissionDeniedError):
                await service.add_file(1, ['/tmp/doc.txt'], parent_id=70)

        mock_require_permission_id.assert_awaited_once_with('folder', 70, 'upload_file', space_id=1)
        mock_query_space.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_file_department_space_upload_skips_approval_and_processes_directly(self, service):
        space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        added_file = _make_file(file_id=83, knowledge_id=1, file_name='doc.txt')
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
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file',
            return_value=added_file,
        ) as mock_process_one_file, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.batch_write_tuples',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.approval.domain.services.approval_service.ApprovalService.create_department_space_upload_request',
            new_callable=AsyncMock,
        ) as mock_create_request:
            result = await service.add_file(1, ['/tmp/doc.txt'])

        assert result[0].id == 83
        mock_create_request.assert_not_called()
        mock_process_one_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_file_department_space_upload_no_longer_needs_bypass_logic(self, service):
        space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        added_file = _make_file(file_id=83, knowledge_id=1, file_name='doc.txt')
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
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file',
            return_value=added_file,
        ) as mock_process_one_file, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.batch_write_tuples',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            result = await service.add_file(1, ['/tmp/doc.txt'])

        assert result[0].id == 83
        mock_process_one_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_file_cleans_knowledge_file_tuples(self, service):
        file_record = _make_file(file_id=82, knowledge_id=1)

        with patch.object(
            service, '_get_file_for_action', new_callable=AsyncMock,
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
    async def test_delete_file_enqueues_content_stat_cleanup(self, service):
        file_record = _make_file(file_id=82, knowledge_id=1)

        with patch.object(
            service, '_get_file_for_action', new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=_make_space(space_id=1),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ), patch.object(
            service, '_cleanup_resource_tuples', new_callable=AsyncMock,
        ), patch.object(
            service, 'update_folder_update_time', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceContentStat.enqueue_file_stat_async',
            new_callable=AsyncMock,
        ) as mock_enqueue:
            await service.delete_file(82)

        mock_enqueue.assert_awaited_once_with([82])

    @pytest.mark.asyncio
    async def test_delete_folder_cleans_descendant_resource_tuples(self, service):
        folder = _make_file(file_id=91, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')
        child_folder = _make_file(file_id=92, knowledge_id=1, file_type=FileType.DIR.value, file_name='nested')
        child_file = _make_file(file_id=93, knowledge_id=1, file_type=FileType.FILE.value, file_name='doc.txt')

        with patch.object(
            service, '_get_folder_for_action', new_callable=AsyncMock,
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
    async def test_delete_folder_enqueues_descendant_file_stat_cleanup(self, service):
        folder = _make_file(file_id=91, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')
        child_file = _make_file(file_id=93, knowledge_id=1, file_type=FileType.FILE.value, file_name='doc.txt')

        with patch.object(
            service, '_get_folder_for_action', new_callable=AsyncMock,
            return_value=folder,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=_make_space(space_id=1),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_children_by_prefix',
            new_callable=AsyncMock,
            return_value=[child_file],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ), patch.object(
            service, '_cleanup_resource_tuples', new_callable=AsyncMock,
        ), patch.object(
            service, 'update_folder_update_time', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceContentStat.enqueue_file_stat_async',
            new_callable=AsyncMock,
        ) as mock_enqueue:
            await service.delete_folder(1, 91)

        mock_enqueue.assert_awaited_once_with([93])

    @pytest.mark.asyncio
    async def test_delete_folder_uses_delete_folder_permission(self, service):
        folder = _make_file(file_id=94, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')

        with patch.object(
            service, '_get_folder_for_action', new_callable=AsyncMock,
            return_value=folder,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ) as mock_require_permission_id, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_children_by_prefix',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.delete_resource_tuples',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            await service.delete_folder(1, 94)

        mock_require_permission_id.assert_awaited_once_with('folder', 94, 'delete_folder', space_id=1)

    @pytest.mark.asyncio
    async def test_delete_folder_requires_descendant_delete_permissions(self, service):
        folder = _make_file(file_id=95, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')
        child_folder = _make_file(file_id=96, knowledge_id=1, file_type=FileType.DIR.value, file_name='nested')
        child_file = _make_file(file_id=97, knowledge_id=1, file_type=FileType.FILE.value, file_name='doc.txt')

        async def require_permission(resource_type, resource_id, permission_id, **kwargs):
            if (resource_type, resource_id, permission_id) == ('knowledge_file', 97, 'delete_file'):
                raise SpacePermissionDeniedError()
            return None

        with patch.object(
            service, '_get_folder_for_action', new_callable=AsyncMock,
            return_value=folder,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
            side_effect=require_permission,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_children_by_prefix',
            new_callable=AsyncMock,
            return_value=[child_folder, child_file],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ) as mock_delete_batch, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.delete_resource_tuples',
            new_callable=AsyncMock,
        ):
            with pytest.raises(SpacePermissionDeniedError):
                await service.delete_folder(1, 95)

        mock_delete_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rename_folder_uses_rename_folder_permission(self, service):
        folder = _make_file(file_id=98, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')

        query_mock = AsyncMock(return_value=folder)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            query_mock,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ) as mock_require_permission_id, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space'},
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
            await service.rename_folder(98, 'renamed-folder')

        mock_require_permission_id.assert_awaited_once_with('folder', 98, 'rename_folder', space_id=1)

    @pytest.mark.asyncio
    async def test_delete_file_uses_delete_file_permission(self, service):
        file_record = _make_file(file_id=99, knowledge_id=1)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ) as mock_require_permission_id, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.delete_resource_tuples',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            await service.delete_file(99)

        mock_require_permission_id.assert_awaited_once_with('knowledge_file', 99, 'delete_file', space_id=1)

    @pytest.mark.asyncio
    async def test_rename_file_enqueues_content_stat_refresh(self, service):
        file_record = _make_file(file_id=100, knowledge_id=1, file_name='old.txt')
        updated_file = _make_file(file_id=100, knowledge_id=1, file_name='new.txt')
        updated_file.status = 2

        with patch.object(
            service, '_get_file_for_action', new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=_make_space(space_id=1),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.count_file_by_name',
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_update',
            new_callable=AsyncMock,
            return_value=updated_file,
        ), patch.object(
            service, 'update_folder_update_time', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceContentStat.enqueue_file_stat_async',
            new_callable=AsyncMock,
        ) as mock_enqueue:
            await service.rename_file(100, 'new.txt')

        mock_enqueue.assert_awaited_once_with([100])

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
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space', 'view_file'},
        ) as mock_effective, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.get_file_share_url',
            return_value=('original', 'preview'),
        ):
            result = await service.get_file_preview(96)

        assert result['original_url'] == 'original'
        assert ('knowledge_file', 96) in [
            (call.args[0], call.args[1]) for call in mock_effective.await_args_list
        ]

    @pytest.mark.asyncio
    async def test_get_file_preview_schedules_success_telemetry_without_changing_response(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        file_record = _make_file(file_id=196, knowledge_id=1)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space', 'view_file'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.get_file_share_url',
            return_value=('original', 'preview'),
        ), patch.object(
            service, '_log_file_preview_success',
            new_callable=AsyncMock,
            create=True,
        ) as mock_log, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.asyncio.create_task',
        ) as mock_create_task:
            result = await service.get_file_preview(196)

        assert result == {"original_url": "original", "preview_url": "preview"}
        mock_log.assert_called_once_with(file_record)
        mock_create_task.assert_called_once()
        scheduled = mock_create_task.call_args.args[0]
        assert inspect.iscoroutine(scheduled)
        scheduled.close()

    @pytest.mark.asyncio
    async def test_get_file_preview_denied_without_view_file_permission(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        file_record = _make_file(file_id=97, knowledge_id=1)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.get_file_share_url',
            return_value=('original', 'preview'),
        ) as mock_share_url:
            with pytest.raises(SpacePermissionDeniedError):
                await service.get_file_preview(97)

        mock_share_url.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_file_download_denied_without_download_file_permission(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        file_record = _make_file(file_id=98, knowledge_id=1)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'view_space', 'view_file'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.get_file_share_url',
            return_value=('original', 'preview'),
        ) as mock_share_url:
            with pytest.raises(SpacePermissionDeniedError):
                await service.get_file_download(98)

        mock_share_url.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_file_download_uses_download_file_permission(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        file_record = _make_file(file_id=99, knowledge_id=1)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            return_value={'download_file'},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.get_file_share_url',
            return_value=('original', 'preview'),
        ):
            result = await service.get_file_download(99)

        assert result['original_url'] == 'original'

    @pytest.mark.asyncio
    async def test_list_space_children_filters_each_child_by_view_permission(self, service):
        folder = _make_file(file_id=201, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')
        file_record = _make_file(file_id=202, knowledge_id=1, file_type=FileType.FILE.value, file_name='file.txt')

        async def fake_effective_permissions(object_type, object_id, **kwargs):
            if object_type == 'folder' and object_id == 201:
                return set()
            if object_type == 'knowledge_file' and object_id == 202:
                return {'view_file'}
            return {'view_space'}

        with patch.object(
            service, '_require_read_permission', new_callable=AsyncMock,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.async_list_children',
            new_callable=AsyncMock,
            return_value=[folder, file_record],
        ), patch.object(
            service, '_get_effective_permission_ids',
            new_callable=AsyncMock,
            side_effect=fake_effective_permissions,
        ), patch.object(
            service, '_handle_file_folder_extra_info',
            new_callable=AsyncMock,
            side_effect=lambda items: [{'id': item.id} for item in items],
        ):
            result = await service.list_space_children(1, page=1, page_size=20)

        assert result['total'] == 1
        assert result['data'] == [{'id': 202}]

    @pytest.mark.asyncio
    async def test_public_subscribe_updates_membership_and_syncs_rebac_tuple(self, service):
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
        ), patch.object(
            service.__class__,
            'sync_direct_space_user_permissions',
            new_callable=AsyncMock,
        ) as mock_sync_permissions:
            result = await service.subscribe_space(1)

        assert result['status'] == 'subscribed'
        mock_sync_permissions.assert_awaited_once()
        assert mock_sync_permissions.await_args.args[:3] == (1, service.login_user.user_id, UserRoleEnum.MEMBER)
        assert mock_sync_permissions.await_args.kwargs['is_active'] is True

    @pytest.mark.asyncio
    async def test_public_to_approval_does_not_sync_member_tuples(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        approval_space = _make_space(auth_type=AuthTypeEnum.APPROVAL)

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
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            await service.update_knowledge_space(1, auth_type=AuthTypeEnum.APPROVAL)

        mock_authorize.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_public_to_private_cleans_members_and_permissions(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        private_space = _make_space(auth_type=AuthTypeEnum.PRIVATE)
        child_resources = [('folder', 11), ('knowledge_file', 12)]

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
            return_value=private_space,
        ), patch.object(
            service,
            '_list_space_child_resources',
            new_callable=AsyncMock,
            return_value=child_resources,
        ) as mock_list_children, patch.object(
            service.__class__,
            'clear_space_authorization_for_private',
            new_callable=AsyncMock,
        ) as mock_clear_permissions, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_delete_non_creator_members',
            new_callable=AsyncMock,
        ) as mock_delete_members:
            await service.update_knowledge_space(1, auth_type=AuthTypeEnum.PRIVATE)

        mock_list_children.assert_awaited_once_with(1)
        mock_clear_permissions.assert_awaited_once_with(
            space=private_space,
            child_resources=child_resources,
        )
        mock_delete_members.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_approval_to_public_activates_pending_members_and_syncs_rebac_tuple(self, service):
        approval_space = _make_space(auth_type=AuthTypeEnum.APPROVAL)
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        pending_member = _make_member(user_id=12, status=MembershipStatusEnum.PENDING)

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
            return_value=[pending_member],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.update',
            new_callable=AsyncMock,
        ) as mock_update_member, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_delete_rejected_members',
            new_callable=AsyncMock,
        ) as mock_delete_rejected, patch.object(
            service.__class__,
            'sync_direct_space_user_permissions',
            new_callable=AsyncMock,
        ) as mock_sync_permissions:
            await service.update_knowledge_space(1, auth_type=AuthTypeEnum.PUBLIC)

        assert pending_member.status == MembershipStatusEnum.ACTIVE
        mock_update_member.assert_awaited_once()
        mock_delete_rejected.assert_awaited_once_with(1)
        mock_sync_permissions.assert_awaited_once_with(
            1,
            pending_member.user_id,
            pending_member.user_role,
            is_active=True,
        )

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
    async def test_unsubscribe_space_without_direct_grant_only_removes_membership(self, service):
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
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            result = await service.unsubscribe_space(1)

        assert result is True
        mock_authorize.assert_not_awaited()
        mock_save_bindings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unsubscribe_space_revokes_direct_rebac_binding(self, service):
        public_space = _make_space(auth_type=AuthTypeEnum.PUBLIC, user_id=99)
        active_member = _make_member(user_id=service.login_user.user_id)
        stale_binding = {
            'key': 'knowledge_space:1:user:7:viewer:none',
            'resource_type': 'knowledge_space',
            'resource_id': '1',
            'subject_type': 'user',
            'subject_id': service.login_user.user_id,
            'relation': 'viewer',
            'include_children': None,
            'model_id': 'custom_viewer',
        }
        other_binding = {
            'key': 'knowledge_space:1:user:88:viewer:none',
            'resource_type': 'knowledge_space',
            'resource_id': '1',
            'subject_type': 'user',
            'subject_id': 88,
            'relation': 'viewer',
            'include_children': None,
            'model_id': 'custom_viewer',
        }

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
        ) as mock_delete_member, patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[stale_binding, other_binding],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            result = await service.unsubscribe_space(1)

        assert result is True
        mock_delete_member.assert_awaited_once_with(1, service.login_user.user_id)
        mock_authorize.assert_awaited_once()
        kwargs = mock_authorize.await_args.kwargs
        assert kwargs['object_type'] == 'knowledge_space'
        assert kwargs['object_id'] == '1'
        assert kwargs['enforce_fga_success'] is True
        assert len(kwargs['revokes']) == 1
        assert kwargs['revokes'][0].subject_type == 'user'
        assert kwargs['revokes'][0].subject_id == service.login_user.user_id
        assert kwargs['revokes'][0].relation == 'viewer'
        mock_save_bindings.assert_awaited_once_with([other_binding])

    @pytest.mark.asyncio
    async def test_remove_member_without_direct_grant_only_removes_membership(self, service):
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
        ) as mock_delete_member, patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            result = await service.remove_member(SimpleNamespace(space_id=1, user_id=88))

        assert result is True
        mock_delete_member.assert_awaited_once_with(space_id=1, user_id=88)
        mock_authorize.assert_not_awaited()
        mock_save_bindings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_remove_member_revokes_direct_rebac_binding(self, service):
        target_member = _make_member(user_id=88)
        target_binding = {
            'key': 'knowledge_space:1:user:88:manager:none',
            'resource_type': 'knowledge_space',
            'resource_id': '1',
            'subject_type': 'user',
            'subject_id': 88,
            'relation': 'manager',
            'include_children': None,
            'model_id': 'custom_manager',
        }

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
        ) as mock_delete_member, patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[target_binding],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            result = await service.remove_member(SimpleNamespace(space_id=1, user_id=88))

        assert result is True
        mock_delete_member.assert_awaited_once_with(space_id=1, user_id=88)
        mock_authorize.assert_awaited_once()
        kwargs = mock_authorize.await_args.kwargs
        assert kwargs['object_type'] == 'knowledge_space'
        assert kwargs['object_id'] == '1'
        assert kwargs['enforce_fga_success'] is True
        assert len(kwargs['revokes']) == 1
        assert kwargs['revokes'][0].subject_id == 88
        assert kwargs['revokes'][0].relation == 'manager'
        mock_save_bindings.assert_awaited_once_with([])

    @pytest.mark.asyncio
    async def test_add_space_tag_uses_edit_space_permission(self, service):
        with patch.object(
            service, '_require_write_permission', new_callable=AsyncMock,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ) as mock_require_permission_id, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.TagDao.get_tags_by_business',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.TagDao.ainsert_tag',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=1, name='tag'),
        ):
            await service.add_space_tag(1, 'tag')

        mock_require_permission_id.assert_awaited_once_with('knowledge_space', 1, 'edit_space')

    @pytest.mark.asyncio
    async def test_update_file_tags_uses_edit_permission(self, service):
        file_record = _make_file(file_id=123, knowledge_id=1)

        with patch.object(
            service, '_get_file_for_action', new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
        ) as mock_require_permission_id, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aupdate_resource_tags',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            await service.update_file_tags(1, 123, [1, 2])

        mock_require_permission_id.assert_awaited_once_with('knowledge_file', 123, 'rename_file', space_id=1)

    @pytest.mark.asyncio
    async def test_retry_space_files_relies_on_edit_permission_only(self, service):
        space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        file_record = _make_file(file_id=124, knowledge_id=1)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch.object(
            service, '_require_read_permission', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids',
            new_callable=AsyncMock,
            return_value=[file_record],
        ), patch.object(
            service, '_require_resource_permission', new_callable=AsyncMock,
        ) as mock_require_resource_permission, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ):
            await service.retry_space_files(1, {'file_objs': [{'id': 124}]})

        mock_require_resource_permission.assert_awaited_once_with('can_edit', 'knowledge_file', 124)

    @pytest.mark.asyncio
    async def test_batch_retry_failed_files_enqueues_waiting_file_stats(self, service):
        space = _make_space(auth_type=AuthTypeEnum.PUBLIC)
        file_record = _make_file(file_id=126, knowledge_id=1)
        file_record.status = KnowledgeFileStatus.FAILED.value

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch.object(
            service, '_require_read_permission', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids',
            new_callable=AsyncMock,
            return_value=[file_record],
        ), patch.object(
            service, '_require_resource_permission', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aupdate_file_status',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id',
            new_callable=AsyncMock,
        ), patch.object(
            service, 'update_folder_update_time', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceContentStat.enqueue_file_stat_async',
            new_callable=AsyncMock,
        ) as mock_enqueue:
            await service.batch_retry_failed_files(1, [126])

        mock_enqueue.assert_awaited_once_with([126])


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
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=None,
        ):
            permission_ids = await service._get_effective_permission_ids(
                'knowledge_file',
                120,
                space_id=1,
            )

        assert permission_ids == {'view_file'}

    @pytest.mark.asyncio
    async def test_child_direct_binding_overrides_inherited_space_permissions(self, service):
        file_record = _make_file(file_id=121, knowledge_id=1)
        private_space = _make_space(space_id=1, auth_type=AuthTypeEnum.PRIVATE)
        fake_fga = _FakeReadTuplesFGA({
            'knowledge_file:121': [
                {'user': 'user:7', 'relation': 'viewer', 'object': 'knowledge_file:121'},
            ],
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
            return_value=[
                {
                    'resource_type': 'knowledge_file',
                    'resource_id': '121',
                    'subject_type': 'user',
                    'subject_id': 7,
                    'relation': 'viewer',
                    'model_id': 'file_download_only',
                    'include_children': None,
                },
                {
                    'resource_type': 'knowledge_space',
                    'resource_id': '1',
                    'subject_type': 'user',
                    'subject_id': 7,
                    'relation': 'viewer',
                    'model_id': 'space_viewer',
                    'include_children': None,
                },
            ],
        ), patch.object(
            service, '_get_binding_department_paths', new_callable=AsyncMock,
            return_value={},
        ), patch.object(
            service, '_get_relation_models_map', new_callable=AsyncMock,
            return_value={
                'file_download_only': {
                    'id': 'file_download_only',
                    'relation': 'viewer',
                    'permissions': ['download_file'],
                    'is_system': False,
                },
                'space_viewer': {
                    'id': 'space_viewer',
                    'relation': 'viewer',
                    'permissions': ['view_file'],
                    'is_system': False,
                },
            },
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService._get_fga',
            return_value=fake_fga,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_implicit_permission_level',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=_make_member(user_id=service.login_user.user_id),
        ):
            permission_ids = await service._get_effective_permission_ids(
                'knowledge_file',
                121,
                space_id=1,
            )

        assert permission_ids == {'download_file'}
        assert 'view_file' not in permission_ids

    @pytest.mark.asyncio
    async def test_unreleased_public_space_without_rebac_relation_has_no_default_permission_ids(self, service):
        public_space = _make_space(space_id=1, auth_type=AuthTypeEnum.PUBLIC)
        fake_fga = _FakeReadTuplesFGA({'knowledge_space:1': []})

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch.object(
            service, '_get_current_user_subject_strings', new_callable=AsyncMock,
            return_value={'user:7'},
        ), patch.object(
            service, '_get_relation_bindings', new_callable=AsyncMock,
            return_value=[],
        ), patch.object(
            service, '_get_binding_department_paths', new_callable=AsyncMock,
            return_value={},
        ), patch.object(
            service, '_get_relation_models_map', new_callable=AsyncMock,
            return_value={},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService._get_fga',
            return_value=fake_fga,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=None,
        ):
            permission_ids = await service._get_effective_permission_ids(
                'knowledge_space',
                1,
            )

        assert permission_ids == set()

    @pytest.mark.asyncio
    async def test_released_public_space_grants_viewer_permissions_without_joining(self, service):
        public_space = _make_space(space_id=1, auth_type=AuthTypeEnum.PUBLIC, is_released=True)
        file_record = _make_file(file_id=120, knowledge_id=1)
        fake_fga = _FakeReadTuplesFGA({
            'knowledge_file:120': [],
            'knowledge_space:1': [],
        })

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_get_current_user_subject_strings', new_callable=AsyncMock,
            return_value={'user:7'},
        ), patch.object(
            service, '_get_relation_bindings', new_callable=AsyncMock,
            return_value=[],
        ), patch.object(
            service, '_get_binding_department_paths', new_callable=AsyncMock,
            return_value={},
        ), patch.object(
            service, '_get_relation_models_map', new_callable=AsyncMock,
            return_value={},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService._get_fga',
            return_value=fake_fga,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_implicit_permission_level',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=None,
        ):
            permission_ids = await service._get_effective_permission_ids(
                'knowledge_file',
                120,
                space_id=1,
            )

        assert 'view_space' in permission_ids
        assert 'view_folder' in permission_ids
        assert 'view_file' in permission_ids
        assert 'download_file' in permission_ids
        assert 'edit_space' not in permission_ids

    @pytest.mark.asyncio
    async def test_unbound_user_viewer_tuple_is_ignored_as_legacy_subscription(self, service):
        private_space = _make_space(space_id=1, auth_type=AuthTypeEnum.PRIVATE)
        fake_fga = _FakeReadTuplesFGA({
            'knowledge_space:1': [
                {'user': 'user:7', 'relation': 'viewer', 'object': 'knowledge_space:1'},
            ],
        })

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=private_space,
        ), patch.object(
            service, '_get_current_user_subject_strings', new_callable=AsyncMock,
            return_value={'user:7'},
        ), patch.object(
            service, '_get_relation_bindings', new_callable=AsyncMock,
            return_value=[],
        ), patch.object(
            service, '_get_binding_department_paths', new_callable=AsyncMock,
            return_value={},
        ), patch.object(
            service, '_get_relation_models_map', new_callable=AsyncMock,
            return_value={},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService._get_fga',
            return_value=fake_fga,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_implicit_permission_level',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='can_read',
        ) as mock_get_level, patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=None,
        ):
            permission_ids = await service._get_effective_permission_ids(
                'knowledge_space',
                1,
            )

        assert permission_ids == set()
        mock_get_level.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_active_member_gets_viewer_permissions_without_rebac_tuple(self, service):
        public_space = _make_space(space_id=1, auth_type=AuthTypeEnum.PUBLIC)
        fake_fga = _FakeReadTuplesFGA({'knowledge_space:1': []})

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch.object(
            service, '_get_current_user_subject_strings', new_callable=AsyncMock,
            return_value={'user:7'},
        ), patch.object(
            service, '_get_relation_bindings', new_callable=AsyncMock,
            return_value=[],
        ), patch.object(
            service, '_get_binding_department_paths', new_callable=AsyncMock,
            return_value={},
        ), patch.object(
            service, '_get_relation_models_map', new_callable=AsyncMock,
            return_value={},
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService._get_fga',
            return_value=fake_fga,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_implicit_permission_level',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
            new_callable=AsyncMock,
            return_value=_make_member(user_id=service.login_user.user_id),
        ):
            permission_ids = await service._get_effective_permission_ids(
                'knowledge_space',
                1,
            )

        assert 'view_space' in permission_ids
        assert 'view_file' in permission_ids
        assert 'edit_space' not in permission_ids

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
    async def test_batch_download_checks_download_permission_without_read_gate(self, service):
        file_record = _make_file(file_id=121, knowledge_id=1)
        public_space = _make_space(space_id=1, auth_type=AuthTypeEnum.PUBLIC)

        async def deny_download(resource_type, resource_id, permission_id, **kwargs):
            assert (resource_type, resource_id, permission_id) == ('knowledge_file', 121, 'download_file')
            raise SpacePermissionDeniedError()

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=file_record,
        ), patch.object(
            service, '_require_read_permission', new_callable=AsyncMock,
            side_effect=AssertionError('download should not require read/view permission'),
        ) as mock_require_read, patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
            side_effect=deny_download,
        ) as mock_require_permission_id:
            with pytest.raises(SpacePermissionDeniedError):
                await service.batch_download(1, [121], [])

        mock_require_read.assert_not_awaited()
        mock_require_permission_id.assert_awaited_once_with(
            'knowledge_file', 121, 'download_file', space_id=1,
        )

    @pytest.mark.asyncio
    async def test_batch_download_denied_without_download_folder_permission(self, service):
        folder = _make_file(file_id=122, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')
        public_space = _make_space(space_id=1, auth_type=AuthTypeEnum.PUBLIC)

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=folder,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ), patch.object(
            service, '_get_effective_permission_ids', new_callable=AsyncMock,
            return_value={'view_folder'},
        ):
            with pytest.raises(SpacePermissionDeniedError):
                await service.batch_download(1, [], [122])

    @pytest.mark.asyncio
    async def test_batch_download_requires_descendant_download_permissions(self, service):
        folder = _make_file(file_id=123, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')
        child_file = _make_file(file_id=124, knowledge_id=1, file_type=FileType.FILE.value, file_name='doc.txt')
        public_space = _make_space(space_id=1, auth_type=AuthTypeEnum.PUBLIC)

        async def require_permission(resource_type, resource_id, permission_id, **kwargs):
            if (resource_type, resource_id, permission_id) == ('knowledge_file', 124, 'download_file'):
                raise SpacePermissionDeniedError()
            return None

        with patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=public_space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id',
            new_callable=AsyncMock,
            return_value=folder,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ), patch.object(
            service, '_get_effective_permission_ids', new_callable=AsyncMock,
            return_value={'view_folder', 'download_folder'},
        ), patch.object(
            service, '_require_permission_id', new_callable=AsyncMock,
            side_effect=require_permission,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_children_by_prefix',
            new_callable=AsyncMock,
            return_value=[child_file],
        ):
            with pytest.raises(SpacePermissionDeniedError):
                await service.batch_download(1, [], [123])

    @pytest.mark.asyncio
    async def test_delete_file_denied_without_delete_file_permission(self, service):
        file_record = _make_file(file_id=125, knowledge_id=1)
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
                await service.delete_file(125)

        mock_delete_batch.assert_not_awaited()
