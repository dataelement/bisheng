from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem
from bisheng.permission.domain.services.grant_subject_query_service import (
    GrantSubjectQueryService,
)
from bisheng.permission.domain.services.resource_authorization_service import (
    ResourceAuthorizationService,
)


def _user(user_id: int = 7):
    return SimpleNamespace(user_id=user_id, is_admin=lambda: False)


def _relation_models():
    return [
        {
            "id": relation,
            "name": relation.title(),
            "relation": relation,
            "grant_tier": "owner" if relation == "owner" else "manager" if relation == "manager" else "usage",
            "permissions": [],
            "permissions_explicit": False,
            "is_system": True,
        }
        for relation in ("owner", "manager", "editor", "viewer")
    ]


@pytest.fixture(autouse=True)
def default_relation_models(monkeypatch):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.resource_authorization_service.get_relation_models",
        AsyncMock(return_value=_relation_models()),
    )


@pytest.fixture
def repository():
    repo = SimpleNamespace(
        is_active_tenant=AsyncMock(return_value=True),
        list_users=AsyncMock(return_value=[{"user_id": 8, "user_name": "Alice"}]),
        list_departments_children=AsyncMock(return_value=[{"id": 10}]),
        search_departments=AsyncMock(return_value={"roots": [{"id": 10}], "total_matches": 1, "truncated": False}),
        get_departments_path_tree=AsyncMock(
            return_value={"roots": [{"id": 10}], "total_matches": 1, "truncated": False}
        ),
        list_user_groups=AsyncMock(return_value=[{"id": 20, "group_name": "Readers"}]),
        users_exist_in_tenant=AsyncMock(return_value=True),
        departments_exist_in_tenant=AsyncMock(return_value=True),
        user_groups_exist_in_tenant=AsyncMock(return_value=True),
        resolve_department_space_path=AsyncMock(return_value=None),
        grant_subjects_exist_in_department_scope=AsyncMock(return_value=True),
    )
    return repo


async def test_user_candidates_tenant_scoped(repository, monkeypatch):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.grant_subject_query_service.get_current_tenant_id",
        lambda: 5,
    )
    service = GrantSubjectQueryService(repository)

    result = await service.query_creation_subjects(
        resource_type="knowledge_space",
        subject_type="user",
        operation="list",
        login_user=_user(),
        keyword="Ali",
        page=2,
        page_size=25,
    )

    assert result == [{"user_id": 8, "user_name": "Alice"}]
    repository.list_users.assert_awaited_once_with(
        tenant_id=5,
        keyword="Ali",
        page=2,
        page_size=25,
        restrict_dept_path=None,
    )


@pytest.mark.parametrize(
    ("operation", "kwargs", "repository_method"),
    [
        ("children", {"parent_id": 10}, "list_departments_children"),
        ("search", {"keyword": "Eng", "limit": 20}, "search_departments"),
        ("path_tree", {"department_id": 11}, "get_departments_path_tree"),
    ],
)
async def test_department_lazy_operations(repository, monkeypatch, operation, kwargs, repository_method):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.grant_subject_query_service.get_current_tenant_id",
        lambda: 5,
    )
    service = GrantSubjectQueryService(repository)

    await service.query_creation_subjects(
        resource_type="channel",
        subject_type="department",
        operation=operation,
        login_user=_user(),
        **kwargs,
    )

    getattr(repository, repository_method).assert_awaited_once()
    assert getattr(repository, repository_method).await_args.kwargs["tenant_id"] == 5


async def test_creator_without_manage_permission_denied(repository, monkeypatch):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.grant_subject_query_service.get_current_tenant_id",
        lambda: 5,
    )
    service = GrantSubjectQueryService(repository)
    monkeypatch.setattr(
        service,
        "prospective_owner_permission_ids",
        AsyncMock(return_value={"view_space"}),
    )

    with pytest.raises(PermissionDeniedError):
        await service.query_creation_subjects(
            resource_type="knowledge_space",
            subject_type="user",
            operation="list",
            login_user=_user(),
        )

    repository.list_users.assert_not_awaited()


async def test_creation_candidates_use_configured_owner_permissions(repository, monkeypatch):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.grant_subject_query_service.get_current_tenant_id",
        lambda: 5,
    )
    read_models = AsyncMock(
        return_value=[
            {
                "id": "owner",
                "name": "Owner",
                "relation": "owner",
                "grant_tier": "owner",
                "permissions": ["view_space"],
                "permissions_explicit": True,
                "is_system": False,
            }
        ]
    )
    authorization_service = ResourceAuthorizationService(get_relation_models=read_models)
    service = GrantSubjectQueryService(
        repository,
        resource_authorization_service=authorization_service,
    )

    with pytest.raises(PermissionDeniedError):
        await service.query_creation_subjects(
            resource_type="knowledge_space",
            subject_type="user",
            operation="list",
            login_user=_user(),
        )

    read_models.assert_awaited_once()
    repository.list_users.assert_not_awaited()


async def test_validate_creation_grants_rejects_cross_tenant(repository, monkeypatch):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.grant_subject_query_service.get_current_tenant_id",
        lambda: 5,
    )
    repository.users_exist_in_tenant.return_value = False
    service = GrantSubjectQueryService(repository)

    with pytest.raises(PermissionDeniedError):
        await service.validate_creation_grants(
            resource_type="knowledge_space",
            grants=[AuthorizeGrantItem(subject_type="user", subject_id=999, relation="viewer")],
            login_user=_user(),
        )

    repository.users_exist_in_tenant.assert_awaited_once_with({999}, 5)


async def test_validate_creation_grants_rejects_current_user_before_persistence(repository):
    read_models = AsyncMock(return_value=_relation_models())
    authorization_service = ResourceAuthorizationService(
        get_relation_models=read_models,
    )
    authorization_service.validate_grants_for_permissions = AsyncMock()
    service = GrantSubjectQueryService(
        repository,
        resource_authorization_service=authorization_service,
    )

    with pytest.raises(PermissionDeniedError):
        await service.validate_creation_grants(
            resource_type="knowledge_space",
            grants=[AuthorizeGrantItem(subject_type="user", subject_id=7, relation="viewer")],
            login_user=_user(user_id=7),
        )

    read_models.assert_not_awaited()
    authorization_service.validate_grants_for_permissions.assert_not_awaited()
    repository.users_exist_in_tenant.assert_not_awaited()


async def test_validate_resource_grants_rejects_subject_moved_out_of_resource_tenant(
    repository,
):
    repository.users_exist_in_tenant.return_value = False
    service = GrantSubjectQueryService(repository)

    with patch(
        "bisheng.permission.domain.services.permission_service.PermissionService._resolve_resource_tenant",
        new=AsyncMock(return_value=5),
    ):
        with pytest.raises(PermissionDeniedError):
            await service.validate_resource_grants(
                resource_type="knowledge_space",
                resource_id="11",
                grants=[
                    AuthorizeGrantItem(
                        subject_type="user",
                        subject_id=999,
                        relation="viewer",
                    )
                ],
            )

    repository.is_active_tenant.assert_awaited_once_with(5)
    repository.users_exist_in_tenant.assert_awaited_once_with({999}, 5)


async def test_validate_resource_grants_rejects_subject_outside_department_space(repository):
    repository.resolve_department_space_path.return_value = "1/10"
    repository.grant_subjects_exist_in_department_scope.return_value = False
    service = GrantSubjectQueryService(repository)

    with patch(
        "bisheng.permission.domain.services.permission_service.PermissionService._resolve_resource_tenant",
        new=AsyncMock(return_value=5),
    ):
        with pytest.raises(PermissionDeniedError):
            await service.validate_resource_grants(
                resource_type="knowledge_space",
                resource_id="11",
                grants=[
                    AuthorizeGrantItem(
                        subject_type="user",
                        subject_id=8,
                        relation="viewer",
                    )
                ],
            )

    repository.grant_subjects_exist_in_department_scope.assert_awaited_once_with(
        user_ids={8},
        department_ids=set(),
        tenant_id=5,
        restrict_root_path="1/10",
    )


async def test_validate_resource_grants_rejects_user_groups_for_department_space(repository):
    repository.resolve_department_space_path.return_value = "1/10"
    service = GrantSubjectQueryService(repository)

    with patch(
        "bisheng.permission.domain.services.permission_service.PermissionService._resolve_resource_tenant",
        new=AsyncMock(return_value=5),
    ):
        with pytest.raises(PermissionDeniedError):
            await service.validate_resource_grants(
                resource_type="knowledge_space",
                resource_id="11",
                grants=[
                    AuthorizeGrantItem(
                        subject_type="user_group",
                        subject_id=20,
                        relation="viewer",
                    )
                ],
            )

    repository.grant_subjects_exist_in_department_scope.assert_not_awaited()


async def test_group_owner_rejected(repository, monkeypatch):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.grant_subject_query_service.get_current_tenant_id",
        lambda: 5,
    )
    service = GrantSubjectQueryService(repository)

    with pytest.raises(PermissionDeniedError):
        await service.validate_creation_grants(
            resource_type="channel",
            grants=[AuthorizeGrantItem(subject_type="user_group", subject_id=20, relation="owner")],
            login_user=_user(),
        )

    repository.user_groups_exist_in_tenant.assert_not_awaited()


async def test_validate_creation_grants_rejects_unknown_relation_model(repository, monkeypatch):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.grant_subject_query_service.get_current_tenant_id",
        lambda: 5,
    )
    authorization_service = ResourceAuthorizationService(
        get_relation_models=AsyncMock(return_value=_relation_models()),
    )
    authorization_service.validate_grants_for_permissions = AsyncMock(side_effect=PermissionDeniedError())
    service = GrantSubjectQueryService(
        repository,
        resource_authorization_service=authorization_service,
    )

    with pytest.raises(PermissionDeniedError):
        await service.validate_creation_grants(
            resource_type="knowledge_space",
            grants=[
                AuthorizeGrantItem(
                    subject_type="user",
                    subject_id=8,
                    relation="viewer",
                    model_id="unknown",
                )
            ],
            login_user=_user(),
        )

    authorization_service.validate_grants_for_permissions.assert_awaited_once()
    repository.users_exist_in_tenant.assert_not_awaited()


async def test_default_creation_model_validation_reads_domain_store(repository, monkeypatch):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.grant_subject_query_service.get_current_tenant_id",
        lambda: 5,
    )
    service = GrantSubjectQueryService(repository)
    models = [
        {
            "id": "owner",
            "name": "Owner",
            "relation": "owner",
            "grant_tier": "owner",
            "permissions": [],
            "permissions_explicit": False,
            "is_system": True,
        },
        {
            "id": "viewer",
            "name": "Viewer",
            "relation": "viewer",
            "grant_tier": "usage",
            "permissions": [],
            "permissions_explicit": False,
            "is_system": True,
        },
    ]

    with patch(
        "bisheng.permission.domain.services.resource_authorization_service.get_relation_models",
        new=AsyncMock(return_value=models),
    ) as read_models:
        await service.validate_creation_grants(
            resource_type="knowledge_space",
            grants=[
                AuthorizeGrantItem(
                    subject_type="user",
                    subject_id=8,
                    relation="viewer",
                    model_id="viewer",
                )
            ],
            login_user=_user(),
        )

    read_models.assert_awaited_once()


async def test_resource_user_candidates_keep_department_space_scope(repository):
    repository.resolve_department_space_path.return_value = "/10/"
    service = GrantSubjectQueryService(repository)

    with (
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service."
            "FineGrainedPermissionService.get_effective_permission_ids_async",
            new=AsyncMock(return_value={"manage_space_relation"}),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._resolve_resource_tenant",
            new=AsyncMock(return_value=5),
        ),
    ):
        result = await service.query_resource_users(
            resource_type="knowledge_space",
            resource_id="11",
            login_user=_user(),
            keyword="Ali",
            page=1,
            page_size=20,
        )

    assert result == [{"user_id": 8, "user_name": "Alice"}]
    repository.list_users.assert_awaited_once_with(
        tenant_id=5,
        keyword="Ali",
        page=1,
        page_size=20,
        restrict_dept_path="/10/",
    )


async def test_resource_department_space_hides_user_groups(repository):
    repository.resolve_department_space_path.return_value = "/10/"
    service = GrantSubjectQueryService(repository)

    with (
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service."
            "FineGrainedPermissionService.get_effective_permission_ids_async",
            new=AsyncMock(return_value={"manage_space_relation"}),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._resolve_resource_tenant",
            new=AsyncMock(return_value=5),
        ),
    ):
        result = await service.query_resource_user_groups(
            resource_type="knowledge_space",
            resource_id="11",
            login_user=_user(),
            keyword="",
        )

    assert result == []
    repository.list_user_groups.assert_not_awaited()


async def test_user_group_visibility_scope_is_resolved_by_domain_service(repository):
    login_user = SimpleNamespace(
        user_id=7,
        tenant_id=5,
        is_global_super=False,
        is_admin=lambda: False,
    )
    service = GrantSubjectQueryService(repository)

    with patch(
        "bisheng.permission.domain.services.permission_service.PermissionService.check",
        new=AsyncMock(return_value=False),
    ) as check_tenant_admin:
        await service.list_user_groups(
            tenant_id=5,
            keyword="read",
            login_user=login_user,
        )

    check_tenant_admin.assert_awaited_once()
    repository.list_user_groups.assert_awaited_once_with(
        tenant_id=5,
        keyword="read",
        viewer_user_id=7,
        can_view_all=False,
    )


async def test_user_group_visibility_scope_allows_system_admin(repository):
    login_user = SimpleNamespace(
        user_id=7,
        tenant_id=5,
        is_global_super=True,
        is_admin=lambda: False,
    )
    service = GrantSubjectQueryService(repository)

    with patch(
        "bisheng.permission.domain.services.permission_service.PermissionService.check",
        new=AsyncMock(),
    ) as check_tenant_admin:
        await service.list_user_groups(
            tenant_id=5,
            keyword="read",
            login_user=login_user,
        )

    check_tenant_admin.assert_not_awaited()
    repository.list_user_groups.assert_awaited_once_with(
        tenant_id=5,
        keyword="read",
        viewer_user_id=7,
        can_view_all=True,
    )
