from __future__ import annotations

import ast
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
from bisheng.common.errcode.permission import PermissionDeniedError, PermissionTupleWriteError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.permission.domain.ports.resource_grant_executor import ResourceGrantCommand
from bisheng.permission.domain.schemas.permission_schema import (
    AuthorizeGrantItem,
    AuthorizeRequest,
    AuthorizeRevokeItem,
)
from bisheng.permission.domain.services.resource_authorization_service import (
    KnowledgeSpaceResourceGrantExecutor,
    ResourceAuthorizationService,
)

TENANT_ID = 3
RESOURCE_ID = "11"
INVITER_USER_ID = 7
TARGET_USER_ID = 42


@pytest.fixture(autouse=True)
def tenant_context():
    token = set_current_tenant_id(TENANT_ID)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def _login_user():
    return SimpleNamespace(
        user_id=INVITER_USER_ID,
        user_name="inviter",
        tenant_id=TENANT_ID,
        is_admin=lambda: True,
    )


def _role_snapshot() -> dict[str, object]:
    return {
        "id": "viewer",
        "name": "Viewer",
        "relation": "viewer",
        "permissions": [],
        "permissions_explicit": False,
        "is_system": True,
        "grant_tier": "usage",
    }


def _fingerprint(snapshot: dict[str, object]) -> str:
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _grant_command() -> ResourceGrantCommand:
    role_snapshot = _role_snapshot()
    return ResourceGrantCommand(
        tenant_id=TENANT_ID,
        request_id=501,
        request_fingerprint="request-fingerprint",
        resource_type="knowledge_space",
        resource_id=RESOURCE_ID,
        inviter_user_id=INVITER_USER_ID,
        target_user_id=TARGET_USER_ID,
        relation="viewer",
        model_id="viewer",
        include_children=False,
        role_snapshot=role_snapshot,
        role_fingerprint=_fingerprint(role_snapshot),
    )


async def test_new_personal_user_creates_only_f045_business_request() -> None:
    guard_events: list[str] = []

    @asynccontextmanager
    async def scenario_guard(*, tenant_id: int):
        assert tenant_id == TENANT_ID
        guard_events.append("enter")
        yield
        guard_events.append("exit")

    invite_application_service = SimpleNamespace(
        scenario_guard=scenario_guard,
        request_invite=AsyncMock(
            return_value={
                "outcome": "invite_created",
                "request_id": 501,
                "approval_instance_id": 88,
                "target_user_id": TARGET_USER_ID,
                "relation": "viewer",
                "model_id": "viewer",
            }
        ),
    )
    role_snapshot = _role_snapshot()
    service = ResourceAuthorizationService(
        invite_application_service=invite_application_service,
        grant_subject_query_service=SimpleNamespace(validate_resource_grants=AsyncMock()),
        get_relation_models=AsyncMock(return_value=[role_snapshot]),
    )
    service._resolve_invite_context = AsyncMock(return_value=("Space", "Target", None))
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(
                subject_type="user",
                subject_id=TARGET_USER_ID,
                relation="viewer",
                model_id="viewer",
            )
        ]
    )

    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._resolve_resource_tenant",
            new=AsyncMock(return_value=TENANT_ID),
        ),
        patch(
            "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as direct_authorize,
    ):
        result = await service.authorize(
            "knowledge_space",
            RESOURCE_ID,
            request,
            _login_user(),
        )

    direct_authorize.assert_not_awaited()
    invite_application_service.request_invite.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        resource_type="knowledge_space",
        resource_id=RESOURCE_ID,
        resource_name="Space",
        inviter_user_id=INVITER_USER_ID,
        inviter_user_name="inviter",
        target_user_id=TARGET_USER_ID,
        target_user_name="Target",
        relation="viewer",
        model_id="viewer",
        role_snapshot=role_snapshot,
        include_children=False,
        applicant_department_id=None,
    )
    assert result is not None
    assert result.direct_applied_count == 0
    assert result.invite_created_count == 1
    assert result.results[0].approval_instance_id == 88
    assert guard_events == ["enter", "exit"]


async def test_department_group_and_existing_user_changes_stay_direct() -> None:
    invite_application_service = SimpleNamespace(request_invite=AsyncMock())
    service = ResourceAuthorizationService(
        invite_application_service=invite_application_service,
    )
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(subject_type="department", subject_id=9, relation="viewer"),
            AuthorizeGrantItem(subject_type="user_group", subject_id=10, relation="viewer"),
            AuthorizeGrantItem(subject_type="user", subject_id=TARGET_USER_ID, relation="editor"),
        ]
    )
    existing = SimpleNamespace(
        subject_type="user",
        subject_id=TARGET_USER_ID,
        relation="viewer",
    )

    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[existing]),
        ),
        patch.object(service, "_authorize_direct", new=AsyncMock()) as direct,
    ):
        result = await service.authorize(
            "knowledge_space",
            RESOURCE_ID,
            request,
            _login_user(),
        )

    invite_application_service.request_invite.assert_not_awaited()
    direct.assert_awaited_once()
    direct_request = direct.await_args.args[2]
    assert direct_request.grants == request.grants
    assert result is not None
    assert result.direct_applied_count == 3


async def test_mixed_request_disabled_scenario_degrades_to_direct() -> None:
    @asynccontextmanager
    async def disabled_guard(*, tenant_id: int):
        assert tenant_id == TENANT_ID
        raise ApprovalScenarioDisabledError()
        yield

    invite_application_service = SimpleNamespace(
        scenario_guard=disabled_guard,
        request_invite=AsyncMock(),
    )
    service = ResourceAuthorizationService(
        invite_application_service=invite_application_service,
    )
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(subject_type="department", subject_id=9, relation="viewer"),
            AuthorizeGrantItem(
                subject_type="user",
                subject_id=TARGET_USER_ID,
                relation="viewer",
            ),
        ]
    )

    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._resolve_resource_tenant",
            new=AsyncMock(return_value=TENANT_ID),
        ),
        patch.object(service, "_authorize_direct", new=AsyncMock()) as direct,
    ):
        result = await service.authorize(
            "knowledge_space",
            RESOURCE_ID,
            request,
            _login_user(),
        )

    # 审批场景关闭 -> 降级为直接授权：所有 grant（含新增个人用户）直接写入，不创建本人确认审批。
    direct.assert_awaited_once()
    direct_request = direct.await_args.args[2]
    assert direct_request.grants == request.grants
    invite_application_service.request_invite.assert_not_awaited()
    assert result.direct_applied_count == 2


async def test_personal_user_removal_stays_direct() -> None:
    invite_application_service = SimpleNamespace(request_invite=AsyncMock())
    service = ResourceAuthorizationService(
        invite_application_service=invite_application_service,
    )
    request = AuthorizeRequest(
        revokes=[
            AuthorizeRevokeItem(
                subject_type="user",
                subject_id=TARGET_USER_ID,
                relation="viewer",
                model_id="viewer",
            )
        ]
    )

    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(service, "_authorize_direct", new=AsyncMock()) as direct,
    ):
        result = await service.authorize(
            "knowledge_space",
            RESOURCE_ID,
            request,
            _login_user(),
        )

    invite_application_service.request_invite.assert_not_awaited()
    direct.assert_awaited_once()
    direct_request = direct.await_args.args[2]
    assert direct_request.grants == []
    assert direct_request.revokes == request.revokes
    assert result is not None
    assert result.direct_applied_count == 1


class _BindingTransaction:
    def __init__(
        self,
        store: list[dict[str, object]],
        *,
        fail_commit: bool = False,
    ) -> None:
        self.store = store
        self.bindings = list(store)
        self.fail_commit = fail_commit
        self.commit_calls = 0
        self.restore_calls = 0

    async def commit(self, bindings: list[dict[str, object]]) -> None:
        self.commit_calls += 1
        if self.fail_commit:
            raise RuntimeError("binding commit failed")
        self.store[:] = bindings
        self.bindings = list(bindings)

    async def restore(self) -> None:
        self.restore_calls += 1
        self.store.clear()
        self.bindings = []


class _BindingMutationService:
    def __init__(self, store: list[dict[str, object]], *, fail_commit: bool = False) -> None:
        self.store = store
        self.fail_commit = fail_commit
        self.last_transaction: _BindingTransaction | None = None

    @asynccontextmanager
    async def transaction(self):
        self.last_transaction = _BindingTransaction(
            self.store,
            fail_commit=self.fail_commit,
        )
        yield self.last_transaction


async def test_executor_rereads_authorities_and_ack_loss_is_idempotent() -> None:
    command = _grant_command()
    role_snapshot = _role_snapshot()
    binding_store: list[dict[str, object]] = []
    active_permissions: list[object] = []
    relation_models = AsyncMock(return_value=[role_snapshot])
    grant_subject_query_service = SimpleNamespace(validate_resource_grants=AsyncMock())
    service = ResourceAuthorizationService(
        get_relation_models=relation_models,
        get_bindings=AsyncMock(side_effect=lambda: list(binding_store)),
        grant_subject_query_service=grant_subject_query_service,
        binding_mutation_service=_BindingMutationService(binding_store),
    )
    executor = KnowledgeSpaceResourceGrantExecutor(authorization_service=service)

    knowledge_read = AsyncMock(return_value=SimpleNamespace(id=int(RESOURCE_ID), tenant_id=TENANT_ID, delete=0))

    async def read_user(user_id: int):
        if user_id == INVITER_USER_ID:
            return SimpleNamespace(id=user_id, user_name="inviter", tenant_id=TENANT_ID, delete=0)
        if user_id == TARGET_USER_ID:
            return SimpleNamespace(id=user_id, user_name="target", tenant_id=TENANT_ID, delete=0)
        return None

    user_read = AsyncMock(side_effect=read_user)

    async def read_permissions(*_args, **_kwargs):
        return list(active_permissions)

    async def authorize_with_lost_response(*_args, **kwargs):
        grant = kwargs["grants"][0]
        active_permissions.append(
            SimpleNamespace(
                subject_type=grant.subject_type,
                subject_id=grant.subject_id,
                relation=grant.relation,
                include_children=grant.include_children,
                model_id=grant.model_id,
            )
        )
        raise RuntimeError("grant response lost")

    authorize = AsyncMock(side_effect=authorize_with_lost_response)

    with (
        patch(
            "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id",
            new=knowledge_read,
        ),
        patch(
            "bisheng.user.domain.models.user.UserDao.aget_user",
            new=user_read,
        ),
        patch(
            "bisheng.user.domain.models.user_role.UserRoleDao.aget_user_roles",
            new=AsyncMock(return_value=[SimpleNamespace(role_id=1)]),
        ),
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service."
            "FineGrainedPermissionService.get_effective_permission_ids_async",
            new=AsyncMock(
                return_value={
                    "manage_space_relation",
                    "view_space",
                    "view_folder",
                    "view_file",
                    "download_folder",
                    "download_file",
                }
            ),
        ),
        patch(
            "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(side_effect=read_permissions),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new=authorize,
        ),
    ):
        with pytest.raises(RuntimeError, match="response lost"):
            await executor.execute(command)

        verification = await executor.verify(command)
        if not verification.applied:
            await executor.execute(command)

        assert binding_store
        active_permissions.clear()
        binding_store.clear()
        relation_models.return_value = [{**role_snapshot, "name": "Changed Viewer"}]
        with pytest.raises(PermissionDeniedError):
            await executor.execute(command)

    assert verification.applied is True
    assert verification.result_snapshot["request_id"] == command.request_id
    assert verification.result_snapshot["resource_id"] == RESOURCE_ID
    assert authorize.await_count == 1
    assert knowledge_read.await_count >= 1
    assert {call.args[0] for call in user_read.await_args_list} >= {
        INVITER_USER_ID,
        TARGET_USER_ID,
    }
    assert relation_models.await_count >= 1
    grant_subject_query_service.validate_resource_grants.assert_awaited()


async def test_executor_true_write_failure_leaves_no_binding() -> None:
    command = _grant_command()
    binding_store: list[dict[str, object]] = []
    mutation_service = _BindingMutationService(binding_store)
    service = ResourceAuthorizationService(binding_mutation_service=mutation_service)
    grant = AuthorizeGrantItem(
        subject_type="user",
        subject_id=TARGET_USER_ID,
        relation="viewer",
        model_id="viewer",
        include_children=False,
    )
    service._validate_confirmed_grant_command = AsyncMock(return_value=grant)

    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new=AsyncMock(side_effect=RuntimeError("openfga unavailable")),
        ),
    ):
        with pytest.raises(RuntimeError, match="openfga unavailable"):
            await service.execute_confirmed_grant(command)

    assert binding_store == []
    assert mutation_service.last_transaction is not None
    assert mutation_service.last_transaction.commit_calls == 0
    assert mutation_service.last_transaction.restore_calls == 1


async def test_executor_binding_commit_failure_compensates_visible_tuple() -> None:
    command = _grant_command()
    binding_store: list[dict[str, object]] = []
    active_permissions: list[object] = []
    mutation_service = _BindingMutationService(binding_store, fail_commit=True)
    service = ResourceAuthorizationService(binding_mutation_service=mutation_service)
    grant = AuthorizeGrantItem(
        subject_type="user",
        subject_id=TARGET_USER_ID,
        relation="viewer",
        model_id="viewer",
        include_children=False,
    )
    service._validate_confirmed_grant_command = AsyncMock(return_value=grant)

    async def read_permissions(*_args, **_kwargs):
        return list(active_permissions)

    async def authorize(*_args, **kwargs):
        if kwargs["grants"]:
            active_permissions.append(
                SimpleNamespace(
                    subject_type="user",
                    subject_id=TARGET_USER_ID,
                    relation="viewer",
                )
            )
        else:
            active_permissions.clear()

    authorize_mock = AsyncMock(side_effect=authorize)
    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(side_effect=read_permissions),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new=authorize_mock,
        ),
    ):
        with pytest.raises(PermissionTupleWriteError, match="binding commit failed"):
            await service.execute_confirmed_grant(command)

    assert active_permissions == []
    assert binding_store == []
    assert authorize_mock.await_count == 2
    assert authorize_mock.await_args_list[1].kwargs["grants"] == []
    assert authorize_mock.await_args_list[1].kwargs["revokes"]
    assert mutation_service.last_transaction is not None
    assert mutation_service.last_transaction.restore_calls == 1


def test_resource_authorization_owner_has_no_approval_invite_dependency() -> None:
    service_path = (
        Path(__file__).resolve().parents[2]
        / "bisheng"
        / "permission"
        / "domain"
        / "services"
        / "resource_authorization_service.py"
    )
    source = service_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_references: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_references.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_references.add(node.module)
            imported_references.update(f"{node.module}.{alias.name}" for alias in node.names)

    assert not any(reference.startswith("bisheng.approval") for reference in imported_references)
    forbidden_source_references = (
        "resource_user_invite_service",
        "resource_user_invite_scenario_handler",
        "payload_snapshot",
        "ApprovalInstanceRepository",
        "ApprovalOutboxRepository",
    )
    assert not any(reference in source for reference in forbidden_source_references)
