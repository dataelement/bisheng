from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import select

from bisheng.approval.domain.ports.scenario_policy import (
    ApprovalSubmissionCommand,
    ApprovalSubmissionResult,
)
from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.permission.domain.models.resource_user_invite_request import (
    ResourceUserInviteExecutionState,
    ResourceUserInviteRequest,
)
from bisheng.permission.domain.services import resource_user_invite_application_service as application_module
from bisheng.permission.domain.services.resource_user_invite_application_service import (
    ResourceUserInviteApplicationService,
)


@asynccontextmanager
async def _no_op_lock(**_identity):
    class Lock:
        @staticmethod
        def ensure_owned() -> None:
            return None

    yield Lock()


class FakeApprovalSubmissionPort:
    def __init__(self) -> None:
        self.commands: list[ApprovalSubmissionCommand] = []
        self.rows_seen_before_submission: list[int] = []
        self.post_commit_request_ids: list[int] = []
        self.failures_by_target_user_id: dict[int, BaseException] = {}
        self.emit_post_commit_effect = True

    async def submit_in_uow(
        self,
        *,
        session: AsyncSession,
        command: ApprovalSubmissionCommand,
    ) -> ApprovalSubmissionResult:
        self.commands.append(command)
        request_id = int(command.business_request_id)
        row = await session.get(ResourceUserInviteRequest, request_id)
        assert row is not None
        assert row.approval_instance_id is None
        assert session.in_transaction()
        self.rows_seen_before_submission.append(request_id)

        target_user_id = command.initial_approver_user_ids[0]
        failure = self.failures_by_target_user_id.get(target_user_id)
        if failure is not None:
            raise failure

        async def record_post_commit() -> None:
            self.post_commit_request_ids.append(request_id)

        effects = (record_post_commit,) if self.emit_post_commit_effect else ()
        return ApprovalSubmissionResult(
            instance_id=10_000 + request_id,
            task_ids=(20_000 + request_id,),
            post_commit_effects=effects,
        )


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(ResourceUserInviteRequest.__table__.create)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    tenant_token = set_current_tenant_id(7)
    try:
        yield factory
    finally:
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


def _service(
    session_factory: async_sessionmaker[AsyncSession],
    submission_port: FakeApprovalSubmissionPort,
) -> ResourceUserInviteApplicationService:
    return ResourceUserInviteApplicationService(
        session_factory=session_factory,
        submission_port=submission_port,
        lock_factory=_no_op_lock,
    )


def _invite_kwargs(**overrides) -> dict[str, object]:
    values: dict[str, object] = {
        "tenant_id": 7,
        "resource_type": "knowledge_space",
        "resource_id": "88",
        "resource_name": "Docs",
        "inviter_user_id": 101,
        "inviter_user_name": "inviter-a",
        "target_user_id": 201,
        "target_user_name": "target-a",
        "relation": "editor",
        "model_id": "model-1",
        "include_children": True,
        "role_snapshot": {"permissions": ["read", "write"], "name": "editor"},
    }
    values.update(overrides)
    return values


async def _get_request(
    session_factory: async_sessionmaker[AsyncSession],
    request_id: int,
) -> ResourceUserInviteRequest | None:
    async with session_factory() as session:
        return await session.get(ResourceUserInviteRequest, request_id)


async def _list_requests(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[ResourceUserInviteRequest]:
    async with session_factory() as session:
        rows = await session.execute(select(ResourceUserInviteRequest).order_by(ResourceUserInviteRequest.id))
        return list(rows.scalars().all())


async def _set_state_and_marker(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    request_id: int,
    execution_state: str,
    active_marker: int,
) -> None:
    async with session_factory() as session, session.begin():
        row = await session.get(ResourceUserInviteRequest, request_id)
        assert row is not None
        row.execution_state = execution_state
        row.active_marker = active_marker


async def test_business_row_precedes_submission_and_binding_commits_in_same_uow(session_factory) -> None:
    submission_port = FakeApprovalSubmissionPort()
    service = _service(session_factory, submission_port)

    result = await service.request_invite(**_invite_kwargs())

    assert result["outcome"] == "invite_created"
    request_id = result["request_id"]
    assert submission_port.rows_seen_before_submission == [request_id]
    row = await _get_request(session_factory, request_id)
    assert row is not None
    assert row.approval_instance_id == 10_000 + request_id
    assert result["approval_instance_id"] == row.approval_instance_id
    assert submission_port.post_commit_request_ids == [request_id]

    command = submission_port.commands[0]
    assert command.business_request_type == "resource_user_invite_request"
    assert command.business_request_id == str(request_id)
    assert command.initial_approver_user_ids == (201,)
    assert command.request_fingerprint == row.request_fingerprint


async def test_first_request_is_created_when_submission_has_no_post_commit_effects(session_factory) -> None:
    submission_port = FakeApprovalSubmissionPort()
    submission_port.emit_post_commit_effect = False
    service = _service(session_factory, submission_port)

    result = await service.request_invite(**_invite_kwargs())

    assert result["outcome"] == "invite_created"
    assert result["approval_instance_id"] is not None
    assert submission_port.post_commit_request_ids == []


async def test_disabled_approval_scenario_rolls_back_business_request(session_factory) -> None:
    submission_port = FakeApprovalSubmissionPort()
    submission_port.failures_by_target_user_id[201] = ApprovalScenarioDisabledError()
    service = _service(session_factory, submission_port)

    with pytest.raises(ApprovalScenarioDisabledError) as error:
        await service.request_invite(**_invite_kwargs())

    assert error.value.code == 18106
    assert submission_port.rows_seen_before_submission
    assert await _list_requests(session_factory) == []
    assert submission_port.post_commit_request_ids == []


@pytest.mark.parametrize("tenant_context", [None, 8])
async def test_missing_or_mismatched_tenant_context_fails_before_side_effects(
    session_factory,
    tenant_context,
) -> None:
    submission_port = FakeApprovalSubmissionPort()
    service = _service(session_factory, submission_port)
    tenant_token = current_tenant_id.set(tenant_context)
    try:
        with pytest.raises(ValueError, match="matching tenant context"):
            await service.request_invite(**_invite_kwargs())
    finally:
        current_tenant_id.reset(tenant_token)

    assert await _list_requests(session_factory) == []
    assert submission_port.commands == []


async def test_duplicate_across_inviters_returns_first_request_and_role_snapshot(session_factory) -> None:
    submission_port = FakeApprovalSubmissionPort()
    service = _service(session_factory, submission_port)
    first_role = {"permissions": ["read"], "name": "viewer"}

    first = await service.request_invite(**_invite_kwargs(role_snapshot=first_role, relation="viewer"))
    duplicate = await service.request_invite(
        **_invite_kwargs(
            inviter_user_id=102,
            inviter_user_name="inviter-b",
            role_snapshot={"permissions": ["admin"], "name": "owner"},
            relation="owner",
        )
    )

    assert duplicate["outcome"] == "invite_existing"
    assert duplicate["request_id"] == first["request_id"]
    assert duplicate["relation"] == "viewer"
    assert duplicate["role_snapshot"] == first_role
    assert len(submission_port.commands) == 1
    assert len(await _list_requests(session_factory)) == 1


@pytest.mark.parametrize(
    "terminal_state",
    [ResourceUserInviteExecutionState.APPLIED, ResourceUserInviteExecutionState.CLOSED],
)
async def test_terminal_request_releases_active_marker_for_a_new_invite(session_factory, terminal_state) -> None:
    submission_port = FakeApprovalSubmissionPort()
    service = _service(session_factory, submission_port)
    first = await service.request_invite(**_invite_kwargs())
    first_request_id = first["request_id"]
    await _set_state_and_marker(
        session_factory,
        request_id=first_request_id,
        execution_state=terminal_state,
        active_marker=first_request_id,
    )

    second = await service.request_invite(**_invite_kwargs(inviter_user_id=102, inviter_user_name="inviter-b"))

    assert second["outcome"] == "invite_created"
    assert second["request_id"] != first_request_id
    assert len(submission_port.commands) == 2


async def test_failed_request_keeps_active_marker_and_blocks_reapproval(session_factory) -> None:
    submission_port = FakeApprovalSubmissionPort()
    service = _service(session_factory, submission_port)
    first = await service.request_invite(**_invite_kwargs())
    first_request_id = first["request_id"]
    await _set_state_and_marker(
        session_factory,
        request_id=first_request_id,
        execution_state=ResourceUserInviteExecutionState.FAILED,
        active_marker=0,
    )

    duplicate = await service.request_invite(**_invite_kwargs(inviter_user_id=102, inviter_user_name="inviter-b"))

    assert duplicate["outcome"] == "invite_existing"
    assert duplicate["request_id"] == first_request_id
    assert duplicate["execution_state"] == ResourceUserInviteExecutionState.FAILED
    assert len(submission_port.commands) == 1


async def test_role_snapshot_and_fingerprints_are_canonical_and_immutable(session_factory) -> None:
    submission_port = FakeApprovalSubmissionPort()
    service = _service(session_factory, submission_port)
    role_snapshot = {"z": [3, 2, 1], "a": {"write": True, "read": True}}
    canonical_role = json.dumps(
        role_snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    result = await service.request_invite(**_invite_kwargs(role_snapshot=role_snapshot))
    row = await _get_request(session_factory, result["request_id"])

    assert row is not None
    assert row.role_snapshot == role_snapshot
    assert row.role_fingerprint == hashlib.sha256(canonical_role.encode()).hexdigest()
    assert row.request_fingerprint == submission_port.commands[0].request_fingerprint

    role_snapshot["z"].append(0)
    persisted = await _get_request(session_factory, result["request_id"])
    assert persisted is not None
    assert persisted.role_snapshot["z"] == [3, 2, 1]


async def test_each_target_has_an_independent_result_and_transaction(session_factory) -> None:
    submission_port = FakeApprovalSubmissionPort()
    submission_port.failures_by_target_user_id[202] = RuntimeError("target submission failed")
    service = _service(session_factory, submission_port)

    first = await service.request_invite(**_invite_kwargs(target_user_id=201, target_user_name="target-a"))
    with pytest.raises(RuntimeError, match="target submission failed"):
        await service.request_invite(**_invite_kwargs(target_user_id=202, target_user_name="target-b"))
    third = await service.request_invite(**_invite_kwargs(target_user_id=203, target_user_name="target-c"))

    rows = await _list_requests(session_factory)
    assert [row.target_user_id for row in rows] == [201, 203]
    assert [first["target_user_id"], third["target_user_id"]] == [201, 203]
    assert len(submission_port.commands) == 3


async def test_pending_list_reads_permission_facts_without_approval_payload(session_factory) -> None:
    submission_port = FakeApprovalSubmissionPort()
    service = _service(session_factory, submission_port)
    first = await service.request_invite(**_invite_kwargs(target_user_id=201, target_user_name="target-a"))
    second = await service.request_invite(**_invite_kwargs(target_user_id=202, target_user_name="target-b"))
    await service.request_invite(
        **_invite_kwargs(
            resource_id="other-resource",
            target_user_id=203,
            target_user_name="target-c",
        )
    )
    await _set_state_and_marker(
        session_factory,
        request_id=second["request_id"],
        execution_state=ResourceUserInviteExecutionState.CLOSED,
        active_marker=second["request_id"],
    )
    calls_before_list = len(submission_port.commands)

    pending = await service.list_pending_invites(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id="88",
    )

    assert [row.id for row in pending] == [first["request_id"]]
    assert pending[0].target_user_id == 201
    assert pending[0].role_snapshot == {"permissions": ["read", "write"], "name": "editor"}
    assert len(submission_port.commands) == calls_before_list

    source = inspect.getsource(application_module)
    assert "payload_snapshot" not in source
    assert "ApprovalInstance" not in source
    assert "approval.domain.models" not in source
    assert "approval.domain.repositories" not in source
