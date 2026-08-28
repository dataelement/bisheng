"""标签审核范围：独立管理员（排除仅所有者）+ 上传人科室下科室库管理员并集。"""

import importlib
import sys
import types
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

base_service_stub = types.ModuleType("bisheng.common.services.base")


class _BaseService:
    pass


base_service_stub.BaseService = _BaseService
sys.modules["bisheng.common.services.base"] = base_service_stub
workstation_tags_service = importlib.reload(
    importlib.import_module("bisheng.workstation.domain.services.workstation_tags_service")
)

from bisheng.common.errcode.tag import (
    ReviewTagPermissionDeniedError,
    ReviewTagSpaceOutOfScopeError,
)
from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.database.models.review_tags import ApproveOrRejectEnum, TagResourceTypeEnum
from bisheng.workstation.domain.schemas.review_tags_schema import ApproveOrRejectRequest, ReviewTagScope

WorkStationTagsService = workstation_tags_service.WorkStationTagsService
resolve_review_tag_scope_for_user = workstation_tags_service.resolve_review_tag_scope_for_user
user_can_review_tags = workstation_tags_service.user_can_review_tags


def _build_service(*, is_global_super: bool = False) -> WorkStationTagsService:
    session = AsyncMock()
    session.commit = AsyncMock()
    return WorkStationTagsService(
        request=MagicMock(),
        session=session,
        login_user=SimpleNamespace(
            user_id=9,
            tenant_id=1,
            is_global_super=is_global_super,
            is_admin=lambda: False,
            has_tenant_admin=AsyncMock(return_value=False),
            user_name="reviewer",
        ),
        review_tags_repository=AsyncMock(),
    )


def _login_user():
    return SimpleNamespace(
        user_id=9,
        tenant_id=1,
        is_global_super=False,
        is_admin=lambda: False,
        has_tenant_admin=AsyncMock(return_value=False),
    )


def _accessible(*, can_manage=None, owner=None):
    async def _impl(*, relation, **kwargs):
        if relation == "owner":
            return list(owner or [])
        return list(can_manage or [])

    return AsyncMock(side_effect=_impl)


@contextmanager
def _scope_patches(
    *,
    can_manage=None,
    owner=None,
    levels=None,
    members=None,
    clinic_bindings=None,
    creator=None,
    fga=None,
):
    """解析审核范围时用到的 FGA / 成员表 / 科室绑定桩。"""
    patches = (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.list_accessible_ids",
            new=_accessible(can_manage=can_manage, owner=owner),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._get_resource_creator",
            new=AsyncMock(return_value=creator),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._aget_fga",
            new=AsyncMock(return_value=fga),
        ),
        patch(
            "bisheng.knowledge.domain.models.knowledge_space_scope.KnowledgeSpaceScopeDao.aget_map_by_space_ids",
            new=AsyncMock(return_value=levels or {}),
        ),
        patch(
            "bisheng.common.models.space_channel_member.SpaceChannelMemberDao.async_get_user_managed_members",
            new=AsyncMock(return_value=members or []),
        ),
        patch(
            "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_ids",
            new=AsyncMock(return_value=clinic_bindings or []),
        ),
    )
    with ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        yield


@pytest.mark.asyncio
async def test_resolve_review_tag_scope_denies_ordinary_user():
    login_user = _login_user()
    with _scope_patches():
        with pytest.raises(ReviewTagPermissionDeniedError):
            await resolve_review_tag_scope_for_user(login_user)


@pytest.mark.asyncio
async def test_resolve_review_tag_scope_for_space_admin_role_libraries_only():
    login_user = _login_user()
    with _scope_patches(
        can_manage=["100", "200", "300"],
        owner=[],
        levels={
            100: SimpleNamespace(level="public"),
            200: SimpleNamespace(level="team_ks"),
            300: SimpleNamespace(level="team"),
        },
        clinic_bindings=[SimpleNamespace(department_id=55)],
    ):
        scope = await resolve_review_tag_scope_for_user(login_user)

    assert scope.full_tenant is False
    assert scope.role_managed_space_ids == frozenset({100, 200})
    assert scope.clinic_admin_department_ids == frozenset({55})


@pytest.mark.asyncio
async def test_resolve_review_tag_scope_falls_back_to_member_table_admin_only():
    login_user = _login_user()
    with _scope_patches(
        can_manage=[],
        members=[
            SimpleNamespace(business_id="100", user_role=UserRoleEnum.ADMIN),
            SimpleNamespace(business_id="200", user_role=UserRoleEnum.CREATOR),
        ],
        levels={
            100: SimpleNamespace(level="department"),
            200: SimpleNamespace(level="public"),
        },
    ):
        scope = await resolve_review_tag_scope_for_user(login_user)

    assert scope.role_managed_space_ids == frozenset({100})
    assert 200 not in scope.role_managed_space_ids


@pytest.mark.asyncio
async def test_owner_only_cannot_review():
    login_user = _login_user()
    with _scope_patches(
        can_manage=["100"],
        owner=["100"],
        levels={100: SimpleNamespace(level="public")},
    ):
        with pytest.raises(ReviewTagPermissionDeniedError):
            await resolve_review_tag_scope_for_user(login_user)


@pytest.mark.asyncio
async def test_owner_with_independent_manager_can_review():
    login_user = _login_user()
    fga = SimpleNamespace(read_tuples=AsyncMock(return_value=[{"user": "user:9"}]))
    with (
        _scope_patches(
            can_manage=["100"],
            owner=["100"],
            levels={100: SimpleNamespace(level="public")},
            fga=fga,
        ),
        patch(
            "bisheng.database.models.department.UserDepartmentDao.aget_user_departments",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.database.models.user_group.UserGroupDao.aget_user_group",
            new=AsyncMock(return_value=[]),
        ),
    ):
        scope = await resolve_review_tag_scope_for_user(login_user)

    assert scope.role_managed_space_ids == frozenset({100})


@pytest.mark.asyncio
async def test_department_inherited_manager_can_review():
    login_user = _login_user()
    with _scope_patches(
        can_manage=["100"],
        owner=[],
        levels={100: SimpleNamespace(level="department")},
    ):
        scope = await resolve_review_tag_scope_for_user(login_user)

    assert scope.role_managed_space_ids == frozenset({100})


@pytest.mark.asyncio
async def test_department_admin_without_space_admin_cannot_review():
    login_user = _login_user()
    with _scope_patches():
        with pytest.raises(ReviewTagPermissionDeniedError):
            await resolve_review_tag_scope_for_user(login_user)
        assert await user_can_review_tags(login_user) is False


@pytest.mark.asyncio
async def test_clinic_admin_department_ids_are_union_of_team_ks():
    login_user = _login_user()
    with _scope_patches(
        can_manage=["200", "201"],
        owner=[],
        levels={
            200: SimpleNamespace(level="team_ks"),
            201: SimpleNamespace(level="team_ks"),
        },
        clinic_bindings=[
            SimpleNamespace(department_id=10),
            SimpleNamespace(department_id=11),
        ],
    ):
        scope = await resolve_review_tag_scope_for_user(login_user)

    assert scope.role_managed_space_ids == frozenset({200, 201})
    assert scope.clinic_admin_department_ids == frozenset({10, 11})


@pytest.mark.asyncio
async def test_user_can_review_tags():
    login_user = _login_user()
    with patch.object(
        workstation_tags_service,
        "resolve_review_tag_scope_for_user",
        new=AsyncMock(return_value=ReviewTagScope(clinic_admin_department_ids=frozenset({1}))),
    ):
        assert await user_can_review_tags(login_user) is True

    with patch.object(
        workstation_tags_service,
        "resolve_review_tag_scope_for_user",
        new=AsyncMock(side_effect=ReviewTagPermissionDeniedError()),
    ):
        assert await user_can_review_tags(login_user) is False


@pytest.mark.asyncio
async def test_list_review_tag_by_page_passes_scope():
    service = _build_service()
    scope = ReviewTagScope(clinic_admin_department_ids=frozenset({1}))
    service.resolve_review_tag_scope = AsyncMock(return_value=scope)
    service.review_tags_repository.get_review_tag_group_list_by_page = AsyncMock(
        return_value=[{"name": "foo", "resource_type": TagResourceTypeEnum.MANUAL_TAG}]
    )
    service.review_tags_repository.get_review_tag_resource_info_by_tag = AsyncMock(
        return_value={"tag_name": "foo", "resource_files": []}
    )
    service.review_tags_repository.get_review_tag_group_count_by_page = AsyncMock(return_value=1)

    result = await service.list_review_tag_by_page(1, 10, tenant_id=1, keyword="fo")

    assert result["total"] == 1
    service.review_tags_repository.get_review_tag_group_list_by_page.assert_awaited_once_with(
        1, 10, 1, "fo", scope=scope
    )


@pytest.mark.asyncio
async def test_approve_rejects_role_library_outside_scope():
    service = _build_service()
    service.resolve_review_tag_scope = AsyncMock(return_value=ReviewTagScope(role_managed_space_ids=frozenset({100})))
    service.review_tags_repository.list_submitter_notification_targets = AsyncMock(return_value=[])
    data = ApproveOrRejectRequest(
        tag_name="cross",
        status=ApproveOrRejectEnum.APPROVE,
        resource_type=TagResourceTypeEnum.MANUAL_TAG,
        tag_library_id=1,
        knowledge_id=999,
    )

    with (
        patch(
            "bisheng.knowledge.domain.models.knowledge_space_scope.KnowledgeSpaceScopeDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(level="public")),
        ),
        pytest.raises(ReviewTagSpaceOutOfScopeError),
    ):
        await service.approve_or_reject_review_tag(data, tenant_id=1)


@pytest.mark.asyncio
async def test_approve_allows_personal_space_for_clinic_admin():
    service = _build_service()
    scope = ReviewTagScope(clinic_admin_department_ids=frozenset({10}))
    service.resolve_review_tag_scope = AsyncMock(return_value=scope)
    data = ApproveOrRejectRequest(
        tag_name="personal",
        status=ApproveOrRejectEnum.APPROVE,
        resource_type=TagResourceTypeEnum.MANUAL_TAG,
        tag_library_id=10,
        knowledge_id=20,
    )
    service.approve_tag_to_move_operation = AsyncMock(return_value=[])
    service.review_tags_repository.approve_review_tag = AsyncMock()
    service.review_tags_repository.list_submitter_notification_targets = AsyncMock(return_value=[])
    service.review_tags_repository.get_review_tag_list_by_tag_name = AsyncMock(
        return_value=[SimpleNamespace(business_type="knowledge_space", business_id="20")],
    )

    with (
        patch.object(service, "ensure_review_tag_similar_acknowledged", new=AsyncMock()),
        patch(
            "bisheng.knowledge.domain.models.knowledge_space_scope.KnowledgeSpaceScopeDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(level="personal")),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryService",
        ) as library_service_cls,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryService.resolve_bound_library_ids",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.workstation.domain.services.review_tag_notification_service.ReviewTagNotificationService.notify_after_decision",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.models.knowledge_tag_library_link.KnowledgeTagLibraryLinkDao.aadd_links",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(
            service,
            "_list_in_scope_source_knowledge_ids",
            new=AsyncMock(return_value=[20]),
        ),
    ):
        library_service_cls.return_value.append_review_tag = AsyncMock()
        await service.approve_or_reject_review_tag(data, tenant_id=1)

    service.review_tags_repository.approve_review_tag.assert_awaited_once_with(
        "personal",
        TagResourceTypeEnum.MANUAL_TAG,
        1,
        scope=scope,
    )


@pytest.mark.asyncio
async def test_approve_passes_scope_to_repository():
    service = _build_service()
    scope = ReviewTagScope(role_managed_space_ids=frozenset({100}))
    service.resolve_review_tag_scope = AsyncMock(return_value=scope)
    data = ApproveOrRejectRequest(
        tag_name="scoped",
        status=ApproveOrRejectEnum.APPROVE,
        resource_type=TagResourceTypeEnum.MANUAL_TAG,
        tag_library_id=10,
        knowledge_id=100,
    )
    service.approve_tag_to_move_operation = AsyncMock(return_value=[])
    service.review_tags_repository.approve_review_tag = AsyncMock()
    service.review_tags_repository.list_submitter_notification_targets = AsyncMock(return_value=[])
    service.review_tags_repository.get_review_tag_list_by_tag_name = AsyncMock(
        return_value=[SimpleNamespace(business_type="knowledge_space", business_id="100")],
    )

    with (
        patch.object(service, "ensure_review_tag_similar_acknowledged", new=AsyncMock()),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryService",
        ) as library_service_cls,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryService.resolve_bound_library_ids",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.workstation.domain.services.review_tag_notification_service.ReviewTagNotificationService.notify_after_decision",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.models.knowledge_tag_library_link.KnowledgeTagLibraryLinkDao.aadd_links",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(
            service,
            "_list_in_scope_source_knowledge_ids",
            new=AsyncMock(return_value=[100]),
        ),
    ):
        library_service_cls.return_value.append_review_tag = AsyncMock()
        await service.approve_or_reject_review_tag(data, tenant_id=1)

    service.review_tags_repository.approve_review_tag.assert_awaited_once_with(
        "scoped",
        TagResourceTypeEnum.MANUAL_TAG,
        1,
        scope=scope,
    )
    service.approve_tag_to_move_operation.assert_awaited_once_with(
        "scoped",
        TagResourceTypeEnum.MANUAL_TAG,
        1,
        skip_library_add=True,
        scope=scope,
        target_library_id=10,
    )


@pytest.mark.asyncio
async def test_reject_passes_scope_to_repository():
    service = _build_service()
    scope = ReviewTagScope(clinic_admin_department_ids=frozenset({42}))
    service.resolve_review_tag_scope = AsyncMock(return_value=scope)
    data = ApproveOrRejectRequest(
        tag_name="scoped",
        status=ApproveOrRejectEnum.REJECT,
        reject_reason="bad",
        resource_type=TagResourceTypeEnum.MANUAL_TAG,
    )
    service.review_tags_repository.reject_review_tag = AsyncMock()
    service.review_tags_repository.get_review_tag_list_by_tag_name = AsyncMock(
        return_value=[SimpleNamespace(id=1, business_type="knowledge_space", business_id="100")],
    )
    service.review_tags_repository.list_submitter_notification_targets = AsyncMock(return_value=[])

    with (
        patch(
            "bisheng.workstation.domain.services.review_tag_notification_service.ReviewTagNotificationService.notify_after_decision",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistService.ensure_can_insert_async",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistService.add_names_async",
            new=AsyncMock(),
        ),
    ):
        await service.approve_or_reject_review_tag(data, tenant_id=1)

    service.review_tags_repository.reject_review_tag.assert_awaited_once_with(
        "scoped",
        "bad",
        TagResourceTypeEnum.MANUAL_TAG,
        1,
        scope=scope,
        reviewer_id=9,
    )


@pytest.mark.asyncio
async def test_global_super_has_full_scope():
    service = _build_service(is_global_super=True)
    scope = await service.resolve_review_tag_scope()
    assert scope.full_tenant is True


def test_review_tag_scope_allows_predicates():
    scope = ReviewTagScope(
        role_managed_space_ids=frozenset({10}),
        clinic_admin_department_ids=frozenset({5}),
    )
    assert scope.allows_space_for_uploader(space_id=10, level="public", uploader_id=99) is True
    assert (
        scope.allows_space_for_uploader(space_id=20, level="team", uploader_id=99, uploader_office_department_id=5)
        is True
    )
    assert (
        scope.allows_space_for_uploader(space_id=20, level="team_ks", uploader_id=99, uploader_office_department_id=5)
        is False
    )
    assert (
        scope.allows_space_for_uploader(space_id=20, level="personal", uploader_id=99, uploader_office_department_id=6)
        is False
    )
    assert (
        scope.allows_space_for_uploader(
            space_id=20, level="personal", uploader_id=99, uploader_office_department_id=None
        )
        is False
    )


@pytest.mark.asyncio
async def test_link_in_review_scope_uses_file_uploader_office_not_tagger():
    """他人给组织成员文件打标时，团队库待审归上传人科室下的科室库管理员。"""
    from bisheng.workstation.domain.repositories.review_tags_repository import ReviewTagsRepositoryImpl

    repo = ReviewTagsRepositoryImpl(session=AsyncMock(), tags_repository=AsyncMock())
    repo.tags_repository.get_knowledgefile_by_resource_id = AsyncMock(
        return_value=SimpleNamespace(
            id=15,
            knowledge_id=20,
            file_name="doc.pdf",
            file_type="pdf",
            user_id=42,
        )
    )
    repo._level_for_space = AsyncMock(return_value="team")
    repo._uploader_office_department_id = AsyncMock(side_effect=lambda uid: 10 if int(uid) == 42 else 99)
    link = SimpleNamespace(resource_id="15", user_id=1)
    tag = SimpleNamespace(user_id=1)

    clinic_of_uploader = ReviewTagScope(clinic_admin_department_ids=frozenset({10}))
    assert await repo.link_in_review_scope(link, tag, 1, clinic_of_uploader) is True

    clinic_of_tagger = ReviewTagScope(clinic_admin_department_ids=frozenset({99}))
    assert await repo.link_in_review_scope(link, tag, 1, clinic_of_tagger) is False


def test_clinic_uploader_sql_matches_knowledge_file_user_id_and_office_level():
    from bisheng.workstation.domain.repositories.review_tags_repository import ReviewTagsRepositoryImpl

    repo = ReviewTagsRepositoryImpl(session=AsyncMock(), tags_repository=AsyncMock())
    clause = repo._clinic_uploader_match_clause(1, {42})
    compiled = str(clause.compile(compile_kwargs={"literal_binds": True})).lower().replace("`", "")
    assert "knowledgefile.user_id" in compiled
    assert "review_tag_link.user_id" not in compiled
    assert "org_level" in compiled
    assert "office" in compiled
