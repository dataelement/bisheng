from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionTupleWriteError,
)
from bisheng.permission.domain.schemas.permission_schema import AuthorizeRequest


def _user(admin: bool = False):
    return SimpleNamespace(user_id=7, user_name="operator", is_admin=lambda: admin)


async def test_authorize_business_error_keeps_legacy_none_data():
    from bisheng.permission.api.endpoints.resource_permission import authorize_resource

    with patch(
        "bisheng.permission.domain.services.resource_authorization_service.ResourceAuthorizationService.authorize",
        new_callable=AsyncMock,
        side_effect=PermissionDeniedError(msg="denied"),
    ):
        response = await authorize_resource(
            resource_type="workflow",
            resource_id="1",
            request=AuthorizeRequest(),
            login_user=_user(),
        )

    assert response.status_code == PermissionDeniedError.Code
    assert response.status_message == "denied"
    assert response.data is None


async def test_authorize_tuple_error_keeps_exception_data():
    from bisheng.permission.api.endpoints.resource_permission import authorize_resource

    with patch(
        "bisheng.permission.domain.services.resource_authorization_service.ResourceAuthorizationService.authorize",
        new_callable=AsyncMock,
        side_effect=PermissionTupleWriteError(exception=RuntimeError("fga down")),
    ):
        response = await authorize_resource(
            resource_type="workflow",
            resource_id="1",
            request=AuthorizeRequest(),
            login_user=_user(),
        )

    assert response.status_code == PermissionTupleWriteError.Code
    assert response.data == {"exception": "fga down"}


async def test_creation_users_delegate_without_client_tenant_id():
    from bisheng.permission.api.endpoints.resource_permission import (
        get_creation_grant_subjects,
    )

    with patch(
        "bisheng.permission.api.endpoints.resource_permission.GrantSubjectQueryService.query_creation_subjects",
        new_callable=AsyncMock,
        return_value=[{"user_id": 8, "user_name": "Alice"}],
    ) as query:
        response = await get_creation_grant_subjects(
            resource_type="knowledge_space",
            subject_type="user",
            operation="list",
            keyword="Ali",
            page=1,
            page_size=20,
            parent_id=None,
            department_id=None,
            limit=50,
            login_user=_user(),
        )

    assert response.status_code == 200
    assert response.data == [{"user_id": 8, "user_name": "Alice"}]
    assert "tenant_id" not in query.await_args.kwargs


async def test_creation_candidate_permission_denial_keeps_existing_envelope():
    from bisheng.permission.api.endpoints.resource_permission import (
        get_creation_grant_subjects,
    )

    with patch(
        "bisheng.permission.api.endpoints.resource_permission.GrantSubjectQueryService.query_creation_subjects",
        new_callable=AsyncMock,
        side_effect=PermissionDeniedError(),
    ):
        response = await get_creation_grant_subjects(
            resource_type="channel",
            subject_type="department",
            operation="children",
            keyword="",
            page=1,
            page_size=1000,
            parent_id=None,
            department_id=None,
            limit=50,
            login_user=_user(),
        )

    assert response.status_code == PermissionDeniedError.Code


async def test_resource_candidates_delegate_to_query_service():
    from bisheng.permission.api.endpoints.resource_permission import get_grant_subject_users

    login_user = _user()
    with patch(
        "bisheng.permission.api.endpoints.resource_permission.GrantSubjectQueryService.query_resource_users",
        new_callable=AsyncMock,
        return_value=[{"user_id": 8}],
    ) as query:
        response = await get_grant_subject_users(
            resource_type="knowledge_space",
            resource_id="11",
            keyword="",
            page=1,
            page_size=100,
            login_user=login_user,
        )

    assert response.data == [{"user_id": 8}]
    query.assert_awaited_once_with(
        resource_type="knowledge_space",
        resource_id="11",
        login_user=login_user,
        keyword="",
        page=1,
        page_size=100,
    )


async def test_grantable_creation_does_not_require_object_id():
    from bisheng.permission.api.endpoints.resource_permission import (
        get_grantable_relation_models,
    )

    models = [
        {
            "id": "owner",
            "name": "Owner",
            "relation": "owner",
            "grant_tier": "owner",
            "permissions": [],
            "is_system": True,
        },
        {
            "id": "viewer",
            "name": "Viewer",
            "relation": "viewer",
            "grant_tier": "usage",
            "permissions": [],
            "is_system": True,
        },
    ]
    with (
        patch(
            "bisheng.permission.api.endpoints.resource_permission.GrantSubjectQueryService.resolve_creation_tenant_id",
            new_callable=AsyncMock,
            return_value=3,
        ) as resolve_tenant,
        patch(
            "bisheng.permission.api.endpoints.resource_permission._get_relation_models",
            new_callable=AsyncMock,
            return_value=models,
        ) as get_models,
    ):
        response = await get_grantable_relation_models(
            object_type="knowledge_space",
            object_id=None,
            creation=True,
            login_user=_user(),
        )

    assert response.status_code == 200
    assert {item.id for item in response.data} == {"owner", "viewer"}
    resolve_tenant.assert_awaited_once()
    get_models.assert_awaited_once()


async def test_grantable_creation_returns_empty_when_configured_owner_cannot_manage():
    from bisheng.permission.api.endpoints.resource_permission import (
        get_grantable_relation_models,
    )

    models = [
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
    with (
        patch(
            "bisheng.permission.api.endpoints.resource_permission.GrantSubjectQueryService.resolve_creation_tenant_id",
            new_callable=AsyncMock,
            return_value=3,
        ),
        patch(
            "bisheng.permission.api.endpoints.resource_permission._get_relation_models",
            new_callable=AsyncMock,
            return_value=models,
        ) as get_models,
    ):
        response = await get_grantable_relation_models(
            object_type="knowledge_space",
            object_id=None,
            creation=True,
            login_user=_user(),
        )

    assert response.status_code == 200
    assert response.data == []
    get_models.assert_awaited_once()


async def test_grantable_creation_filters_with_configured_owner_permissions():
    from bisheng.permission.api.endpoints.resource_permission import (
        get_grantable_relation_models,
    )

    models = [
        {
            "id": "owner",
            "name": "Owner",
            "relation": "owner",
            "grant_tier": "owner",
            "permissions": ["manage_space_relation", "view_space"],
            "permissions_explicit": True,
            "is_system": False,
        },
        {
            "id": "custom_viewer",
            "name": "Viewer",
            "relation": "viewer",
            "grant_tier": "usage",
            "permissions": ["view_space"],
            "permissions_explicit": True,
            "is_system": False,
        },
        {
            "id": "custom_editor",
            "name": "Editor",
            "relation": "editor",
            "grant_tier": "usage",
            "permissions": ["upload_file"],
            "permissions_explicit": True,
            "is_system": False,
        },
    ]
    with (
        patch(
            "bisheng.permission.api.endpoints.resource_permission.GrantSubjectQueryService.resolve_creation_tenant_id",
            new_callable=AsyncMock,
            return_value=3,
        ),
        patch(
            "bisheng.permission.api.endpoints.resource_permission._get_relation_models",
            new_callable=AsyncMock,
            return_value=models,
        ) as get_models,
    ):
        response = await get_grantable_relation_models(
            object_type="knowledge_space",
            object_id=None,
            creation=True,
            login_user=_user(),
        )

    assert response.status_code == 200
    assert {item.id for item in response.data} == {"owner", "custom_viewer"}
    get_models.assert_awaited_once()


async def test_grantable_creation_rejects_inactive_tenant_before_reading_models():
    from bisheng.permission.api.endpoints.resource_permission import (
        get_grantable_relation_models,
    )

    with (
        patch(
            "bisheng.permission.api.endpoints.resource_permission.GrantSubjectQueryService.resolve_creation_tenant_id",
            new_callable=AsyncMock,
            side_effect=PermissionDeniedError(),
        ),
        patch(
            "bisheng.permission.api.endpoints.resource_permission._get_relation_models",
            new_callable=AsyncMock,
        ) as get_models,
    ):
        response = await get_grantable_relation_models(
            object_type="knowledge_space",
            object_id=None,
            creation=True,
            login_user=_user(),
        )

    assert response.status_code == PermissionDeniedError.Code
    assert response.data is None
    get_models.assert_not_awaited()


async def test_resource_department_candidates_delegate_to_query_service():
    from bisheng.permission.api.endpoints.resource_permission import (
        get_grant_subject_departments_children,
        get_grant_subject_departments_path_tree,
        search_grant_subject_departments,
    )

    result = {"roots": [{"id": 9}], "total_matches": 1, "truncated": False}
    with patch(
        "bisheng.permission.api.endpoints.resource_permission.GrantSubjectQueryService.query_resource_departments",
        new_callable=AsyncMock,
        side_effect=[[{"id": 9}], result, result],
    ) as query:
        children = await get_grant_subject_departments_children("knowledge_space", "11", None, _user())
        search = await search_grant_subject_departments("knowledge_space", "11", "eng", 50, _user())
        path_tree = await get_grant_subject_departments_path_tree("knowledge_space", "11", 9, _user())

    assert children.data == [{"id": 9}]
    assert search.data == result
    assert path_tree.data == result
    assert [call.kwargs["operation"] for call in query.await_args_list] == [
        "children",
        "search",
        "path_tree",
    ]


async def test_resource_user_groups_delegate_to_query_service():
    from bisheng.permission.api.endpoints.resource_permission import (
        get_grant_subject_user_groups,
    )

    login_user = _user()
    with patch(
        "bisheng.permission.api.endpoints.resource_permission.GrantSubjectQueryService.query_resource_user_groups",
        new_callable=AsyncMock,
        return_value=[{"id": 20}],
    ) as query:
        response = await get_grant_subject_user_groups("knowledge_space", "11", "reader", login_user)

    assert response.data == [{"id": 20}]
    query.assert_awaited_once_with(
        resource_type="knowledge_space",
        resource_id="11",
        login_user=login_user,
        keyword="reader",
    )


async def test_grantable_resource_mode_still_uses_effective_permissions():
    from bisheng.permission.api.endpoints.resource_permission import (
        get_grantable_relation_models,
    )

    models = [
        {
            "id": "viewer",
            "name": "Viewer",
            "relation": "viewer",
            "grant_tier": "usage",
            "permissions": [],
            "is_system": True,
        }
    ]
    with (
        patch(
            "bisheng.permission.api.endpoints.resource_permission._get_relation_models",
            new_callable=AsyncMock,
            return_value=models,
        ),
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service."
            "FineGrainedPermissionService.get_effective_permission_ids_async",
            new_callable=AsyncMock,
            return_value={"manage_space_relation"},
        ) as permissions,
    ):
        response = await get_grantable_relation_models(
            object_type="knowledge_space",
            object_id="11",
            creation=False,
            login_user=_user(),
        )

    assert response.status_code == 200
    permissions.assert_awaited_once()
