from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpaceFileChangeApproverUnavailableError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.openfga.exceptions import FGAConnectionError
from bisheng.knowledge.domain.services.knowledge_space_file_change_approver_resolver import (
    KnowledgeSpaceFileChangeApproverResolver,
)
from bisheng.permission.domain.services.permission_service import PermissionService


@pytest.fixture(autouse=True)
def reset_tenant_context():
    token = current_tenant_id.set(None)
    with patch.object(
        PermissionService,
        "resolve_permanent_creator_user_ids_strict",
        AsyncMock(return_value=set()),
    ):
        yield
    current_tenant_id.reset(token)


async def test_resolve_approvers_uses_authoritative_owner_and_manager_relations():
    set_current_tenant_id(17)

    with patch.object(
        PermissionService,
        "resolve_resource_relation_user_ids_strict",
        AsyncMock(return_value={11, 7, 9}),
    ) as strict_resolve:
        result = await KnowledgeSpaceFileChangeApproverResolver.resolve_approver_user_ids(
            tenant_id=17,
            space_id=101,
            applicant_user_id=None,
        )

    assert result == [7, 9, 11]
    strict_resolve.assert_awaited_once_with(
        tenant_id=17,
        object_type="knowledge_space",
        object_id="101",
        relations=("owner", "manager"),
    )


async def test_resolve_approvers_deduplicates_and_excludes_applicant():
    set_current_tenant_id(17)

    with patch.object(
        PermissionService,
        "resolve_resource_relation_user_ids_strict",
        AsyncMock(return_value=[9, 7, 9, 11, 7]),
    ):
        result = await KnowledgeSpaceFileChangeApproverResolver.resolve_approver_user_ids(
            tenant_id=17,
            space_id=101,
            applicant_user_id=9,
        )

    assert result == [7, 11]


async def test_resolve_approvers_includes_active_permanent_space_creator_without_owner_tuple():
    set_current_tenant_id(17)

    with (
        patch.object(
            PermissionService,
            "resolve_resource_relation_user_ids_strict",
            AsyncMock(return_value=set()),
        ),
        patch.object(
            PermissionService,
            "resolve_permanent_creator_user_ids_strict",
            AsyncMock(return_value={7}),
        ) as permanent_creators,
    ):
        result = await KnowledgeSpaceFileChangeApproverResolver.resolve_approver_user_ids(
            tenant_id=17,
            space_id=101,
            applicant_user_id=None,
        )

    assert result == [7]
    permanent_creators.assert_awaited_once_with(
        tenant_id=17,
        object_type="knowledge_space",
        object_id="101",
    )


async def test_resolve_approvers_excludes_permanent_creator_when_creator_is_applicant():
    set_current_tenant_id(17)

    with (
        patch.object(
            PermissionService,
            "resolve_resource_relation_user_ids_strict",
            AsyncMock(return_value=set()),
        ),
        patch.object(
            PermissionService,
            "resolve_permanent_creator_user_ids_strict",
            AsyncMock(return_value={7}),
        ),
    ):
        result = await KnowledgeSpaceFileChangeApproverResolver.resolve_approver_user_ids(
            tenant_id=17,
            space_id=101,
            applicant_user_id=7,
        )

    assert result == []


async def test_resolve_approvers_returns_empty_only_for_authoritative_empty_result():
    set_current_tenant_id(17)

    with patch.object(
        PermissionService,
        "resolve_resource_relation_user_ids_strict",
        AsyncMock(return_value=set()),
    ):
        result = await KnowledgeSpaceFileChangeApproverResolver.resolve_approver_user_ids(
            tenant_id=17,
            space_id=101,
            applicant_user_id=9,
        )

    assert result == []


@pytest.mark.parametrize(
    "failure",
    [
        FGAConnectionError("offline"),
        RuntimeError("tenant context is required"),
        ValueError("Unsupported OpenFGA subject"),
    ],
)
async def test_resolve_approvers_maps_authoritative_failures_to_18076(failure):
    set_current_tenant_id(17)

    with (
        patch.object(
            PermissionService,
            "resolve_resource_relation_user_ids_strict",
            AsyncMock(side_effect=failure),
        ),
        pytest.raises(SpaceFileChangeApproverUnavailableError) as exc_info,
    ):
        await KnowledgeSpaceFileChangeApproverResolver.resolve_approver_user_ids(
            tenant_id=17,
            space_id=101,
            applicant_user_id=9,
        )

    assert exc_info.value.code == 18076
    assert exc_info.value.exception is failure


@pytest.mark.parametrize("context_tenant", [None, 1])
async def test_resolver_never_uses_root_or_missing_tenant_fallback(context_tenant):
    if context_tenant is not None:
        set_current_tenant_id(context_tenant)

    with (
        patch.object(
            PermissionService,
            "resolve_resource_relation_user_ids_strict",
            AsyncMock(),
        ) as strict_resolve,
        pytest.raises(SpaceFileChangeApproverUnavailableError) as exc_info,
    ):
        await KnowledgeSpaceFileChangeApproverResolver.resolve_approver_user_ids(
            tenant_id=17,
            space_id=101,
            applicant_user_id=9,
        )

    assert exc_info.value.code == 18076
    strict_resolve.assert_not_awaited()


async def test_is_current_approver_uses_same_strict_resolution():
    set_current_tenant_id(17)

    with patch.object(
        PermissionService,
        "resolve_resource_relation_user_ids_strict",
        AsyncMock(return_value={7, 9}),
    ):
        assert await KnowledgeSpaceFileChangeApproverResolver.is_current_approver(
            tenant_id=17,
            space_id=101,
            user_id=9,
        )
        assert not await KnowledgeSpaceFileChangeApproverResolver.is_current_approver(
            tenant_id=17,
            space_id=101,
            user_id=11,
        )
