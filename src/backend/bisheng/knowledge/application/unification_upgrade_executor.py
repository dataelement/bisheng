"""Command-owned native fencing; request uncertainty never becomes a retry lease."""

import asyncio
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

from loguru import logger

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.knowledge.domain.repositories.unification_executor_repository import UnificationExecutorRepository


class UpgradeExecutor:
    def __init__(self, runtime, *, run_id, writer_contract_version, lease):
        self.runtime, self.lease = runtime, lease
        self.identity = {"run_id": run_id, "writer_contract_version": writer_contract_version}
        self.repository = UnificationExecutorRepository()
        self.token = None
        self.tenant_ids = ()
        self._watcher = None
        self._owner = None

    @classmethod
    @asynccontextmanager
    async def acquire(cls, runtime, *, run_id, writer_contract_version):
        repository = UnificationExecutorRepository()
        lock_factory = getattr(runtime, "executor_lock", None)
        lock = lock_factory() if lock_factory is not None else repository.acquire(runtime.engine)
        async with lock as lease:
            await lease.ensure()
            instance = cls(runtime, run_id=run_id, writer_contract_version=writer_contract_version, lease=lease)
            try:
                yield instance
            finally:
                if instance._watcher is not None:
                    instance._watcher.cancel()
                    with suppress(asyncio.CancelledError):
                        await instance._watcher

    async def start(self, tenant_ids, *, preparing_binding=None):
        await self.lease.ensure()
        self.tenant_ids = tenant_ids
        token, active = uuid4().hex, False
        with tenant_execution_scope(1):
            async with self.runtime.sessions() as session, session.begin():
                # All preparing rows are created atomically so the native
                # global ledger never observes a partial tenant inventory.
                for tenant_id in tenant_ids:
                    with tenant_execution_scope(tenant_id):
                        row = await self.repository.runs.aget_or_create(session, **self.identity)
                        previous = self.repository._latest(row)
                        if previous is not None and previous[2]["pending"] is not None:
                            raise KnowledgeOperationPlanConflictError(reason="migration_executor_recovery_required")
                        if row.phase == "failed":
                            await self.repository.runs.aresume(
                                session, **self.identity, baseline_hash=row.baseline_hash, plan_hash=row.plan_hash
                            )
                        current = await self.repository.abegin_attempt(session, **self.identity, token=token)
                        active = active or current is not None
                if preparing_binding is not None:
                    from bisheng.knowledge.domain.repositories.unification_upgrade_repository import (
                        UpgradeRunRepository,
                    )

                    # Creation, durable generation and original flow binding
                    # have one commit boundary: no orphan preparing state can
                    # survive a crash between start and the history owner.
                    await UpgradeRunRepository().abind_preparing(
                        session, **self.identity, tenant_ids=tenant_ids, binding=preparing_binding
                    )
                self.token = token if active else None
        if self.token is not None:
            self._owner = asyncio.current_task()
            self._watcher = asyncio.create_task(self._watch(), name="f118-control-lock")

    async def _watch(self):
        while True:
            await asyncio.sleep(5)
            try:
                await self.lease.ensure()
            except Exception:
                # No new connection or optimistic takeover. Durable dispatch
                # records remain pending even if cancellation cannot be saved.
                self._owner.cancel("f118_control_lock_lost")
                return

    async def transaction_guard(self, session, locked_run):
        await self.lease.ensure()
        if locked_run.phase == "completed":
            # Native completed paths are strictly read-only. No checkpoint or
            # external intent may be added to these rows.
            return
        with tenant_execution_scope(locked_run.tenant_id):
            await self.repository.acheck_attempt(session, **self.identity, token=self.token)

    async def permission_transaction_guard(self, session, _locked_run=None):
        """Injected through permission's own explicit maintenance context."""
        await self.lease.ensure()
        _, state = await self.repository.acheck_attempt(session, **self.identity, token=self.token)
        if state["pending"] is not None and state["pending"].get("outcome") == "unknown":
            raise KnowledgeOperationPlanConflictError(reason="migration_executor_recovery_required")

    async def guard_all(self, session):
        for tenant in self.tenant_ids:
            with tenant_execution_scope(tenant):
                row = await self.repository.runs._required(session, **self.identity)
                if row.phase != "completed":
                    await self.permission_transaction_guard(session)

    async def assert_settled(self):
        await self.lease.ensure()
        async with self.runtime.sessions() as session, session.begin():
            for tenant in self.tenant_ids:
                with tenant_execution_scope(tenant):
                    row = await self.repository.runs._required(session, **self.identity)
                    latest = self.repository._latest(row)
                    if latest is not None and latest[2]["pending"] is not None:
                        raise KnowledgeOperationPlanConflictError(reason="migration_executor_recovery_required")

    async def begin(self, *, kind, identity):
        await self.lease.ensure()
        tenant_id = identity.get("tenant_id", get_current_tenant_id())
        with tenant_execution_scope(tenant_id):
            async with self.runtime.sessions() as session, session.begin():
                ticket = await self.repository.abegin_external(
                    session, **self.identity, token=self.token, kind=kind, identity=identity
                )
                return tenant_id, ticket

    async def finish(self, ticket, *, outcome, receipt=None):
        await self.lease.ensure()
        tenant_id, intent_ticket = ticket
        with tenant_execution_scope(tenant_id):
            async with self.runtime.sessions() as session, session.begin():
                await self.repository.afinish_external(
                    session, **self.identity, token=self.token, ticket=intent_ticket, outcome=outcome, receipt=receipt
                )

    async def finish_attempt(self, *, preserve_error=False):
        if self.token is None:
            return
        try:
            await self.lease.ensure()
            with tenant_execution_scope(1):
                async with self.runtime.sessions() as session, session.begin():
                    for tenant_id in self.tenant_ids:
                        with tenant_execution_scope(tenant_id):
                            row = await self.repository.runs.aget(session, **self.identity)
                            if row is not None and row.phase != "completed":
                                await self.repository.afinish_attempt(session, **self.identity, token=self.token)
        except Exception:
            if not preserve_error:
                raise
            logger.warning("F118 executor remains unresolved; original operation error preserved")
