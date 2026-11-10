from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError, PermissionVersionConflictError
from bisheng.permission.application.resource_api import F048ResourcePermissionApi
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.permission.test_f048_grant_policy import _context, _grant, _model

ACTOR = PermissionActor(user_id=100, tenant_id=7)


def resource_api(source=None, *, tenant=7, manageable=True, resource="42", projection_repository=None):
    model = _model("viewer", 1, "visible")
    sources = (source,) if source is not None else ()
    grant = replace(_grant(model), active=True, sources=sources)
    context = _context(capabilities=(), grants=(grant,), system_authorized=True)
    target = SimpleNamespace(tenant_id=tenant, resource_type="workflow", resource_id=resource)
    runtime = SimpleNamespace(
        require_manage_permission=AsyncMock(),
        build_grant_context=AsyncMock(return_value=context),
        manageable_model_keys=AsyncMock(return_value={"viewer"} if manageable else set()),
    )
    options = {"projection_repository": projection_repository} if projection_repository is not None else {}
    return F048ResourcePermissionApi(
        resources=SimpleNamespace(resolve=AsyncMock(return_value=target)), runtime=runtime, subjects=None, **options
    )


@pytest.mark.parametrize(
    "reason", ["valid", "tenant", "resource", "source", "protected", "group", "provenance", "unmanageable", "version"]
)
async def test_checks_exact_local_direct_user_source(reason):
    source = GrantSourceService().canonicalize_source(
        source_id=91, subject_type="user", subject_id="8", source_type="DIRECT"
    )
    if reason in {"protected", "group", "provenance"}:
        source = replace(
            source,
            **{
                "protected": {"protected": True},
                "group": {"subject_type": "user_group"},
                "provenance": {"source_type": "CREATOR"},
            }[reason],
        )
    api = resource_api(
        source,
        tenant=8 if reason == "tenant" else 7,
        manageable=reason != "unmanageable",
        resource="43" if reason == "resource" else "42",
    )
    kwargs = {
        "resource_id": "42",
        "actor": ACTOR,
        "assignee_id": 92 if reason == "source" else 91,
        "expected_assignee_version": 2 if reason == "version" else 1,
    }
    if reason == "valid":
        await api.check_workflow_direct_user_grant(**kwargs)
    else:
        with pytest.raises(PermissionVersionConflictError if reason == "version" else PermissionInvalidResourceError):
            await api.check_workflow_direct_user_grant(**kwargs)


@pytest.mark.parametrize(
    "mismatch", [None, "tenant_id", "scope_key", "operator_id", "operation_type", "idempotency_key"]
)
async def test_outcome_requires_original_scoped_operation(mismatch):
    fields = {
        "tenant_id": 7,
        "scope_type": "resource",
        "scope_key": "workflow:42",
        "operator_id": 100,
        "operation_type": "GRANT_MUTATION",
        "idempotency_key": "f128",
        "status": "FINALIZED",
        "target_version": 5,
    }
    if mismatch:
        fields[mismatch] = "other"
    reader = SimpleNamespace(aget_operation_by_idempotency=AsyncMock(return_value=SimpleNamespace(**fields)))
    api = resource_api(projection_repository=reader)
    result = await api.get_workflow_grant_outcome(resource_id="42", actor=ACTOR, idempotency_key="f128")
    assert result == (None if mismatch else ("FINALIZED", 5))
    reader.aget_operation_by_idempotency.assert_awaited_once_with("f128")
