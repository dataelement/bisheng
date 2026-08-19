from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.models.space_channel_member import (
    ChannelRelationEnum,
    MembershipStatusEnum,
    SpaceChannelMemberDao,
    UserRoleEnum,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.openfga.exceptions import FGAConnectionError
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.repositories.grant_subject_query_repository import (
    GrantSubjectQueryRepository,
)
from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)
from bisheng.permission.domain.services.permission_service import PermissionService


@pytest.fixture(autouse=True)
def tenant_context():
    token = current_tenant_id.set(None)
    set_current_tenant_id(42)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def _user() -> UserPayload:
    return UserPayload(user_id=7, user_name="applicant", tenant_id=42, user_role=[])


async def _strict_check(
    *,
    tuples: list[dict],
    bindings: list[dict] | None = None,
    models: dict[str, dict] | None = None,
    subjects: set[str] | None = None,
    allowed_unbound: set[tuple[str, str, str]] | None = None,
    checks: list[bool] | None = None,
) -> tuple[bool, AsyncMock]:
    fga = AsyncMock()
    fga.check.side_effect = checks or [False, False]
    fga.read_tuples.return_value = tuples
    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        patch.object(
            GrantSubjectQueryRepository,
            "is_active_user_in_any_active_tenant",
            AsyncMock(return_value=True),
        ),
        patch.object(
            GrantSubjectQueryRepository,
            "resolve_active_subject_strings_for_user",
            AsyncMock(return_value={"user:7"} if subjects is None else subjects),
        ),
        patch.object(
            FineGrainedPermissionService,
            "get_relation_models_map",
            AsyncMock(return_value=models or {}),
        ),
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service._get_bindings",
            AsyncMock(return_value=bindings or []),
        ),
        patch.object(
            FineGrainedPermissionService,
            "get_binding_department_paths",
            AsyncMock(return_value={}),
        ),
    ):
        result = await FineGrainedPermissionService.has_effective_permission_id_strict(
            _user(),
            "knowledge_space",
            8,
            "upload_file",
            tenant_id=42,
            space_id=8,
            allowed_unbound_direct_tuples=allowed_unbound,
        )
    return result, fga


async def test_strict_permission_uses_custom_model_permissions_for_group_userset():
    tuple_item = {
        "user": "user_group:9#member",
        "relation": "viewer",
        "object": "knowledge_space:8",
    }
    binding = {
        "resource_type": "knowledge_space",
        "resource_id": "8",
        "subject_type": "user_group",
        "subject_id": 9,
        "relation": "viewer",
        "model_id": "custom-viewer",
        "include_children": False,
    }
    allowed, fga = await _strict_check(
        tuples=[tuple_item],
        bindings=[binding],
        models={
            "custom-viewer": {
                "relation": "viewer",
                "permissions": ["view_space", "upload_file"],
                "permissions_explicit": True,
                "is_system": False,
            }
        },
        subjects={"user:7", "user_group:9#member"},
    )

    assert allowed is True
    fga.read_tuples.assert_awaited_once_with(
        object="knowledge_space:8",
        consistency="HIGHER_CONSISTENCY",
    )


async def test_strict_permission_denies_custom_relation_without_upload_file():
    allowed, _fga = await _strict_check(
        tuples=[{"user": "user:7", "relation": "editor", "object": "knowledge_space:8"}],
        bindings=[
            {
                "resource_type": "knowledge_space",
                "resource_id": "8",
                "subject_type": "user",
                "subject_id": 7,
                "relation": "editor",
                "model_id": "custom-editor",
                "include_children": False,
            }
        ],
        models={
            "custom-editor": {
                "relation": "editor",
                "permissions": ["view_space", "rename_file"],
                "permissions_explicit": True,
                "is_system": False,
            }
        },
    )

    assert allowed is False


async def test_strict_permission_does_not_revive_stale_binding_after_tuple_revoke():
    allowed, _fga = await _strict_check(
        tuples=[],
        bindings=[
            {
                "resource_type": "knowledge_space",
                "resource_id": "8",
                "subject_type": "user",
                "subject_id": 7,
                "relation": "owner",
                "model_id": "owner",
                "include_children": False,
            }
        ],
        models={"owner": {"relation": "owner", "permissions": [], "is_system": True}},
    )

    assert allowed is False


async def test_strict_permission_only_accepts_projected_unbound_legacy_tuple():
    tuple_item = {"user": "user:7", "relation": "manager", "object": "knowledge_space:8"}
    denied, _fga = await _strict_check(tuples=[tuple_item])
    allowed, _fga = await _strict_check(
        tuples=[tuple_item],
        allowed_unbound={("knowledge_space", "8", "manager")},
    )

    assert denied is False
    assert allowed is True


async def test_strict_permission_propagates_strong_fga_read_failure():
    fga = AsyncMock()
    fga.check.side_effect = [False, False]
    failure = FGAConnectionError("offline")
    fga.read_tuples.side_effect = failure
    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        patch.object(
            GrantSubjectQueryRepository,
            "is_active_user_in_any_active_tenant",
            AsyncMock(return_value=True),
        ),
        patch.object(
            GrantSubjectQueryRepository,
            "resolve_active_subject_strings_for_user",
            AsyncMock(return_value={"user:7"}),
        ),
        patch.object(FineGrainedPermissionService, "get_relation_models_map", AsyncMock(return_value={})),
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service._get_bindings",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            FineGrainedPermissionService,
            "get_binding_department_paths",
            AsyncMock(return_value={}),
        ),
        pytest.raises(FGAConnectionError) as exc_info,
    ):
        await FineGrainedPermissionService.has_effective_permission_id_strict(
            _user(),
            "knowledge_space",
            8,
            "upload_file",
            tenant_id=42,
            space_id=8,
        )

    assert exc_info.value is failure


async def test_strict_global_admin_requires_active_identity_but_not_target_tenant_membership():
    fga = AsyncMock()
    fga.check.return_value = True
    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        patch.object(
            GrantSubjectQueryRepository,
            "is_active_user_in_any_active_tenant",
            AsyncMock(return_value=True),
        ),
        patch.object(
            GrantSubjectQueryRepository,
            "resolve_active_subject_strings_for_user",
            AsyncMock(),
        ) as target_subjects,
    ):
        allowed = await FineGrainedPermissionService.has_effective_permission_id_strict(
            _user(), "knowledge_space", 8, "upload_file", tenant_id=42, space_id=8
        )

    assert allowed is True
    target_subjects.assert_not_awaited()


async def test_strict_stale_global_admin_tuple_cannot_revive_disabled_user():
    fga = AsyncMock()
    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        patch.object(
            GrantSubjectQueryRepository,
            "is_active_user_in_any_active_tenant",
            AsyncMock(return_value=False),
        ),
    ):
        allowed = await FineGrainedPermissionService.has_effective_permission_id_strict(
            _user(), "knowledge_space", 8, "upload_file", tenant_id=42, space_id=8
        )

    assert allowed is False
    fga.check.assert_not_awaited()


async def test_strict_tenant_admin_requires_active_target_tenant_membership():
    allowed, fga = await _strict_check(tuples=[], subjects=set(), checks=[False, True])

    assert allowed is False
    assert fga.check.await_count == 1


async def test_knowledge_owner_builds_only_authoritative_legacy_projections():
    service = KnowledgeSpaceService(request=None, login_user=_user())
    locked_space = SimpleNamespace(id=8, tenant_id=42, user_id=7)
    membership = SimpleNamespace(
        is_active=True,
        relation=ChannelRelationEnum.EDITOR,
        user_role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.ACTIVE,
    )
    with (
        patch.object(SpaceChannelMemberDao, "async_find_member", AsyncMock(return_value=membership)),
        patch.object(
            FineGrainedPermissionService,
            "has_effective_permission_id_strict",
            AsyncMock(return_value=True),
        ) as strict_evaluator,
    ):
        assert await service.has_effective_permission_id_strict(
            "knowledge_space",
            8,
            "upload_file",
            space_id=8,
            locked_space=locked_space,
        )

    assert strict_evaluator.await_args.kwargs["allowed_unbound_direct_tuples"] == {
        ("knowledge_space", "8", "owner"),
        ("knowledge_space", "8", "editor"),
    }
