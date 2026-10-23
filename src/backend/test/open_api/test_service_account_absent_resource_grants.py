"""Service-account grants that point at a deleted resource.

Resource deletion only closes the F048 ``permission_enabled`` gate, so the
grant roster (for example the CREATOR_GRANT a service account gets on a
resource it created) stays behind. Deleting the service account must still
work, and the account's grant list must not show those rows.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import (
    PermissionInvalidResourceError,
    PermissionPublishNotReadyError,
)
from bisheng.permission.application.control_state import SqlPermissionControlState
from bisheng.permission.application.resource_api import F048ResourcePermissionApi
from bisheng.permission.application.resource_authorization import (
    BoundResourceAuthorizationPort,
    ResourceAuthorizationRegistry,
)
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.models import PermissionGrant, PermissionGrantAssignee
from bisheng.permission.domain.repositories.grant_repository import GrantRepository
from bisheng.permission.domain.schemas import VerifiedPermissionTarget


def _grant(resource_id: str, assignee_id: int, *, version: int = 1, source_type: str = "CREATOR_GRANT") -> dict:
    return {
        "resource_type": "knowledge_library",
        "resource_id": resource_id,
        "assignee_id": str(assignee_id),
        "assignee_version": version,
        "source_type": source_type,
    }


class _Registry:
    def __init__(self, absent: set[tuple[str, str]]):
        self.absent = absent
        self.calls: list[tuple[str, str]] = []

    async def confirm_absent(self, *, resource_type, resource_id):
        self.calls.append((resource_type, resource_id))
        return (resource_type, resource_id) in self.absent


def _api(registry, runtime=None) -> F048ResourcePermissionApi:
    return F048ResourcePermissionApi(
        resources=registry,
        runtime=runtime or SimpleNamespace(),
        subjects=SimpleNamespace(),
    )


async def test_delete_account_removes_grants_on_deleted_resources(monkeypatch):
    """Account created a library, the library was deleted, then the account is deleted."""

    registry = _Registry(absent={("knowledge_library", "4283")})
    remove = AsyncMock(return_value=None)
    api = _api(registry, SimpleNamespace(remove_absent_resource_sources=remove))
    grants = [_grant("4283", 91, version=3)]
    list_grants = AsyncMock(return_value=grants)
    monkeypatch.setattr(api, "list_service_account_grants", list_grants)
    monkeypatch.setattr(api, "get_context", AsyncMock(side_effect=PermissionInvalidResourceError()))
    mutate = AsyncMock()
    monkeypatch.setattr(api, "mutate_grants", mutate)
    actor = SimpleNamespace(user_id=1)

    result = await api.revoke_service_account_grants(tenant_id=1, service_account_id=21, actor=actor)

    assert result == grants
    assert list_grants.await_args.kwargs["include_absent_resources"] is True
    mutate.assert_not_awaited()
    remove.assert_awaited_once()
    kwargs = remove.await_args.kwargs
    assert kwargs["actor"] is actor
    assert (kwargs["tenant_id"], kwargs["resource_type"], kwargs["resource_id"]) == (1, "knowledge_library", "4283")
    assert kwargs["assignees"] == ((91, 3),)
    assert kwargs["idempotency_key"].startswith("sa-delete-21-")


async def test_delete_account_keeps_failing_when_absence_is_not_confirmed(monkeypatch):
    """19003 alone may mean cross-tenant or an unauthorizable state: stay fail-closed."""

    registry = _Registry(absent=set())
    remove = AsyncMock()
    api = _api(registry, SimpleNamespace(remove_absent_resource_sources=remove))
    monkeypatch.setattr(api, "list_service_account_grants", AsyncMock(return_value=[_grant("9", 5)]))
    monkeypatch.setattr(api, "get_context", AsyncMock(side_effect=PermissionInvalidResourceError()))

    with pytest.raises(PermissionInvalidResourceError):
        await api.revoke_service_account_grants(tenant_id=1, service_account_id=21, actor=SimpleNamespace())

    assert registry.calls == [("knowledge_library", "9")]
    remove.assert_not_awaited()


async def test_delete_account_mixes_live_and_deleted_resources(monkeypatch):
    """A live resource keeps the ordinary mutation path; a deleted one is cleaned up."""

    registry = _Registry(absent={("knowledge_library", "4284")})
    remove = AsyncMock(return_value=None)
    api = _api(registry, SimpleNamespace(remove_absent_resource_sources=remove))
    grants = [_grant("10", 1, version=2), _grant("4284", 2)]
    monkeypatch.setattr(api, "list_service_account_grants", AsyncMock(return_value=grants))

    async def context(*, resource_type, resource_id, actor):
        if resource_id == "4284":
            raise PermissionInvalidResourceError()
        return {"resource_version": 7, "catalog_release_id": 5}

    monkeypatch.setattr(api, "get_context", context)
    mutate = AsyncMock(return_value={})
    monkeypatch.setattr(api, "mutate_grants", mutate)

    await api.revoke_service_account_grants(tenant_id=1, service_account_id=21, actor=SimpleNamespace())

    assert [call.kwargs["resource_id"] for call in mutate.await_args_list] == ["10"]
    request = mutate.await_args.kwargs["request"]
    assert request.expected_resource_version == 7
    assert [change.assignee_id for change in request.changes] == ["1"]
    assert [call.kwargs["resource_id"] for call in remove.await_args_list] == ["4284"]


def _row(resource_id: str, assignee_id: int):
    assignee = PermissionGrantAssignee(
        id=assignee_id,
        tenant_id=1,
        grant_id=assignee_id,
        subject_type="service_account",
        subject_id="21",
        source_type="CREATOR_GRANT",
        source_ref=f"knowledge_library:{resource_id}",
        source_locator="x",
        source_fingerprint="a" * 64,
        projected_subject="service_account:21",
        state="ACTIVE",
        version=1,
        create_time=datetime(2026, 10, 9),
    )
    grant = PermissionGrant(
        id=assignee_id,
        tenant_id=1,
        resource_type="knowledge_library",
        resource_id=resource_id,
        model_key="manager",
        state="ACTIVE",
    )
    return assignee, grant


async def _catalog():
    return SimpleNamespace(models=[SimpleNamespace(snapshot=SimpleNamespace(model_key="manager"), name="Manager")])


class _Subjects:
    def __init__(self, named: set[str]):
        self.named = named

    async def resource_display_names(self, resources):
        return {resource: f"name-{resource[1]}" for resource in resources if resource[1] in self.named}


@pytest.fixture
def three_rows(monkeypatch):
    async def rows(_self, *, tenant_id, subject_type, subject_id):
        return [_row("10", 1), _row("4285", 2), _row("77", 3)]

    monkeypatch.setattr(GrantRepository, "alist_active_subject_grants", rows)


async def test_grant_list_hides_rows_on_deleted_resources(three_rows):
    """10 has a name; 4285 is gone; 77 has no label but still exists, so it stays."""

    registry = _Registry(absent={("knowledge_library", "4285")})
    api = F048ResourcePermissionApi(
        resources=registry,
        runtime=SimpleNamespace(current_catalog=_catalog),
        subjects=_Subjects(named={"10"}),
    )

    result = await api.list_service_account_grants(tenant_id=1, service_account_id=21)

    assert [(row["resource_id"], row["resource_name"]) for row in result] == [("10", "name-10"), ("77", "77")]
    # Only unlabeled resources need the existence probe.
    assert sorted(registry.calls) == [("knowledge_library", "4285"), ("knowledge_library", "77")]


async def test_grant_list_keeps_row_when_the_probe_fails(three_rows):
    class _Broken:
        async def confirm_absent(self, *, resource_type, resource_id):
            raise PermissionPublishNotReadyError()

    api = F048ResourcePermissionApi(
        resources=_Broken(),
        runtime=SimpleNamespace(current_catalog=_catalog),
        subjects=_Subjects(named={"10"}),
    )

    result = await api.list_service_account_grants(tenant_id=1, service_account_id=21)

    assert [row["resource_id"] for row in result] == ["10", "4285", "77"]


async def test_revoke_listing_includes_rows_on_deleted_resources(three_rows):
    registry = _Registry(absent={("knowledge_library", "4285")})
    api = F048ResourcePermissionApi(
        resources=registry,
        runtime=SimpleNamespace(current_catalog=_catalog),
        subjects=_Subjects(named={"10"}),
    )

    result = await api.list_service_account_grants(
        tenant_id=1,
        service_account_id=21,
        include_absent_resources=True,
    )

    assert [row["resource_id"] for row in result] == ["10", "4285", "77"]
    assert registry.calls == []


class _Adapter:
    def __init__(self, record):
        self.record = record
        self.calls = []

    async def load_permission_record(self, *, resource_type, resource_id):
        self.calls.append((resource_type, resource_id))
        return self.record


class _DirectPort:
    def __init__(self, record):
        self.record = record

    async def load_permission_record(self, resource_id):
        return self.record


async def test_registry_confirms_absence_only_from_the_business_loader():
    registry = ResourceAuthorizationRegistry()
    gone = _Adapter(None)
    registry.register(
        "knowledge_library", BoundResourceAuthorizationPort(resource_type="knowledge_library", adapter=gone)
    )
    registry.register(
        "knowledge_space", BoundResourceAuthorizationPort(resource_type="knowledge_space", adapter=_Adapter(object()))
    )
    registry.register("channel", _DirectPort(None))
    registry.register("tool", SimpleNamespace(resolve_permission_target=None))

    assert await registry.confirm_absent(resource_type="knowledge_library", resource_id=" 4283 ") is True
    assert gone.calls == [("knowledge_library", "4283")]
    assert await registry.confirm_absent(resource_type="knowledge_space", resource_id="1") is False
    assert await registry.confirm_absent(resource_type="channel", resource_id="c1") is True
    # No loader, unknown type or empty id: absence cannot be confirmed.
    assert await registry.confirm_absent(resource_type="tool", resource_id="1") is False
    assert await registry.confirm_absent(resource_type="app", resource_id="1") is False
    assert await registry.confirm_absent(resource_type="knowledge_library", resource_id=" ") is False


async def test_registry_propagates_loader_errors():
    class _Failing:
        async def load_permission_record(self, *, resource_type, resource_id):
            raise PermissionPublishNotReadyError()

    registry = ResourceAuthorizationRegistry()
    registry.register("workflow", BoundResourceAuthorizationPort(resource_type="workflow", adapter=_Failing()))

    with pytest.raises(PermissionPublishNotReadyError):
        await registry.confirm_absent(resource_type="workflow", resource_id="w1")


def _target(version: int = 4) -> VerifiedPermissionTarget:
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=1,
        resource_type="knowledge_library",
        resource_id="4283",
        resource_version=version,
        context_version="absent:4",
    )


async def test_runtime_removes_sources_through_the_grant_mutation():
    runtime = object.__new__(F048PermissionRuntime)
    state = SimpleNamespace(absent_resource_target=AsyncMock(return_value=_target()))
    runtime._state = state
    runtime._runtime_catalog = AsyncMock(return_value=SimpleNamespace(release_id=8))
    runtime.mutate_grants = AsyncMock(return_value="done")
    actor = SimpleNamespace(user_id=1)

    result = await runtime.remove_absent_resource_sources(
        actor=actor,
        tenant_id=1,
        resource_type="knowledge_library",
        resource_id="4283",
        assignees=((91, 3), (92, 1)),
        idempotency_key="k",
    )

    assert result == "done"
    state.absent_resource_target.assert_awaited_once_with(
        tenant_id=1,
        resource_type="knowledge_library",
        resource_id="4283",
    )
    kwargs = runtime.mutate_grants.await_args.kwargs
    assert kwargs["target"] == _target()
    assert kwargs["expected_resource_version"] == 4
    assert kwargs["expected_catalog_release_id"] == 8
    assert [(c.operation, c.assignee_id, c.expected_assignee_version) for c in kwargs["changes"]] == [
        ("REMOVE", 91, 3),
        ("REMOVE", 92, 1),
    ]


class _Session:
    def __init__(self, row):
        self.row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, _statement):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: self.row))


async def test_absent_target_comes_from_the_current_permission_mirror(monkeypatch):
    from bisheng.permission.application import control_state

    row = SimpleNamespace(
        tenant_id=1,
        resource_type="knowledge_library",
        resource_id="4283",
        version=4,
        parent_type=None,
        parent_id=None,
        projection_state="CURRENT",
    )
    monkeypatch.setattr(control_state, "get_async_db_session", lambda: _Session(row))

    target = await SqlPermissionControlState().absent_resource_target(
        tenant_id=1,
        resource_type="knowledge_library",
        resource_id="4283",
    )

    assert (target.tenant_id, target.resource_id, target.resource_version) == (1, "4283", 4)

    row.projection_state = "PROJECTING"
    with pytest.raises(PermissionPublishNotReadyError):
        await SqlPermissionControlState().absent_resource_target(
            tenant_id=1,
            resource_type="knowledge_library",
            resource_id="4283",
        )
