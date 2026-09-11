"""The approved-upload FGA step must register through F048, not the legacy service.

`upload.fga` hand-wrote the parent tuple and the owner grant through the legacy
`PermissionService`. F048 migrated `folder` and `knowledge_file` and then closed
that service to business resources, so every attempt raised

    Legacy PermissionService cannot authorize an F048 business resource: knowledge_file

The approval was granted, the formal file row existed, and the step retried
forever — one request on the customer's machine reached 298 attempts — while the
file sat in WAITING and the list showed it as still processing.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    KnowledgeSpaceMutationExecutor,
    UploadStepDispatchContext,
)

_APPLICANT = 150041
_TENANT = 1


def _context(resources) -> UploadStepDispatchContext:
    return UploadStepDispatchContext(
        tenant_id=_TENANT,
        request_id=7,
        execution_token="ae4cfe7a-a709-42c4-a83c-613404065fcc",
        step_code="upload.fga",
        idempotency_key="f046:7:upload.fga",
        file_id=1123,
        file_name="dashboard_export.xlsx",
        applicant_user_id=_APPLICANT,
        space_id=156,
        checkpoint={"fga_resources": resources},
    )


_MANIFEST = [
    {
        "resource_type": "folder",
        "resource_id": 1120,
        "parent_type": "knowledge_space",
        "parent_id": 156,
        "owner_user_id": _APPLICANT,
    },
    {
        "resource_type": "knowledge_file",
        "resource_id": 1123,
        "parent_type": "folder",
        "parent_id": 1120,
        "owner_user_id": _APPLICANT,
    },
]


def _patches(*, register, login_user=SimpleNamespace(user_id=_APPLICANT)):
    return (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeSpaceService.initialize_child_resource_permissions_for_actor",
            register,
        ),
        patch(
            "bisheng.knowledge.domain.services.space_flow_retrieval.abuild_scoped_login_user",
            AsyncMock(return_value=login_user),
        ),
        patch(
            "bisheng.permission.application.identity.resolve_permission_actor",
            AsyncMock(return_value=SimpleNamespace(subject_id=_APPLICANT, super_admin=False)),
        ),
    )


async def test_every_manifest_resource_is_registered_through_f048():
    register = AsyncMock(return_value=None)
    a, b, c = _patches(register=register)
    with a, b, c:
        digest = await KnowledgeSpaceMutationExecutor._authorize_file(_context(_MANIFEST))

    assert digest == "fga:f046:7:upload.fga"
    assert register.await_count == 2
    assert [call.kwargs["object_type"] for call in register.await_args_list] == ["folder", "knowledge_file"]
    assert [call.kwargs["object_id"] for call in register.await_args_list] == [1120, 1123]
    # The parent link travels with the registration; it is not a separate write.
    assert register.await_args_list[1].kwargs["parent_type"] == "folder"
    assert register.await_args_list[1].kwargs["parent_id"] == 1120


async def test_the_legacy_permission_service_is_not_called():
    """The exact call that F048 refuses, and that spun the retry loop."""
    register = AsyncMock(return_value=None)
    a, b, c = _patches(register=register)
    with (
        a,
        b,
        c,
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            AsyncMock(side_effect=AssertionError("legacy authorize must not be used")),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.batch_write_tuples",
            AsyncMock(side_effect=AssertionError("legacy tuple write must not be used")),
        ),
    ):
        await KnowledgeSpaceMutationExecutor._authorize_file(_context(_MANIFEST))

    assert register.await_count == 2


async def test_an_unresolvable_applicant_fails_loudly():
    """Never register with a missing identity — the grant would name nobody."""
    register = AsyncMock(return_value=None)
    a, b, c = _patches(register=register, login_user=None)
    with a, b, c, pytest.raises(RuntimeError, match="applicant"):
        await KnowledgeSpaceMutationExecutor._authorize_file(_context(_MANIFEST))

    register.assert_not_awaited()


async def test_an_empty_manifest_is_a_hard_error():
    register = AsyncMock(return_value=None)
    a, b, c = _patches(register=register)
    with a, b, c, pytest.raises(RuntimeError, match="manifest"):
        await KnowledgeSpaceMutationExecutor._authorize_file(_context([]))
