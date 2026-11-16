"""F133 formal permission assembly and durable retry safety."""

import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest


def module():
    name = "bisheng.workflow.application.kunlian_permission_api"
    assert importlib.util.find_spec(name) is not None, "formal permission API missing"
    return importlib.import_module(name)


async def test_durable_receipts_survive_new_instances_and_bind_request(monkeypatch):
    api = module()
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.workflow.application.kunlian_workflow_authorization import GrantReceiptResult
    from bisheng.workflow.domain.models.kunlian_grant_receipt import KunlianGrantReceipt
    from bisheng.workflow.domain.repositories import kunlian_grant_receipt as repo

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(KunlianGrantReceipt.__table__.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(repo, "get_async_db_session", sessions)
    try:
        with tenant_execution_scope(7):
            first = repo.KunlianGrantReceiptRepository()
            receipt, claimed = await first.claim_or_read("key", "digest")
            assert claimed and receipt.result is None
            await first.complete("key", GrantReceiptResult("APPLIED", 9))
            reread, claimed = await repo.KunlianGrantReceiptRepository().claim_or_read("key", "other")
            assert not claimed and reread.digest == "digest"
            assert reread.result == GrantReceiptResult("APPLIED", 9)
        with tenant_execution_scope(8):
            _, claimed = await repo.KunlianGrantReceiptRepository().claim_or_read("key", "other")
            assert claimed
    finally:
        await engine.dispose()
    assert api.KunlianPermissionApi is not None


class Identities:
    async def resolve(self, *, connection_id, external_tenant_id, external_user_id):
        return SimpleNamespace(
            tenant_id=7 if external_user_id != "cross" else 8,
            user_id=10 if external_user_id == "actor" else 20,
            is_global_super=False,
        )


class Permissions:
    def __init__(self):
        self.mutations = []
        self.outcomes = {}
        self.protected = False

    async def get_grantable_models(self, **kwargs):
        return [{"key": "current-model", "active": True}]

    async def mutate_grants(self, *, request, **kwargs):
        self.mutations.append(request)
        self.outcomes[request.idempotency_key] = ("FINALIZED", 3)
        return {"resource_version": 3}

    async def get_workflow_grant_outcome(self, *, idempotency_key, **kwargs):
        return self.outcomes.get(idempotency_key)

    async def check_workflow_direct_user_grant(self, **kwargs):
        if self.protected:
            from bisheng.common.errcode.permission import ProtectedAssignmentMutationError

            raise ProtectedAssignmentMutationError()


class Receipts:
    def __init__(self):
        self.rows = {}

    async def claim_or_read(self, key, digest):
        from bisheng.workflow.application.kunlian_workflow_authorization import GrantReceipt

        first = key not in self.rows
        self.rows.setdefault(key, GrantReceipt(digest, key))
        return self.rows[key], first

    async def complete(self, key, result):
        from dataclasses import replace

        self.rows[key] = replace(self.rows[key], result=result)
        return result


async def test_formal_change_resolves_external_target_and_replays_without_remutation():
    api = module()
    from bisheng.open_api.application.kunlian_access import KunlianRequestUser
    from bisheng.open_api.domain.services.kunlian_credential import KunlianPrincipal
    from bisheng.permission.application.identity import PermissionActor
    from bisheng.workflow.application.kunlian_workflow_authorization import AuthorizationError, GrantChange

    class Targets:
        async def resolve(self, *, resource_id, **kwargs):
            return SimpleNamespace(tenant_id=7, resource_type="workflow", resource_id=resource_id)

    class Decisions:
        async def check(self, **kwargs):
            return True

    user = KunlianRequestUser(
        KunlianPrincipal(1, "integration", "identity", "ext", frozenset({"grant"}), 1),
        SimpleNamespace(user_id=10, tenant_id=7, is_global_super=False),
        "ext",
        "actor",
    )
    permissions, receipts = Permissions(), Receipts()

    async def actor_reader(_user):
        return PermissionActor(subject_type="user", subject_id=10, tenant_id=7)

    service = api.KunlianPermissionApi(
        permissions=permissions,
        targets=Targets(),
        decisions=Decisions(),
        identities=Identities(),
        receipts=receipts,
        actor_reader=actor_reader,
    )
    change = GrantChange(1, 2, subject_ref="target", model_key="current-model")
    result = await service.change(user, "workflow", change, "retry")
    assert result["status"] == "APPLIED"
    assert permissions.mutations[0].changes[0].subject.id == "20"
    assert await service.change(user, "workflow", change, "retry") == result
    assert len(permissions.mutations) == 1
    # Simulate a crash after F048 committed but before receipt completion; a new
    # application instance must reconcile the original operation, not mutate again.
    from dataclasses import replace

    receipt_key = next(iter(receipts.rows))
    receipts.rows[receipt_key] = replace(receipts.rows[receipt_key], result=None)
    recovered = api.KunlianPermissionApi(
        permissions=permissions,
        targets=Targets(),
        decisions=Decisions(),
        identities=Identities(),
        receipts=receipts,
        actor_reader=actor_reader,
    )
    assert await recovered.change(user, "workflow", change, "retry") == result
    assert len(permissions.mutations) == 1
    receipts.rows[receipt_key] = replace(receipts.rows[receipt_key], result=None)
    permissions.outcomes[receipt_key] = ("PROJECTING", None)
    assert (await recovered.change(user, "workflow", change, "retry"))["status"] == "PENDING"
    assert len(permissions.mutations) == 1
    with pytest.raises(AuthorizationError, match="IDEMPOTENCY_CONFLICT"):
        await service.change(
            user, "workflow", GrantChange(1, 2, subject_ref="other", model_key="current-model"), "retry"
        )
    with pytest.raises(AuthorizationError, match="NOT_FOUND"):
        await service.change(
            user, "workflow", GrantChange(1, 2, subject_ref="cross", model_key="current-model"), "cross"
        )
    permissions.protected = True
    with pytest.raises(AuthorizationError, match="NOT_FOUND"):
        await service.change(
            user, "workflow", GrantChange(1, 2, assignee_id="4", expected_assignee_version=0), "protected"
        )
    assert len(permissions.mutations) == 1
