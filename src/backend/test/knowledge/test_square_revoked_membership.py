"""TC-120-DSQ-014: current permission decides joined and reapplication.

Compile the owning service methods with isolated repository and approval ports;
provider and middleware startup stay outside this regression.
"""

import ast
import asyncio
import sys
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import Field, SQLModel

BACKEND = Path(__file__).resolve().parents[2]
SERVICE = BACKEND / "bisheng/knowledge/domain/services/knowledge_space_service.py"


class Status(StrEnum):
    SUBSCRIBED = "subscribed"
    PENDING = "pending"
    REJECTED = "rejected"
    NOT_SUBSCRIBED = "not_subscribed"


class Membership(StrEnum):
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    REJECTED = "REJECTED"


class Role(StrEnum):
    CREATOR = "creator"
    ADMIN = "admin"
    MEMBER = "member"


class Auth(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"
    APPROVAL = "approval"


class Info(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(user_role=None, **kwargs)


class MemberRow(SQLModel, table=True):
    __tablename__ = "revoked_membership_test"
    id: int | None = Field(default=None, primary_key=True)
    business_id: str
    business_type: str
    user_id: int
    user_role: str
    status: str


@pytest.fixture
def context(monkeypatch):
    member = SimpleNamespace(
        user_id=7,
        user_role=Role.MEMBER,
        status=Membership.ACTIVE,
        is_active=True,
        is_pending=False,
        is_recently_rejected=lambda: False,
    )
    space_data = {
        "id": 74,
        "user_id": 1,
        "tenant_id": 1,
        "name": "KS1030T46",
        "auth_type": Auth.APPROVAL,
        "type": 3,
        "state": 1,
        "model": "embedding",
    }
    space = SimpleNamespace(**space_data, model_dump=lambda: space_data)
    worker = ModuleType("bisheng.worker")
    worker.rebuild_knowledge_celery = SimpleNamespace()
    user_module = ModuleType("bisheng.user.domain.services.user")
    user_module.UserService = SimpleNamespace(get_avatar_share_link=AsyncMock())
    monkeypatch.setitem(sys.modules, worker.__name__, worker)
    monkeypatch.setitem(sys.modules, user_module.__name__, user_module)
    members = SimpleNamespace(
        async_find_member=AsyncMock(return_value=member), async_count_space_members=AsyncMock(return_value=2)
    )
    knowledge = SimpleNamespace(
        aquery_by_id=AsyncMock(return_value=space),
        async_get_public_spaces_paginated=AsyncMock(return_value=[(space, Membership.ACTIVE, None, 2)]),
        async_count_public_spaces=AsyncMock(return_value=1),
    )
    namespace = {
        "KnowledgeUtils": object,
        "datetime": datetime,
        "asyncio": asyncio,
        "perf_counter": perf_counter,
        "contextmanager": contextmanager,
        "emit_metric": Mock(),
        "SpaceSubscriptionStatusEnum": Status,
        "MembershipStatusEnum": Membership,
        "UserRoleEnum": Role,
        "AuthTypeEnum": Auth,
        "KnowledgeTypeEnum": SimpleNamespace(SPACE=SimpleNamespace(value=3)),
        "KnowledgeState": SimpleNamespace(PUBLISHED=SimpleNamespace(value=1)),
        "KnowledgeSpaceInfoResp": Info,
        "KnowledgeDao": knowledge,
        "SpaceChannelMemberDao": members,
        "KnowledgeFileDao": SimpleNamespace(async_count_success_files_batch=AsyncMock(return_value={74: 1})),
        "UserDao": SimpleNamespace(
            aget_user=AsyncMock(return_value=SimpleNamespace(user_name="owner")),
            aget_user_by_ids=AsyncMock(return_value=[]),
        ),
        "UserDepartmentDao": SimpleNamespace(aget_user_primary_department=AsyncMock(return_value=None)),
        "batch_check_business_visible": AsyncMock(return_value={"74": False}),
        "ApprovalGateRequest": lambda **kw: SimpleNamespace(**kw),
        "ApprovalGateDecision": SimpleNamespace(PENDING="pending"),
    }
    tree = ast.parse(SERVICE.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "KnowledgeSpaceService")
    selected = {
        "_resolve_subscription_status",
        "_resolve_subscription_status_from_fields",
        "_resolve_effective_subscription_status",
        "_exclude_failed_subscriptions",
        "_apply_subscription_flags",
        "get_space_info",
        "get_knowledge_square",
        "subscribe_space",
    }
    cls.body = [node for node in cls.body if getattr(node, "name", None) in selected]
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[]
    )
    exec(compile(ast.fix_missing_locations(module), str(SERVICE), "exec"), namespace)
    service = namespace["KnowledgeSpaceService"]()
    service.login_user = SimpleNamespace(user_id=7, user_name="viewer", tenant_id=1)
    service.request = None
    service.message_service = None
    service._permission_actor_resolve_count = 0
    service._permission_actor_cache_hits = 0
    service._permission_actor_resolve_elapsed_ms = 0.0
    service._require_space_info_permission = AsyncMock(return_value=(space, False))
    service._has_joined_visibility = AsyncMock(return_value=False)
    service._get_effective_actions = AsyncMock(return_value=set())
    service._check_action = AsyncMock(return_value=False)
    service._decorate_department_metadata = AsyncMock()
    service._decorate_auto_tag_for_info = AsyncMock()
    service.approval_gate = SimpleNamespace(
        request_or_pass=AsyncMock(return_value=SimpleNamespace(decision="pending", task_ids=[]))
    )
    service._persist_space_member = AsyncMock(
        return_value=SimpleNamespace(user_id=7, user_role=Role.MEMBER, status=Membership.PENDING)
    )
    service.sync_direct_space_user_permissions = AsyncMock()
    # subscribe_space uses the class-owned permission projector.
    type(service).sync_direct_space_user_permissions = service.sync_direct_space_user_permissions
    return SimpleNamespace(service=service, member=member, space=space, namespace=namespace)


@pytest.mark.parametrize("status", [Status.SUBSCRIBED, Status.NOT_SUBSCRIBED])
@pytest.mark.parametrize("visible", [False, True])
def test_joined_status_uses_current_visibility(context, status, visible):
    expected = Status.SUBSCRIBED if visible else Status.NOT_SUBSCRIBED
    assert context.service._resolve_effective_subscription_status(status, has_visible=visible) == expected


@pytest.mark.parametrize("status", [Status.PENDING, Status.REJECTED])
@pytest.mark.parametrize("visible", [False, True])
def test_application_states_are_only_shown_without_current_visibility(context, status, visible):
    expected = Status.SUBSCRIBED if visible else status
    assert context.service._resolve_effective_subscription_status(status, has_visible=visible) == expected


@pytest.mark.parametrize("role", [Role.MEMBER, Role.ADMIN])
async def test_info_and_square_clear_stale_joined_state_after_revocation(context, role):
    context.member.user_role = role
    info = await context.service.get_space_info(74)
    square = await context.service.get_knowledge_square()
    assert info.subscription_status == square["data"][0].subscription_status == Status.NOT_SUBSCRIBED
    assert info.is_followed is False
    assert square["data"][0].is_followed is False
    assert info.user_role is None
    assert info.actions == []


@pytest.mark.parametrize("failed", [False, True])
async def test_failed_execution_is_not_displayed_as_pending_in_info_or_square(context, monkeypatch, failed):
    from bisheng.approval.application import request_state

    context.member.is_active = False
    context.member.is_pending = True
    context.member.status = Membership.PENDING
    context.namespace["KnowledgeDao"].async_get_public_spaces_paginated.return_value = [
        (context.space, Membership.PENDING, None, 2)
    ]
    lookup = AsyncMock(return_value=frozenset({"space:74:user:7"}) if failed else frozenset())
    monkeypatch.setattr(request_state, "get_failed_request_keys", lookup)

    info = await context.service.get_space_info(74)
    square = await context.service.get_knowledge_square()

    expected = Status.NOT_SUBSCRIBED if failed else Status.PENDING
    assert info.subscription_status == square["data"][0].subscription_status == expected
    assert info.is_pending == square["data"][0].is_pending == (not failed)
    assert info.is_followed is False
    assert info.actions == []
    assert lookup.await_count == 2


async def test_failed_subscription_lookup_batches_only_pending_rows(context, monkeypatch):
    from bisheng.approval.application import request_state

    lookup = AsyncMock(return_value=frozenset({"space:74:user:7"}))
    monkeypatch.setattr(request_state, "get_failed_request_keys", lookup)
    states = {74: Status.PENDING, 75: Status.SUBSCRIBED, 76: Status.REJECTED}
    await context.service._exclude_failed_subscriptions(states)
    assert states == {74: Status.NOT_SUBSCRIBED, 75: Status.SUBSCRIBED, 76: Status.REJECTED}
    lookup.assert_awaited_once_with(
        tenant_id=1,
        scenario_code="knowledge_space_subscribe_request",
        applicant_user_id=7,
        business_keys=["space:74:user:7"],
    )


async def test_failed_reapplication_does_not_persist_pending_member_or_notify(context):
    from bisheng.approval.domain.services.approval_gate import ApprovalGate
    from bisheng.common.errcode.approval import ApprovalExecutionFailedError

    context.member.status = Membership.PENDING
    context.service.approval_gate = ApprovalGate(
        registry=SimpleNamespace(get_handler=AsyncMock()),
        instance_repository=SimpleNamespace(
            find_duplicate_active_instance=AsyncMock(return_value=SimpleNamespace(id=16, status="execute_failed"))
        ),
    )
    with pytest.raises(ApprovalExecutionFailedError):
        await context.service.subscribe_space(74)
    context.service._persist_space_member.assert_not_awaited()
    context.service.sync_direct_space_user_permissions.assert_not_awaited()


async def test_effective_direct_or_inherited_grant_still_displays_joined(context):
    context.service._require_space_info_permission.return_value = (context.space, True)
    context.service._has_joined_visibility.return_value = True
    context.namespace["batch_check_business_visible"].return_value = {"74": True}
    info = await context.service.get_space_info(74)
    square = await context.service.get_knowledge_square()
    assert info.subscription_status == square["data"][0].subscription_status == Status.SUBSCRIBED
    assert info.user_role == Role.MEMBER


@pytest.mark.parametrize("role", [Role.MEMBER, Role.ADMIN])
async def test_stale_active_membership_reenters_approval(context, role):
    context.member.user_role = role
    result = await context.service.subscribe_space(74)
    assert result == {"status": "pending", "space_id": 74}
    context.service.approval_gate.request_or_pass.assert_awaited_once()
    context.service._persist_space_member.assert_awaited_once_with(context.member, 74, Membership.PENDING)
    context.service.sync_direct_space_user_permissions.assert_not_awaited()


async def test_member_with_current_access_keeps_idempotent_join(context):
    context.service._check_action.return_value = True
    context.service._has_joined_visibility.return_value = True
    assert await context.service.subscribe_space(74) == {"status": "subscribed", "space_id": 74}
    context.service.approval_gate.request_or_pass.assert_not_awaited()
    context.service._persist_space_member.assert_not_awaited()


async def test_approval_auto_pass_still_projects_the_new_member(context):
    context.service.approval_gate.request_or_pass.return_value = SimpleNamespace(decision="pass")
    assert await context.service.subscribe_space(74) == {"status": "subscribed", "space_id": 74}
    context.service.sync_direct_space_user_permissions.assert_awaited_once_with(
        74,
        7,
        Role.MEMBER,
        is_active=True,
        operator_user_id=7,
    )


async def test_creator_keeps_ownership_without_reapplying(context):
    context.space.user_id = 7
    assert await context.service.subscribe_space(74) == {"status": "subscribed", "space_id": 74}
    info = await context.service.get_space_info(74)
    square = await context.service.get_knowledge_square()
    assert info.subscription_status == square["data"][0].subscription_status == Status.SUBSCRIBED
    context.service.approval_gate.request_or_pass.assert_not_awaited()
    context.service._persist_space_member.assert_not_awaited()


@pytest.mark.parametrize("existing", [True, False])
async def test_reapplication_storage_uses_member_role(existing):
    from sqlmodel import Session, create_engine, select, update

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[MemberRow.__table__])
    with Session(engine) as session:
        if existing:
            session.add(
                MemberRow(
                    business_id="74", business_type="space", user_id=7, user_role=Role.ADMIN, status=Membership.ACTIVE
                )
            )
            session.commit()

        class AsyncSessionPort:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def exec(self, statement):
                return session.exec(statement)

            async def commit(self):
                session.commit()

            async def refresh(self, row):
                session.refresh(row)

            def add(self, row):
                session.add(row)

        namespace = {
            "SpaceChannelMember": MemberRow,
            "BusinessTypeEnum": SimpleNamespace(SPACE="space"),
            "UserRoleEnum": Role,
            "MembershipStatusEnum": Membership,
            "get_async_db_session": AsyncSessionPort,
            "select": select,
            "update": update,
        }
        path = BACKEND / "bisheng/common/models/space_channel_member.py"
        tree = ast.parse(path.read_text())
        cls = next(
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SpaceChannelMemberDao"
        )
        cls.body = [node for node in cls.body if getattr(node, "name", None) == "async_upsert_space_member_status"]
        module = ast.Module(
            body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls],
            type_ignores=[],
        )
        exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
        row = await namespace["SpaceChannelMemberDao"].async_upsert_space_member_status(74, 7, Membership.PENDING)
        assert row.user_role == Role.MEMBER
        assert row.status == Membership.PENDING
